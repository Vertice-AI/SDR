"""Loop de tool calling (`app/agent/runtime.py`, `docs/04-motor-de-conversa.md`
§4, roadmap 3.4) — sem rede, sem LLM real: `LLMProvider` e `ToolExecutor` são
dublês controlados pelo teste."""

import asyncio
import uuid
from typing import Any

import pytest

from app.agent.llm.base import LLMResponse, LLMUsage, TextBlock, ToolDefinition, ToolUseBlock
from app.agent.runtime import (
    MENSAGEM_FALHA_LLM,
    MENSAGEM_LOOP_EXCEDIDO,
    ToolExecutionResult,
    TurnContext,
    run_turn,
)
from app.agent.state import (
    AGENDAR_REUNIAO,
    BUSCAR_CONHECIMENTO,
    ESCALAR_PARA_HUMANO,
    REGISTRAR_QUALIFICACAO,
    ConversationState,
    TurnSignals,
    tools_for_state,
)
from app.core.errors import ExternalServiceError


def _resposta_texto(texto: str) -> LLMResponse:
    return LLMResponse(
        content=[TextBlock(text=texto)],
        stop_reason="end_turn",
        usage=LLMUsage(input_tokens=10, output_tokens=5),
        latency_ms=5,
    )


def _resposta_tool_use(name: str, tool_input: dict[str, Any] | None = None) -> LLMResponse:
    return LLMResponse(
        content=[ToolUseBlock(id=f"call-{name}", name=name, input=tool_input or {})],
        stop_reason="tool_use",
        usage=LLMUsage(input_tokens=10, output_tokens=5),
        latency_ms=5,
    )


class FakeLLM:
    def __init__(
        self,
        respostas: list[LLMResponse],
        *,
        erro: Exception | None = None,
        atraso_s: float = 0.0,
    ) -> None:
        self._respostas = list(respostas)
        self._erro = erro
        self._atraso_s = atraso_s
        self.chamadas: list[dict[str, Any]] = []

    async def complete(
        self,
        *,
        system: str,
        messages: list[Any],
        tools: list[ToolDefinition] | None = None,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.4,
    ) -> LLMResponse:
        self.chamadas.append({"tools": tools, "n_messages": len(messages)})
        if self._atraso_s:
            await asyncio.sleep(self._atraso_s)
        if self._erro is not None:
            raise self._erro
        if len(self._respostas) > 1:
            return self._respostas.pop(0)
        return self._respostas[0]

    async def count_tokens(self, **kwargs: Any) -> int:
        return 0


class FakeToolExecutor:
    def __init__(
        self,
        *,
        resultado: ToolExecutionResult | None = None,
        erro: Exception | None = None,
        atraso_s: float = 0.0,
        ao_executar: Any = None,
    ) -> None:
        self._resultado = resultado or ToolExecutionResult(content="ok")
        self._erro = erro
        self._atraso_s = atraso_s
        self._ao_executar = ao_executar
        self.chamadas: list[tuple[str, dict[str, Any]]] = []

    async def execute(
        self, *, name: str, tool_input: dict[str, Any], ctx: TurnContext
    ) -> ToolExecutionResult:
        self.chamadas.append((name, tool_input))
        if self._atraso_s:
            await asyncio.sleep(self._atraso_s)
        if self._erro is not None:
            raise self._erro
        if self._ao_executar is not None:
            self._ao_executar(ctx)
        return self._resultado


def _tool_def(name: str) -> ToolDefinition:
    return ToolDefinition(name=name, description=name, input_schema={"type": "object"})


_TODAS_AS_FERRAMENTAS = {
    nome: _tool_def(nome) for estado in ConversationState for nome in tools_for_state(estado)
}


def _ctx(state: ConversationState, *, signals: TurnSignals | None = None) -> TurnContext:
    return TurnContext(
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
        state=state,
        model="claude-sonnet-5",
        system="prompt de sistema",
        messages=[],
        signals=signals or TurnSignals(),
    )


async def test_resposta_direta_sem_ferramenta_permanece_no_estado() -> None:
    ctx = _ctx(ConversationState.QUALIFICANDO)
    llm = FakeLLM([_resposta_texto("Entendi, me conta mais sobre a operação de vocês.")])
    executor = FakeToolExecutor()

    resultado = await run_turn(
        ctx, llm=llm, tool_executor=executor, tool_definitions=_TODAS_AS_FERRAMENTAS
    )

    assert resultado.reply == "Entendi, me conta mais sobre a operação de vocês."
    assert resultado.new_state is ConversationState.QUALIFICANDO
    assert resultado.iterations == 1
    assert resultado.tools_called == ()
    assert not resultado.escalated
    assert resultado.error is None
    assert executor.chamadas == []


async def test_so_expoe_ferramentas_liberadas_pelo_estado() -> None:
    ctx = _ctx(ConversationState.ABERTURA)
    llm = FakeLLM([_resposta_texto("oi")])

    await run_turn(
        ctx, llm=llm, tool_executor=FakeToolExecutor(), tool_definitions=_TODAS_AS_FERRAMENTAS
    )

    nomes_expostos = {t.name for t in llm.chamadas[0]["tools"]}
    assert nomes_expostos == tools_for_state(ConversationState.ABERTURA)


async def test_ferramenta_chamada_avanca_estado_via_sinal() -> None:
    def _marca_qualificado(ctx: TurnContext) -> None:
        ctx.update_signals(qualification_score=80, required_fields_filled=True)

    ctx = _ctx(ConversationState.QUALIFICANDO)
    llm = FakeLLM(
        [
            _resposta_tool_use(REGISTRAR_QUALIFICACAO, {"campo": "dor", "valor": "x"}),
            _resposta_texto("Perfeito, vamos agendar uma conversa."),
        ]
    )
    executor = FakeToolExecutor(ao_executar=_marca_qualificado)

    resultado = await run_turn(
        ctx, llm=llm, tool_executor=executor, tool_definitions=_TODAS_AS_FERRAMENTAS
    )

    assert resultado.iterations == 2
    registro = resultado.tools_called[0]
    assert registro.name == REGISTRAR_QUALIFICACAO
    assert registro.is_error is False
    assert resultado.new_state is ConversationState.AGENDANDO
    assert not resultado.escalated


async def test_buscar_conhecimento_desvia_para_respondendo_duvidas() -> None:
    ctx = _ctx(ConversationState.QUALIFICANDO)
    llm = FakeLLM(
        [
            _resposta_tool_use(BUSCAR_CONHECIMENTO, {"pergunta": "qual o preço?"}),
            _resposta_texto("O plano custa..."),
        ]
    )
    executor = FakeToolExecutor(resultado=ToolExecutionResult(content="trecho da base"))

    resultado = await run_turn(
        ctx, llm=llm, tool_executor=executor, tool_definitions=_TODAS_AS_FERRAMENTAS
    )

    assert resultado.new_state is ConversationState.RESPONDENDO_DUVIDAS


async def test_ferramenta_fora_do_estado_e_bloqueada_sem_executar() -> None:
    ctx = _ctx(ConversationState.ABERTURA)
    llm = FakeLLM(
        [
            _resposta_tool_use(AGENDAR_REUNIAO, {"slot_id": "abc"}),
            _resposta_texto("Deixa eu confirmar mais alguns detalhes antes."),
        ]
    )
    executor = FakeToolExecutor()

    resultado = await run_turn(
        ctx, llm=llm, tool_executor=executor, tool_definitions=_TODAS_AS_FERRAMENTAS
    )

    assert executor.chamadas == []
    assert resultado.tools_called == ()
    assert len(resultado.guardrail_flags) == 1
    assert resultado.guardrail_flags[0]["tool"] == AGENDAR_REUNIAO
    assert resultado.new_state is ConversationState.ABERTURA


async def test_estouro_de_max_iterations_escala_e_avisa_o_lead() -> None:
    ctx = _ctx(ConversationState.ABERTURA)
    llm = FakeLLM([_resposta_tool_use(BUSCAR_CONHECIMENTO, {"pergunta": "oi"})])
    executor = FakeToolExecutor()

    resultado = await run_turn(
        ctx,
        llm=llm,
        tool_executor=executor,
        tool_definitions=_TODAS_AS_FERRAMENTAS,
        max_iterations=3,
    )

    assert resultado.iterations == 3
    assert resultado.error == "max_iterations_excedido"
    assert resultado.reply == MENSAGEM_LOOP_EXCEDIDO
    assert resultado.escalated
    assert resultado.new_state is ConversationState.HANDOFF_HUMANO


async def test_falha_definitiva_do_llm_escala_com_mensagem_neutra() -> None:
    ctx = _ctx(ConversationState.QUALIFICANDO)
    llm = FakeLLM([], erro=ExternalServiceError("Anthropic API: 503", retryable=False))

    resultado = await run_turn(
        ctx,
        llm=llm,
        tool_executor=FakeToolExecutor(),
        tool_definitions=_TODAS_AS_FERRAMENTAS,
    )

    assert resultado.reply == MENSAGEM_FALHA_LLM
    assert resultado.error is not None
    assert resultado.escalated
    assert resultado.new_state is ConversationState.HANDOFF_HUMANO


async def test_timeout_do_llm_escala_com_mensagem_neutra() -> None:
    ctx = _ctx(ConversationState.QUALIFICANDO)
    llm = FakeLLM([_resposta_texto("nunca chega")], atraso_s=0.2)

    resultado = await run_turn(
        ctx,
        llm=llm,
        tool_executor=FakeToolExecutor(),
        tool_definitions=_TODAS_AS_FERRAMENTAS,
        llm_timeout_seconds=0.01,
    )

    assert resultado.reply == MENSAGEM_FALHA_LLM
    assert resultado.escalated
    assert resultado.new_state is ConversationState.HANDOFF_HUMANO


async def test_timeout_de_ferramenta_nao_derruba_o_turno() -> None:
    ctx = _ctx(ConversationState.ABERTURA)
    llm = FakeLLM(
        [
            _resposta_tool_use(BUSCAR_CONHECIMENTO, {"pergunta": "oi"}),
            _resposta_texto("Só um instante..."),
        ]
    )
    executor = FakeToolExecutor(atraso_s=0.2)

    resultado = await run_turn(
        ctx,
        llm=llm,
        tool_executor=executor,
        tool_definitions=_TODAS_AS_FERRAMENTAS,
        tool_timeout_seconds=0.01,
    )

    assert resultado.error is None
    assert resultado.tools_called[0].is_error is True
    assert not resultado.escalated


async def test_excecao_inesperada_da_ferramenta_vira_erro_tratavel() -> None:
    ctx = _ctx(ConversationState.ABERTURA)
    llm = FakeLLM(
        [
            _resposta_tool_use(BUSCAR_CONHECIMENTO, {"pergunta": "oi"}),
            _resposta_texto("segue o jogo"),
        ]
    )
    executor = FakeToolExecutor(erro=RuntimeError("boom"))

    resultado = await run_turn(
        ctx, llm=llm, tool_executor=executor, tool_definitions=_TODAS_AS_FERRAMENTAS
    )

    assert resultado.error is None
    assert resultado.tools_called[0].is_error is True
    assert resultado.reply == "segue o jogo"


async def test_escalar_para_humano_chamado_pelo_llm_muda_estado() -> None:
    ctx = _ctx(ConversationState.QUALIFICANDO)
    llm = FakeLLM(
        [
            _resposta_tool_use(ESCALAR_PARA_HUMANO, {"motivo": "pediu humano"}),
            _resposta_texto("Vou chamar alguém do time aqui para te ajudar."),
        ]
    )
    executor = FakeToolExecutor()

    resultado = await run_turn(
        ctx, llm=llm, tool_executor=executor, tool_definitions=_TODAS_AS_FERRAMENTAS
    )

    assert resultado.new_state is ConversationState.HANDOFF_HUMANO
    assert resultado.escalated


@pytest.mark.parametrize("estado", [ConversationState.QUALIFICANDO, ConversationState.AGENDANDO])
async def test_score_alto_sem_desvio_avanca_direto_para_agendando(
    estado: ConversationState,
) -> None:
    sinais = TurnSignals(qualification_score=90, required_fields_filled=True)
    ctx = _ctx(estado, signals=sinais)
    llm = FakeLLM([_resposta_texto("Vamos marcar uma conversa?")])

    resultado = await run_turn(
        ctx, llm=llm, tool_executor=FakeToolExecutor(), tool_definitions=_TODAS_AS_FERRAMENTAS
    )

    assert resultado.new_state is ConversationState.AGENDANDO
