"""Worker `process_webhook_event` — resolve contato/conversa, persiste
mensagem e aplica o buffer de debounce (`docs/04-motor-de-conversa.md` §1,
roadmap 2.5).

`process_turn` (o loop de tool calling de verdade) é a tarefa 3.4 — aqui é
só um stub que drena o buffer e loga, para o encadeamento
webhook → buffer → turno já ser real e testável antes da Fase 3.
"""

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from arq import ArqRedis
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.channels.base import InboundMessage
from app.channels.factory import build_adapter
from app.config import get_settings
from app.core.buffer import drain_buffer, enqueue_message
from app.core.db import tenant_session
from app.core.locks import conversation_lock
from app.core.tenancy import TenantContext
from app.models import Message, WebhookEvent
from app.repositories.channel import ChannelRepository
from app.services.conversation import get_or_create_contact, get_or_create_conversation

logger = structlog.get_logger()

# Casos que ignoram o buffer e processam na hora (`docs/04` §1). A detecção
# completa de opt-out (regex + classificador) é a tarefa 6.2 — isto aqui é só
# o suficiente para não fazer um lead que pediu pra sair esperar o debounce.
_OPT_OUT_RE = re.compile(r"^\s*(sair|parar|descadastrar|cancelar)\s*[.!]?\s*$", re.IGNORECASE)


def _deve_pular_buffer(msg: InboundMessage) -> bool:
    if msg.content_type == "interactive":
        return True
    return bool(msg.text and _OPT_OUT_RE.match(msg.text))


async def _inserir_mensagem_idempotente(
    session: Any, *, tenant_id: uuid.UUID, conversation_id: uuid.UUID, msg: InboundMessage
) -> uuid.UUID | None:
    """`INSERT ... ON CONFLICT DO NOTHING` na `UNIQUE(tenant_id,
    provider_message_id)` — o WhatsApp reenvia webhook, processar duas vezes
    não pode gerar mensagem duplicada (`CLAUDE.md` §4.2). Retorna `None` se
    já existia (evento duplicado, nada a fazer)."""
    stmt = (
        pg_insert(Message)
        .values(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            direction="inbound",
            sender_type="lead",
            content_type=msg.content_type,
            content=msg.text,
            media_mime=msg.media_mime,
            provider_message_id=msg.provider_message_id or None,
            provider_status="delivered",
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "provider_message_id"])
        .returning(Message.id)
    )
    result = await session.execute(stmt)
    message_id: uuid.UUID | None = result.scalar_one_or_none()
    return message_id


async def _processar_mensagem(
    session: Any,
    pool: ArqRedis,
    *,
    tenant_id: uuid.UUID,
    channel_id: uuid.UUID,
    msg: InboundMessage,
    debounce_seconds: int,
) -> None:
    agora = datetime.now(UTC)

    contact = await get_or_create_contact(
        session, phone_e164=msg.from_phone, profile_name=msg.profile_name, now=agora
    )
    conversation = await get_or_create_conversation(
        session, contact_id=contact.id, channel_id=channel_id
    )
    await session.flush()

    message_id = await _inserir_mensagem_idempotente(
        session, tenant_id=tenant_id, conversation_id=conversation.id, msg=msg
    )
    if message_id is None:
        logger.info("mensagem_duplicada_ignorada", provider_message_id=msg.provider_message_id)
        return

    conversation.last_inbound_at = agora
    conversation.within_24h_window_until = agora + timedelta(hours=24)

    if _deve_pular_buffer(msg):
        await pool.enqueue_job("process_turn", str(tenant_id), str(conversation.id))
        return

    await enqueue_message(
        pool,
        conversation_id=str(conversation.id),
        tenant_id=str(tenant_id),
        message={"message_id": str(message_id), "text": msg.text, "content_type": msg.content_type},
        debounce_seconds=debounce_seconds,
    )


async def process_webhook_event(ctx: dict[str, Any], tenant_id: str, webhook_event_id: str) -> None:
    tenant_uuid = uuid.UUID(tenant_id)
    pool: ArqRedis = ctx["redis"]
    settings = get_settings()

    token = TenantContext.set(tenant_uuid)
    try:
        async with tenant_session(tenant_uuid) as session:
            evento = await session.get(WebhookEvent, uuid.UUID(webhook_event_id))
            if evento is None or not evento.signature_valid:
                return

            channel = await ChannelRepository(session).get_by_provider(evento.provider)
            if channel is None:
                logger.warning(
                    "process_webhook_event_canal_sumiu",
                    tenant_id=tenant_id,
                    webhook_event_id=webhook_event_id,
                )
                return

            adapter = build_adapter(channel)
            mensagens = await adapter.parse_inbound(evento.payload)

            for msg in mensagens:
                await _processar_mensagem(
                    session,
                    pool,
                    tenant_id=tenant_uuid,
                    channel_id=channel.id,
                    msg=msg,
                    debounce_seconds=settings.default_debounce_seconds,
                )

            evento.processed_at = datetime.now(UTC)
    finally:
        TenantContext.reset(token)


async def process_turn(ctx: dict[str, Any], tenant_id: str, conversation_id: str) -> None:
    """Stub até a Fase 3 (tarefa 3.4) — adquire o lock da conversa, drena o
    buffer e loga, sem chamar LLM. Sem o lock, dois turnos concorrentes
    processariam o mesmo buffer ao mesmo tempo (`docs/04` §2)."""
    pool: ArqRedis = ctx["redis"]
    settings = get_settings()

    async with conversation_lock(
        pool, conversation_id, ttl=settings.conversation_lock_ttl_seconds
    ) as adquirido:
        if not adquirido:
            logger.info(
                "process_turn_lock_ocupado", tenant_id=tenant_id, conversation_id=conversation_id
            )
            await pool.enqueue_job("process_turn", tenant_id, conversation_id, _defer_by=5)
            return

        mensagens = await drain_buffer(pool, conversation_id=conversation_id)
        logger.info(
            "process_turn_stub",
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            quantidade_mensagens=len(mensagens),
        )
