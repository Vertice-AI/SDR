"""`process_webhook_event` + buffer de debounce ponta a ponta — resolve
contato/conversa, persiste mensagem com idempotência e agenda `process_turn`
(`docs/04` §1, roadmap 2.5). Chama o worker diretamente (sem subir um
processo ARQ) — o que importa aqui é a lógica, não o transporte do job."""

import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.core.db import tenant_session
from app.core.queue import get_arq_pool
from app.models import Channel, Contact, Conversation, Message, Tenant, WebhookEvent
from app.workers.inbound import process_turn, process_webhook_event

_WEBHOOK_TOKEN = "webhook-secret-inbound"


@pytest.fixture
async def tenant_com_canal_evolution() -> AsyncGenerator[tuple[uuid.UUID, uuid.UUID], None]:
    settings = get_settings()
    admin_engine = create_async_engine(settings.database_admin_url or settings.database_url)
    admin_session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)

    tenant_id = uuid.uuid4()
    slug = f"inbound-{tenant_id.hex[:8]}"

    async with admin_session_factory() as session:
        session.add(Tenant(id=tenant_id, slug=slug, name="Tenant Inbound Teste"))
        await session.commit()

        channel = Channel(
            tenant_id=tenant_id,
            provider="evolution",
            phone_number=f"+55119{tenant_id.int % 100000000:08d}",
            status="active",
            credentials_encrypted=json.dumps(
                {
                    "base_url": "http://localhost:8080",
                    "api_key": "instance-key",
                    "instance_name": "tenant-demo",
                }
            ),
            webhook_verify_token_encrypted=_WEBHOOK_TOKEN,
            capabilities={"typing": True},
        )
        session.add(channel)
        await session.commit()
        channel_id = channel.id

    try:
        yield tenant_id, channel_id
    finally:
        async with admin_session_factory() as session:
            await session.execute(delete(Message).where(Message.tenant_id == tenant_id))
            await session.execute(delete(Conversation).where(Conversation.tenant_id == tenant_id))
            await session.execute(delete(Contact).where(Contact.tenant_id == tenant_id))
            await session.execute(delete(WebhookEvent).where(WebhookEvent.tenant_id == tenant_id))
            await session.execute(delete(Channel).where(Channel.tenant_id == tenant_id))
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await session.commit()
        await admin_engine.dispose()


def _payload_evolution(*, remote_jid: str, provider_message_id: str, texto: str) -> dict[str, Any]:
    return {
        "event": "messages.upsert",
        "instance": "tenant-demo",
        "data": {
            "key": {"remoteJid": remote_jid, "fromMe": False, "id": provider_message_id},
            "pushName": "Maria",
            "message": {"conversation": texto},
            "messageTimestamp": 1735689600,
        },
    }


async def _criar_webhook_event(
    tenant_id: uuid.UUID, payload: dict[str, Any], *, signature_valid: bool = True
) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        evento = WebhookEvent(
            tenant_id=tenant_id,
            provider="evolution",
            event_type="messages.upsert",
            payload=payload,
            signature_valid=signature_valid,
        )
        session.add(evento)
        await session.flush()
        return evento.id


async def test_processa_mensagem_cria_contato_conversa_e_bufferiza(
    tenant_com_canal_evolution: tuple[uuid.UUID, uuid.UUID],
) -> None:
    tenant_id, _channel_id = tenant_com_canal_evolution
    payload = _payload_evolution(
        remote_jid="5511988887777@s.whatsapp.net",
        provider_message_id="WA_MSG_1",
        texto="oi, vi o anúncio",
    )
    evento_id = await _criar_webhook_event(tenant_id, payload)
    pool = await get_arq_pool()

    await process_webhook_event({"redis": pool}, str(tenant_id), str(evento_id))

    async with tenant_session(tenant_id) as session:
        contact = (
            await session.execute(select(Contact).where(Contact.phone_e164 == "+5511988887777"))
        ).scalar_one()
        conversation = (
            await session.execute(select(Conversation).where(Conversation.contact_id == contact.id))
        ).scalar_one()
        mensagens = (
            (
                await session.execute(
                    select(Message).where(Message.conversation_id == conversation.id)
                )
            )
            .scalars()
            .all()
        )

    assert conversation.status == "active"
    assert conversation.state == "novo"
    assert conversation.last_inbound_at is not None
    assert len(mensagens) == 1
    assert mensagens[0].content == "oi, vi o anúncio"
    assert mensagens[0].provider_message_id == "WA_MSG_1"

    bufferizadas = await pool.lrange(f"buf:{conversation.id}", 0, -1)
    assert len(bufferizadas) == 1
    timer_existe = await pool.exists(f"buftimer:{conversation.id}")
    assert timer_existe == 1


async def test_reenvio_do_mesmo_provider_message_id_nao_duplica(
    tenant_com_canal_evolution: tuple[uuid.UUID, uuid.UUID],
) -> None:
    tenant_id, _channel_id = tenant_com_canal_evolution
    payload = _payload_evolution(
        remote_jid="5511988887778@s.whatsapp.net",
        provider_message_id="WA_MSG_DUPLICADA",
        texto="quanto custa?",
    )
    pool = await get_arq_pool()

    evento_1 = await _criar_webhook_event(tenant_id, payload)
    await process_webhook_event({"redis": pool}, str(tenant_id), str(evento_1))

    # WhatsApp reenvia o mesmo evento — outro webhook_event, mesmo provider_message_id
    evento_2 = await _criar_webhook_event(tenant_id, payload)
    await process_webhook_event({"redis": pool}, str(tenant_id), str(evento_2))

    async with tenant_session(tenant_id) as session:
        mensagens = (
            (
                await session.execute(
                    select(Message).where(Message.provider_message_id == "WA_MSG_DUPLICADA")
                )
            )
            .scalars()
            .all()
        )

    assert len(mensagens) == 1


async def test_evento_com_assinatura_invalida_e_ignorado(
    tenant_com_canal_evolution: tuple[uuid.UUID, uuid.UUID],
) -> None:
    tenant_id, _channel_id = tenant_com_canal_evolution
    payload = _payload_evolution(
        remote_jid="5511988887779@s.whatsapp.net",
        provider_message_id="WA_MSG_INVALIDO",
        texto="oi",
    )
    evento_id = await _criar_webhook_event(tenant_id, payload, signature_valid=False)
    pool = await get_arq_pool()

    await process_webhook_event({"redis": pool}, str(tenant_id), str(evento_id))

    async with tenant_session(tenant_id) as session:
        contact = (
            await session.execute(select(Contact).where(Contact.phone_e164 == "+5511988887779"))
        ).scalar_one_or_none()

    assert contact is None


async def test_comando_de_saida_pula_o_buffer(
    tenant_com_canal_evolution: tuple[uuid.UUID, uuid.UUID],
) -> None:
    tenant_id, _channel_id = tenant_com_canal_evolution
    payload = _payload_evolution(
        remote_jid="5511988887780@s.whatsapp.net",
        provider_message_id="WA_MSG_OPTOUT",
        texto="PARAR",
    )
    evento_id = await _criar_webhook_event(tenant_id, payload)
    pool = await get_arq_pool()

    await process_webhook_event({"redis": pool}, str(tenant_id), str(evento_id))

    async with tenant_session(tenant_id) as session:
        contact = (
            await session.execute(select(Contact).where(Contact.phone_e164 == "+5511988887780"))
        ).scalar_one()
        conversation = (
            await session.execute(select(Conversation).where(Conversation.contact_id == contact.id))
        ).scalar_one()

    # Não passou pelo buffer: nada empilhado em buf:{conv}
    bufferizadas = await pool.lrange(f"buf:{conversation.id}", 0, -1)
    assert bufferizadas == []


async def test_process_turn_drena_o_buffer(
    tenant_com_canal_evolution: tuple[uuid.UUID, uuid.UUID],
) -> None:
    tenant_id, _channel_id = tenant_com_canal_evolution
    payload = _payload_evolution(
        remote_jid="5511988887781@s.whatsapp.net",
        provider_message_id="WA_MSG_DRAIN",
        texto="mensagem pra testar drain",
    )
    evento_id = await _criar_webhook_event(tenant_id, payload)
    pool = await get_arq_pool()
    await process_webhook_event({"redis": pool}, str(tenant_id), str(evento_id))

    async with tenant_session(tenant_id) as session:
        contact = (
            await session.execute(select(Contact).where(Contact.phone_e164 == "+5511988887781"))
        ).scalar_one()
        conversation = (
            await session.execute(select(Conversation).where(Conversation.contact_id == contact.id))
        ).scalar_one()

    antes = await pool.lrange(f"buf:{conversation.id}", 0, -1)
    assert len(antes) == 1

    await process_turn({"redis": pool}, str(tenant_id), str(conversation.id))

    depois = await pool.lrange(f"buf:{conversation.id}", 0, -1)
    assert depois == []
