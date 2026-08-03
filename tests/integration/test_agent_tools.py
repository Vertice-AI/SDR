"""Ferramentas do agente (`app/agent/tools/`, `docs/04-motor-de-conversa.md`
§5, roadmap 3.5) contra um Postgres de verdade — cada uma grava em tabela
diferente (contacts, qualifications, handoffs, conversations) e a RLS
precisa deixar."""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent.runtime import TurnContext
from app.agent.state import ConversationState
from app.agent.tools import (
    desqualificar,
    encerrar_conversa,
    escalar_para_humano,
    registrar_dados_lead,
    registrar_qualificacao,
)
from app.agent.tools.base import ToolDeps
from app.config import get_settings
from app.core.db import tenant_session
from app.core.tenancy import TenantContext
from app.models import Channel, Contact, Conversation, Handoff, Qualification, Tenant, TenantConfig
from app.repositories.contact import ContactRepository
from app.repositories.conversation import ConversationRepository

_CAMPOS_QUALIFICACAO = [
    {"key": "dor_principal", "required": True, "weight": 30, "scoring": {"has_value": 30}},
    {
        "key": "faturamento_mensal",
        "required": True,
        "weight": 30,
        "scoring": {"ate_50k": 0, "50k_200k": 15, "200k_1m": 30, "acima_1m": 30},
    },
]

_REGRAS_DESQUALIFICACAO = [
    {
        "field": "faturamento_mensal",
        "operator": "in",
        "value": ["ate_50k"],
        "reason": "abaixo do porte mínimo",
        "response": "Ainda não faz sentido para o momento da sua empresa — vou te mandar um material.",
    }
]


@pytest.fixture
async def cenario() -> AsyncGenerator[tuple[uuid.UUID, uuid.UUID, uuid.UUID, TenantConfig], None]:
    settings = get_settings()
    admin_engine = create_async_engine(settings.database_admin_url or settings.database_url)
    admin_session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)

    tenant_id = uuid.uuid4()
    slug = f"agent-tools-{tenant_id.hex[:8]}"

    async with admin_session_factory() as session:
        session.add(Tenant(id=tenant_id, slug=slug, name="Tenant Ferramentas Teste"))
        await session.commit()

        contact = Contact(
            tenant_id=tenant_id,
            phone_e164=f"+55119{tenant_id.int % 100000000:08d}",
            phone_hash="hash-teste",
            source="desconhecido",
        )
        channel = Channel(
            tenant_id=tenant_id,
            provider="evolution",
            phone_number=f"+55119{(tenant_id.int + 1) % 100000000:08d}",
            status="active",
        )
        session.add_all([contact, channel])
        await session.commit()

        conversation = Conversation(
            tenant_id=tenant_id,
            contact_id=contact.id,
            channel_id=channel.id,
            status="active",
            state="qualificando",
        )
        tenant_config = TenantConfig(
            tenant_id=tenant_id,
            version=1,
            agent_name="Ana",
            company_description="Agência de tráfego pago",
            offer_description="Gestão de tráfego para clínicas",
            icp_description="Clínicas com faturamento acima de 50k/mês",
            qualification_fields=_CAMPOS_QUALIFICACAO,
            disqualification_rules=_REGRAS_DESQUALIFICACAO,
        )
        session.add_all([conversation, tenant_config])
        await session.commit()

        contact_id, conversation_id = contact.id, conversation.id

    try:
        yield tenant_id, contact_id, conversation_id, tenant_config
    finally:
        async with admin_session_factory() as session:
            await session.execute(delete(Handoff).where(Handoff.tenant_id == tenant_id))
            await session.execute(delete(Qualification).where(Qualification.tenant_id == tenant_id))
            await session.execute(delete(Conversation).where(Conversation.tenant_id == tenant_id))
            await session.execute(delete(TenantConfig).where(TenantConfig.tenant_id == tenant_id))
            await session.execute(delete(Contact).where(Contact.tenant_id == tenant_id))
            await session.execute(delete(Channel).where(Channel.tenant_id == tenant_id))
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await session.commit()
        await admin_engine.dispose()


def _ctx(tenant_id: uuid.UUID, conversation_id: uuid.UUID) -> TurnContext:
    return TurnContext(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        turn_id=uuid.uuid4(),
        state=ConversationState.QUALIFICANDO,
        model="claude-sonnet-5",
        system="prompt de sistema",
        messages=[],
    )


async def test_registrar_dados_lead_atualiza_contact(
    cenario: tuple[uuid.UUID, uuid.UUID, uuid.UUID, TenantConfig],
) -> None:
    tenant_id, contact_id, conversation_id, tenant_config = cenario
    token = TenantContext.set(tenant_id)
    try:
        async with tenant_session(tenant_id) as session:
            deps = ToolDeps(session=session, contact_id=contact_id, tenant_config=tenant_config)
            resultado = await registrar_dados_lead.execute(
                {"nome": "Joana", "empresa": "Clínica Vida"},
                ctx=_ctx(tenant_id, conversation_id),
                deps=deps,
            )
        assert not resultado.is_error
        assert "nome" in resultado.content and "empresa" in resultado.content

        async with tenant_session(tenant_id) as session:
            contato = await ContactRepository(session).get(contact_id)
            assert contato is not None
            assert contato.name == "Joana"
            assert contato.company == "Clínica Vida"
    finally:
        TenantContext.reset(token)


async def test_registrar_dados_lead_sem_campos_retorna_erro(
    cenario: tuple[uuid.UUID, uuid.UUID, uuid.UUID, TenantConfig],
) -> None:
    tenant_id, contact_id, conversation_id, tenant_config = cenario
    token = TenantContext.set(tenant_id)
    try:
        async with tenant_session(tenant_id) as session:
            deps = ToolDeps(session=session, contact_id=contact_id, tenant_config=tenant_config)
            resultado = await registrar_dados_lead.execute(
                {}, ctx=_ctx(tenant_id, conversation_id), deps=deps
            )
        assert resultado.is_error
    finally:
        TenantContext.reset(token)


async def test_registrar_qualificacao_atualiza_score_e_sinaliza_ctx(
    cenario: tuple[uuid.UUID, uuid.UUID, uuid.UUID, TenantConfig],
) -> None:
    tenant_id, contact_id, conversation_id, tenant_config = cenario
    token = TenantContext.set(tenant_id)
    try:
        ctx = _ctx(tenant_id, conversation_id)
        async with tenant_session(tenant_id) as session:
            deps = ToolDeps(session=session, contact_id=contact_id, tenant_config=tenant_config)
            resultado = await registrar_qualificacao.execute(
                {"campo": "dor_principal", "valor": "precisa de mais leads", "confianca": 0.9},
                ctx=ctx,
                deps=deps,
            )
        assert not resultado.is_error
        assert ctx.signals.qualification_score == 30
        assert ctx.signals.required_fields_filled is False

        async with tenant_session(tenant_id) as session:
            result = await session.execute(
                select(Qualification).where(Qualification.conversation_id == conversation_id)
            )
            qualification = result.scalar_one()
            assert qualification.score == 30
            resposta_dor = qualification.answers["dor_principal"]
            assert isinstance(resposta_dor, dict)
            assert resposta_dor["valor"] == "precisa de mais leads"
    finally:
        TenantContext.reset(token)


async def test_registrar_qualificacao_todos_campos_marca_required_fields_filled(
    cenario: tuple[uuid.UUID, uuid.UUID, uuid.UUID, TenantConfig],
) -> None:
    tenant_id, contact_id, conversation_id, tenant_config = cenario
    token = TenantContext.set(tenant_id)
    try:
        ctx = _ctx(tenant_id, conversation_id)
        async with tenant_session(tenant_id) as session:
            deps = ToolDeps(session=session, contact_id=contact_id, tenant_config=tenant_config)
            await registrar_qualificacao.execute(
                {"campo": "dor_principal", "valor": "precisa de mais leads"}, ctx=ctx, deps=deps
            )
        async with tenant_session(tenant_id) as session:
            deps = ToolDeps(session=session, contact_id=contact_id, tenant_config=tenant_config)
            resultado = await registrar_qualificacao.execute(
                {"campo": "faturamento_mensal", "valor": "200k_1m"}, ctx=ctx, deps=deps
            )
        assert ctx.signals.qualification_score == 60
        assert ctx.signals.required_fields_filled is True
        assert "60" in resultado.content
    finally:
        TenantContext.reset(token)


async def test_registrar_qualificacao_campo_desconhecido_retorna_erro(
    cenario: tuple[uuid.UUID, uuid.UUID, uuid.UUID, TenantConfig],
) -> None:
    tenant_id, contact_id, conversation_id, tenant_config = cenario
    token = TenantContext.set(tenant_id)
    try:
        async with tenant_session(tenant_id) as session:
            deps = ToolDeps(session=session, contact_id=contact_id, tenant_config=tenant_config)
            resultado = await registrar_qualificacao.execute(
                {"campo": "campo_que_nao_existe", "valor": "x"},
                ctx=_ctx(tenant_id, conversation_id),
                deps=deps,
            )
        assert resultado.is_error
        assert "campo_que_nao_existe" in resultado.content
    finally:
        TenantContext.reset(token)


async def test_escalar_para_humano_cria_handoff_e_muda_status(
    cenario: tuple[uuid.UUID, uuid.UUID, uuid.UUID, TenantConfig],
) -> None:
    tenant_id, contact_id, conversation_id, tenant_config = cenario
    token = TenantContext.set(tenant_id)
    try:
        async with tenant_session(tenant_id) as session:
            deps = ToolDeps(session=session, contact_id=contact_id, tenant_config=tenant_config)
            resultado = await escalar_para_humano.execute(
                {"motivo": "lead_pediu", "resumo": "Quer falar com um vendedor"},
                ctx=_ctx(tenant_id, conversation_id),
                deps=deps,
            )
        assert not resultado.is_error
        assert resultado.content == escalar_para_humano.DEFAULT_TRANSITION_MESSAGE

        async with tenant_session(tenant_id) as session:
            handoff = (
                await session.execute(
                    select(Handoff).where(Handoff.conversation_id == conversation_id)
                )
            ).scalar_one()
            assert handoff.reason == "lead_pediu"
            assert handoff.notified_channels["summary"] == "Quer falar com um vendedor"

            conversa = await ConversationRepository(session).get(conversation_id)
            assert conversa is not None
            assert conversa.status == "human_handoff"
    finally:
        TenantContext.reset(token)


async def test_desqualificar_usa_resposta_da_regra_configurada(
    cenario: tuple[uuid.UUID, uuid.UUID, uuid.UUID, TenantConfig],
) -> None:
    tenant_id, contact_id, conversation_id, tenant_config = cenario
    token = TenantContext.set(tenant_id)
    try:
        async with tenant_session(tenant_id) as session:
            deps = ToolDeps(session=session, contact_id=contact_id, tenant_config=tenant_config)
            resultado = await desqualificar.execute(
                {"motivo": "abaixo do porte mínimo"},
                ctx=_ctx(tenant_id, conversation_id),
                deps=deps,
            )
        assert not resultado.is_error
        assert resultado.content == _REGRAS_DESQUALIFICACAO[0]["response"]

        async with tenant_session(tenant_id) as session:
            qualification = (
                await session.execute(
                    select(Qualification).where(Qualification.conversation_id == conversation_id)
                )
            ).scalar_one()
            assert qualification.classification == "disqualified"
            assert qualification.disqualification_reason == "abaixo do porte mínimo"

            conversa = await ConversationRepository(session).get(conversation_id)
            assert conversa is not None
            assert conversa.status == "disqualified"
    finally:
        TenantContext.reset(token)


async def test_desqualificar_sem_regra_usa_mensagem_padrao(
    cenario: tuple[uuid.UUID, uuid.UUID, uuid.UUID, TenantConfig],
) -> None:
    tenant_id, contact_id, conversation_id, tenant_config = cenario
    token = TenantContext.set(tenant_id)
    try:
        async with tenant_session(tenant_id) as session:
            deps = ToolDeps(session=session, contact_id=contact_id, tenant_config=tenant_config)
            resultado = await desqualificar.execute(
                {"motivo": "concorrente disfarçado"},
                ctx=_ctx(tenant_id, conversation_id),
                deps=deps,
            )
        assert resultado.content == desqualificar.DEFAULT_MESSAGE
    finally:
        TenantContext.reset(token)


async def test_encerrar_conversa_fecha_conversa(
    cenario: tuple[uuid.UUID, uuid.UUID, uuid.UUID, TenantConfig],
) -> None:
    tenant_id, contact_id, conversation_id, tenant_config = cenario
    token = TenantContext.set(tenant_id)
    try:
        async with tenant_session(tenant_id) as session:
            deps = ToolDeps(session=session, contact_id=contact_id, tenant_config=tenant_config)
            resultado = await encerrar_conversa.execute(
                {"motivo": "só queria uma informação"},
                ctx=_ctx(tenant_id, conversation_id),
                deps=deps,
            )
        assert not resultado.is_error

        async with tenant_session(tenant_id) as session:
            conversa = await ConversationRepository(session).get(conversation_id)
            assert conversa is not None
            assert conversa.status == "closed"
            assert conversa.closed_reason == "só queria uma informação"
    finally:
        TenantContext.reset(token)
