"""`run_turn` (`app/agent/runtime.py`, roadmap 3.4) grava um `agent_runs` por
turno num Postgres de verdade — é a base do custo e da depuração do agente,
não vale a pena confiar só em teste unitário para isso."""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent.llm.base import LLMResponse, LLMUsage, TextBlock
from app.agent.runtime import ToolExecutionResult, TurnContext, run_turn
from app.agent.state import ConversationState
from app.config import get_settings
from app.core.db import tenant_session
from app.core.tenancy import TenantContext
from app.models import AgentRun, Channel, Contact, Conversation, Tenant
from app.repositories.agent_run import AgentRunRepository


class _FakeLLM:
    async def complete(self, **kwargs: object) -> LLMResponse:
        return LLMResponse(
            content=[TextBlock(text="Entendi, me conta mais sobre a operação de vocês.")],
            stop_reason="end_turn",
            usage=LLMUsage(input_tokens=42, output_tokens=17, cache_read_input_tokens=5),
            latency_ms=123,
        )

    async def count_tokens(self, **kwargs: object) -> int:
        return 0


class _FakeToolExecutor:
    async def execute(self, **kwargs: object) -> ToolExecutionResult:
        raise AssertionError("nenhuma ferramenta deveria ser chamada neste teste")


@pytest.fixture
async def conversa_de_teste() -> AsyncGenerator[tuple[uuid.UUID, uuid.UUID], None]:
    settings = get_settings()
    admin_engine = create_async_engine(settings.database_admin_url or settings.database_url)
    admin_session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)

    tenant_id = uuid.uuid4()
    slug = f"agent-run-{tenant_id.hex[:8]}"

    async with admin_session_factory() as session:
        session.add(Tenant(id=tenant_id, slug=slug, name="Tenant Agent Run Teste"))
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
        session.add(conversation)
        await session.commit()
        conversation_id = conversation.id

    try:
        yield tenant_id, conversation_id
    finally:
        async with admin_session_factory() as session:
            await session.execute(delete(AgentRun).where(AgentRun.tenant_id == tenant_id))
            await session.execute(delete(Conversation).where(Conversation.tenant_id == tenant_id))
            await session.execute(delete(Contact).where(Contact.tenant_id == tenant_id))
            await session.execute(delete(Channel).where(Channel.tenant_id == tenant_id))
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await session.commit()
        await admin_engine.dispose()


async def test_run_turn_registra_agent_run_com_custo_e_transicao_de_estado(
    conversa_de_teste: tuple[uuid.UUID, uuid.UUID],
) -> None:
    tenant_id, conversation_id = conversa_de_teste
    turn_id = uuid.uuid4()

    token = TenantContext.set(tenant_id)
    try:
        async with tenant_session(tenant_id) as session:
            ctx = TurnContext(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                turn_id=turn_id,
                state=ConversationState.QUALIFICANDO,
                model="claude-sonnet-5",
                system="prompt de sistema",
                messages=[],
            )
            resultado = await run_turn(
                ctx, llm=_FakeLLM(), tool_executor=_FakeToolExecutor(), tool_definitions={}
            )

            await AgentRunRepository(session).add(
                AgentRun(
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    model=ctx.model,
                    input_tokens=resultado.usage.input_tokens,
                    output_tokens=resultado.usage.output_tokens,
                    cached_tokens=resultado.usage.cache_read_input_tokens,
                    cost_cents=resultado.usage.cost_cents,
                    latency_ms=resultado.latency_ms,
                    iterations=resultado.iterations,
                    tools_called=[
                        {"name": r.name, "input": r.input, "is_error": r.is_error}
                        for r in resultado.tools_called
                    ],
                    state_before=str(ConversationState.QUALIFICANDO),
                    state_after=str(resultado.new_state),
                    guardrail_flags=list(resultado.guardrail_flags),
                    error=resultado.error,
                    trace_id=str(turn_id),
                )
            )
    finally:
        TenantContext.reset(token)

    async with tenant_session(tenant_id) as session:
        registro = (
            await session.execute(select(AgentRun).where(AgentRun.turn_id == turn_id))
        ).scalar_one()

    assert registro.tenant_id == tenant_id
    assert registro.conversation_id == conversation_id
    assert registro.input_tokens == 42
    assert registro.output_tokens == 17
    assert registro.cached_tokens == 5
    assert registro.iterations == 1
    assert registro.tools_called == []
    assert registro.state_before == "qualificando"
    assert registro.state_after == "qualificando"
    assert registro.error is None
