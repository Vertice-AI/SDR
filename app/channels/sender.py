"""Envio de mensagens — centraliza opt-out, status do canal, janela de 24h,
rate limit, split, typing/delay, persistência e retry
(`docs/06-integracao-whatsapp.md` §4).

Toda mensagem enviada é persistida **antes** de considerar sucesso — se o
envio falhar depois de persistida, a linha fica com `provider_status =
"failed"` e `error_detail`, nunca é descartada (`docs/06` §4).
"""

import asyncio
from datetime import UTC, datetime

import structlog
from arq import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.channels.base import ChannelAdapter, SentMessage
from app.channels.formatting import split_message, typing_delay_ms
from app.core.errors import ExternalServiceError
from app.core.rate_limit import allow_send
from app.models import Channel, Contact, Conversation, Message
from app.repositories.message import MessageRepository

logger = structlog.get_logger()


class OptedOutError(Exception):
    """Lead pediu para sair — nunca mais enviar (`CLAUDE.md` §4.8)."""


class ChannelUnavailableError(Exception):
    """Canal não está `active` — mensagem não sai agora."""


class OutsideWindowError(Exception):
    """Fora da janela de 24h (só Meta) e nenhum template foi passado."""


def _erro_retryable(exc: BaseException) -> bool:
    return isinstance(exc, ExternalServiceError) and exc.retryable


@retry(
    retry=retry_if_exception(_erro_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, max=8),
    reraise=True,
)
async def _enviar_com_retry(adapter: ChannelAdapter, to: str, text: str) -> SentMessage:
    return await adapter.send_text(to, text)


async def send_message(
    session: AsyncSession,
    pool: ArqRedis,
    adapter: ChannelAdapter,
    *,
    channel: Channel,
    conversation: Conversation,
    contact: Contact,
    text: str,
) -> list[Message]:
    if contact.opted_out_at is not None:
        raise OptedOutError(f"Contato {contact.id} optou por sair — envio bloqueado.")

    if channel.status != "active":
        raise ChannelUnavailableError(f"Canal {channel.id} não está ativo ({channel.status}).")

    if channel.provider == "meta_cloud":
        janela = conversation.within_24h_window_until
        if janela is not None and datetime.now(UTC) > janela:
            raise OutsideWindowError(
                f"Conversa {conversation.id} fora da janela de 24h — use send_template."
            )

    partes = split_message(text)
    mensagens_enviadas: list[Message] = []

    for parte in partes:
        await allow_send(pool, channel_id=str(channel.id))

        if adapter.supports("typing"):
            await adapter.send_typing(contact.phone_e164, True)

        await asyncio.sleep(typing_delay_ms(parte) / 1000)

        mensagem = Message(
            conversation_id=conversation.id,
            direction="outbound",
            sender_type="agent",
            content_type="text",
            content=parte,
            provider_status="queued",
        )
        await MessageRepository(session).add(mensagem)
        await session.flush()

        try:
            enviado = await _enviar_com_retry(adapter, contact.phone_e164, parte)
        except ExternalServiceError as exc:
            mensagem.provider_status = "failed"
            mensagem.error_detail = str(exc)
            logger.warning(
                "envio_falhou", conversation_id=str(conversation.id), retryable=exc.retryable
            )
        else:
            mensagem.provider_status = "sent"
            mensagem.provider_message_id = enviado.provider_message_id

        if adapter.supports("typing"):
            await adapter.send_typing(contact.phone_e164, False)

        await asyncio.sleep(0.4)
        mensagens_enviadas.append(mensagem)

    conversation.last_outbound_at = datetime.now(UTC)
    return mensagens_enviadas
