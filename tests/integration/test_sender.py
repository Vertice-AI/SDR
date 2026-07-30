"""`send_message` ponta a ponta contra o schema real — opt-out, canal
inativo, janela de 24h, retry e persistência (`docs/06-integracao-whatsapp.md`
§4, roadmap 2.6). Adapter fake no lugar de um provedor de verdade."""

import json
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.channels.base import InboundMessage, SentMessage
from app.channels.sender import (
    ChannelUnavailableError,
    OptedOutError,
    OutsideWindowError,
    send_message,
)
from app.config import get_settings
from app.core.db import tenant_session
from app.core.errors import ExternalServiceError
from app.core.queue import get_arq_pool
from app.core.tenancy import TenantContext
from app.models import Channel, Contact, Conversation, Message, Tenant


class _FakeAdapter:
    provider = "evolution"

    def __init__(
        self, *, falhas_antes_de_sucesso: int = 0, capacidades: dict[str, bool] | None = None
    ) -> None:
        self.textos_enviados: list[str] = []
        self.typing_chamadas: list[bool] = []
        self._falhas_restantes = falhas_antes_de_sucesso
        self._capacidades = capacidades or {"typing": True}

    async def verify_webhook(self, params: Any, headers: Any, body: bytes) -> bool:
        return True

    async def parse_inbound(self, payload: dict[str, Any]) -> list[InboundMessage]:
        return []

    async def send_text(self, to: str, text: str) -> SentMessage:
        if self._falhas_restantes > 0:
            self._falhas_restantes -= 1
            raise ExternalServiceError("falha temporária simulada", retryable=True)
        self.textos_enviados.append(text)
        return SentMessage(
            provider_message_id=f"OUT{len(self.textos_enviados)}",
            to_phone=to,
            timestamp=datetime.now(UTC),
        )

    async def send_typing(self, to: str, on: bool) -> None:
        self.typing_chamadas.append(on)

    async def send_template(self, to: str, name: str, params: list[str]) -> SentMessage:
        raise NotImplementedError

    async def send_buttons(self, to: str, text: str, buttons: list[str]) -> SentMessage:
        raise NotImplementedError

    async def download_media(self, media_id: str) -> bytes:
        raise NotImplementedError

    async def mark_read(self, provider_message_id: str) -> None:
        return None

    def supports(self, capability: str) -> bool:
        return bool(self._capacidades.get(capability, False))


@pytest.fixture
async def cenario() -> AsyncGenerator[tuple[uuid.UUID, Channel, Conversation, Contact], None]:
    settings = get_settings()
    admin_engine = create_async_engine(settings.database_admin_url or settings.database_url)
    admin_session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)

    tenant_id = uuid.uuid4()
    slug = f"sender-{tenant_id.hex[:8]}"

    async with admin_session_factory() as session:
        session.add(Tenant(id=tenant_id, slug=slug, name="Tenant Sender Teste"))
        await session.commit()

        channel = Channel(
            tenant_id=tenant_id,
            provider="evolution",
            phone_number=f"+55119{tenant_id.int % 100000000:08d}",
            status="active",
            credentials_encrypted=json.dumps(
                {"base_url": "http://localhost:8080", "api_key": "x", "instance_name": "x"}
            ),
            capabilities={"typing": True},
        )
        session.add(channel)

        contact = Contact(
            tenant_id=tenant_id,
            phone_e164="+5511988880000",
            phone_hash="hash-sender-teste",
            source="desconhecido",
        )
        session.add(contact)
        await session.commit()

        conversation = Conversation(
            tenant_id=tenant_id,
            contact_id=contact.id,
            channel_id=channel.id,
            status="active",
            state="novo",
        )
        session.add(conversation)
        await session.commit()

    try:
        yield tenant_id, channel, conversation, contact
    finally:
        async with admin_session_factory() as session:
            await session.execute(delete(Message).where(Message.tenant_id == tenant_id))
            await session.execute(delete(Conversation).where(Conversation.tenant_id == tenant_id))
            await session.execute(delete(Contact).where(Contact.tenant_id == tenant_id))
            await session.execute(delete(Channel).where(Channel.tenant_id == tenant_id))
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await session.commit()
        await admin_engine.dispose()


async def test_envia_mensagem_curta_persiste_e_chama_typing(
    cenario: tuple[uuid.UUID, Channel, Conversation, Contact],
) -> None:
    tenant_id, channel, conversation, contact = cenario
    adapter = _FakeAdapter()
    pool = await get_arq_pool()

    token = TenantContext.set(tenant_id)
    try:
        async with tenant_session(tenant_id) as session:
            enviadas = await send_message(
                session,
                pool,
                adapter,
                channel=channel,
                conversation=conversation,
                contact=contact,
                text="oi, tudo bem?",
            )
    finally:
        TenantContext.reset(token)

    assert len(enviadas) == 1
    assert enviadas[0].provider_status == "sent"
    assert enviadas[0].provider_message_id == "OUT1"
    assert adapter.textos_enviados == ["oi, tudo bem?"]
    assert adapter.typing_chamadas == [True, False]

    async with tenant_session(tenant_id) as session:
        mensagens = (
            (
                await session.execute(
                    select(Message).where(Message.conversation_id == conversation.id)
                )
            )
            .scalars()
            .all()
        )
    assert len(mensagens) == 1
    assert mensagens[0].direction == "outbound"
    assert mensagens[0].sender_type == "agent"


async def test_bloqueia_envio_para_contato_optado_por_sair(
    cenario: tuple[uuid.UUID, Channel, Conversation, Contact],
) -> None:
    tenant_id, channel, conversation, contact = cenario
    contact.opted_out_at = datetime.now(UTC)
    adapter = _FakeAdapter()
    pool = await get_arq_pool()

    token = TenantContext.set(tenant_id)
    try:
        async with tenant_session(tenant_id) as session:
            session.add(contact)
            with pytest.raises(OptedOutError):
                await send_message(
                    session,
                    pool,
                    adapter,
                    channel=channel,
                    conversation=conversation,
                    contact=contact,
                    text="oi",
                )
    finally:
        TenantContext.reset(token)

    assert adapter.textos_enviados == []


async def test_bloqueia_envio_com_canal_inativo(
    cenario: tuple[uuid.UUID, Channel, Conversation, Contact],
) -> None:
    tenant_id, channel, conversation, contact = cenario
    channel.status = "disconnected"
    adapter = _FakeAdapter()
    pool = await get_arq_pool()

    token = TenantContext.set(tenant_id)
    try:
        async with tenant_session(tenant_id) as session:
            with pytest.raises(ChannelUnavailableError):
                await send_message(
                    session,
                    pool,
                    adapter,
                    channel=channel,
                    conversation=conversation,
                    contact=contact,
                    text="oi",
                )
    finally:
        TenantContext.reset(token)

    assert adapter.textos_enviados == []


async def test_bloqueia_envio_fora_da_janela_de_24h_na_meta(
    cenario: tuple[uuid.UUID, Channel, Conversation, Contact],
) -> None:
    tenant_id, channel, conversation, contact = cenario
    channel.provider = "meta_cloud"
    conversation.within_24h_window_until = datetime.now(UTC) - timedelta(hours=1)
    adapter = _FakeAdapter()
    adapter.provider = "meta_cloud"
    pool = await get_arq_pool()

    token = TenantContext.set(tenant_id)
    try:
        async with tenant_session(tenant_id) as session:
            with pytest.raises(OutsideWindowError):
                await send_message(
                    session,
                    pool,
                    adapter,
                    channel=channel,
                    conversation=conversation,
                    contact=contact,
                    text="oi",
                )
    finally:
        TenantContext.reset(token)


async def test_retry_ate_suceder_e_persiste_como_enviada(
    cenario: tuple[uuid.UUID, Channel, Conversation, Contact],
) -> None:
    tenant_id, channel, conversation, contact = cenario
    adapter = _FakeAdapter(falhas_antes_de_sucesso=2)
    pool = await get_arq_pool()

    token = TenantContext.set(tenant_id)
    try:
        async with tenant_session(tenant_id) as session:
            enviadas = await send_message(
                session,
                pool,
                adapter,
                channel=channel,
                conversation=conversation,
                contact=contact,
                text="mensagem com retry",
            )
    finally:
        TenantContext.reset(token)

    assert enviadas[0].provider_status == "sent"
    assert adapter.textos_enviados == ["mensagem com retry"]


async def test_falha_definitiva_grava_mensagem_como_failed(
    cenario: tuple[uuid.UUID, Channel, Conversation, Contact],
) -> None:
    tenant_id, channel, conversation, contact = cenario

    class _AdapterSempreFalha(_FakeAdapter):
        async def send_text(self, to: str, text: str) -> SentMessage:
            raise ExternalServiceError("erro 400 definitivo", retryable=False)

    adapter = _AdapterSempreFalha()
    pool = await get_arq_pool()

    token = TenantContext.set(tenant_id)
    try:
        async with tenant_session(tenant_id) as session:
            enviadas = await send_message(
                session,
                pool,
                adapter,
                channel=channel,
                conversation=conversation,
                contact=contact,
                text="essa vai falhar",
            )
    finally:
        TenantContext.reset(token)

    assert enviadas[0].provider_status == "failed"
    assert enviadas[0].error_detail == "erro 400 definitivo"
