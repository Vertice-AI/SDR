"""Loop de tool calling do agente — `docs/04-motor-de-conversa.md` §4,
roadmap 3.4.

`run_turn` é o coração do produto: itera LLM ↔ ferramentas até obter uma
resposta de texto, respeitando o que o estado da conversa permite
(`app/agent/state.py`) e **nunca** deixando o lead sem resposta, mesmo
quando o LLM falha ou entra em loop. Ferramentas de verdade (tarefa 3.5) só
precisam implementar o `Protocol` `ToolExecutor` — este módulo não conhece
nenhuma delas por nome, exceto para inferir sinais de transição de estado a
partir do que foi chamado.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

import structlog

from app.agent.llm.base import (
    ContentBlock,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    LLMUsage,
    ToolDefinition,
    ToolResultBlock,
)
from app.agent.state import (
    BUSCAR_CONHECIMENTO,
    ESCALAR_PARA_HUMANO,
    ConversationState,
    TurnSignals,
    check_tool_allowed,
    decide_state,
    tools_for_state,
)
from app.core.errors import DomainError, ToolNotAllowedError

logger = structlog.get_logger()

MAX_ITERATIONS = 6
LLM_TIMEOUT_SECONDS = 20.0
TOOL_TIMEOUT_SECONDS = 10.0

# Frases neutras — `docs/04` §4: "nunca silêncio". A mesma frase da falha de
# LLM está fixada no doc; a de loop excedido não é, então escolhemos uma que
# não promete prazo (`docs/08` §5, "sem prometer prazo específico").
MENSAGEM_FALHA_LLM = "Só um instante, já te respondo."
MENSAGEM_LOOP_EXCEDIDO = "Deixa eu confirmar uma informação com o time e já te retorno."


@dataclass(slots=True)
class TurnContext:
    """Tudo que um turno precisa para rodar — `system` e `messages` já vêm
    prontos de `app/agent/prompts/renderer.py` e de quem monta o histórico;
    este módulo não sabe renderizar prompt nem consultar o banco.

    `signals` começa com o que já era verdade da conversa antes do turno
    (score e campos obrigatórios da qualificação persistida, por exemplo) e
    as ferramentas o atualizam durante o loop via `update_signals`.
    """

    tenant_id: uuid.UUID
    conversation_id: uuid.UUID
    turn_id: uuid.UUID
    state: ConversationState
    model: str
    system: str
    messages: list[LLMMessage]
    signals: TurnSignals = field(default_factory=TurnSignals)

    def update_signals(self, **kwargs: Any) -> None:
        self.signals = replace(self.signals, **kwargs)


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    """O que uma ferramenta devolve ao loop — `content` vira o texto do
    `tool_result` mandado de volta ao LLM (nunca stacktrace, `docs/04` §5)."""

    content: str
    is_error: bool = False


class ToolExecutor(Protocol):
    """Contrato que `app/agent/tools/` (tarefa 3.5) precisa cumprir. Recebe
    o `ctx` do turno para poder ler/gravar em `ctx.signals` — é assim que,
    por exemplo, `registrar_qualificacao` informa o novo score ao loop sem
    o loop precisar conhecer a tabela `qualifications`."""

    async def execute(
        self, *, name: str, tool_input: dict[str, Any], ctx: TurnContext
    ) -> ToolExecutionResult: ...


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    name: str
    input: dict[str, Any]
    is_error: bool


@dataclass(frozen=True, slots=True)
class TurnResult:
    reply: str
    new_state: ConversationState
    iterations: int
    tools_called: tuple[ToolCallRecord, ...]
    escalated: bool
    error: str | None
    usage: LLMUsage
    latency_ms: int
    guardrail_flags: tuple[dict[str, Any], ...] = ()


def _somar_usage(total: LLMUsage, parcial: LLMUsage) -> LLMUsage:
    return LLMUsage(
        input_tokens=total.input_tokens + parcial.input_tokens,
        output_tokens=total.output_tokens + parcial.output_tokens,
        cache_creation_input_tokens=(
            total.cache_creation_input_tokens + parcial.cache_creation_input_tokens
        ),
        cache_read_input_tokens=total.cache_read_input_tokens + parcial.cache_read_input_tokens,
        cost_cents=total.cost_cents + parcial.cost_cents,
    )


async def _executar_chamada(
    chamada_nome: str,
    chamada_input: dict[str, Any],
    *,
    ctx: TurnContext,
    tool_executor: ToolExecutor,
    tool_timeout_seconds: float,
) -> ToolExecutionResult:
    try:
        return await asyncio.wait_for(
            tool_executor.execute(name=chamada_nome, tool_input=chamada_input, ctx=ctx),
            timeout=tool_timeout_seconds,
        )
    except TimeoutError:
        logger.warning("ferramenta_expirou", tool=chamada_nome, timeout_s=tool_timeout_seconds)
        return ToolExecutionResult(
            content="Essa ação demorou demais e foi cancelada. Vou seguir sem ela por ora.",
            is_error=True,
        )
    except DomainError as exc:
        # Erro de regra de negócio conhecido (ex.: slot indisponível) — o
        # texto já é apresentável ao LLM, não precisa de tradução.
        logger.info("ferramenta_falhou_com_erro_de_dominio", tool=chamada_nome, code=exc.code)
        return ToolExecutionResult(content=exc.message, is_error=True)
    except Exception:
        # Fronteira de execução de plugin: uma ferramenta (tarefa 3.5+) pode
        # falhar de formas imprevistas. Não deixamos isso derrubar o turno
        # nem vazar stacktrace para o lead — vira erro tratável no loop, que
        # decide se escala.
        logger.exception("falha_inesperada_ao_executar_ferramenta", tool=chamada_nome)
        return ToolExecutionResult(content="Não consegui concluir essa ação agora.", is_error=True)


async def run_turn(
    ctx: TurnContext,
    *,
    llm: LLMProvider,
    tool_executor: ToolExecutor,
    tool_definitions: dict[str, ToolDefinition],
    max_iterations: int = MAX_ITERATIONS,
    llm_timeout_seconds: float = LLM_TIMEOUT_SECONDS,
    tool_timeout_seconds: float = TOOL_TIMEOUT_SECONDS,
) -> TurnResult:
    """Executa um turno completo — `docs/04` §4.

    `tool_definitions` é o catálogo de todas as ferramentas que existem no
    produto; a cada turno só expomos ao LLM as que `tools_for_state`
    libera para `ctx.state`. `check_tool_allowed` roda de novo por chamada,
    como segunda trava — a lista de ferramentas visíveis já devia bastar,
    mas nunca confiamos só na visibilidade para um guardrail de segurança.
    """
    estado_inicial = ctx.state
    nomes_permitidos = tools_for_state(estado_inicial)
    tools = [tool_definitions[nome] for nome in nomes_permitidos if nome in tool_definitions]

    inicio = time.monotonic()
    usage_total = LLMUsage(input_tokens=0, output_tokens=0)
    registros: list[ToolCallRecord] = []
    guardrail_flags: list[dict[str, Any]] = []
    resposta: LLMResponse | None = None
    erro: str | None = None
    iteracoes = 0

    try:
        for iteracoes in range(1, max_iterations + 1):  # noqa: B007 — usado no retorno, fora do loop
            resposta = await asyncio.wait_for(
                llm.complete(
                    system=ctx.system,
                    messages=ctx.messages,
                    tools=tools,
                    model=ctx.model,
                    max_tokens=1024,
                    temperature=0.4,
                ),
                timeout=llm_timeout_seconds,
            )
            usage_total = _somar_usage(usage_total, resposta.usage)

            if resposta.stop_reason != "tool_use":
                break

            ctx.messages.append(LLMMessage(role="assistant", content=resposta.content))
            resultados_da_rodada: list[ContentBlock] = []

            for chamada in resposta.tool_calls:
                try:
                    check_tool_allowed(chamada.name, estado_inicial)
                except ToolNotAllowedError as exc:
                    logger.warning(
                        "ferramenta_nao_permitida_no_estado",
                        tool=chamada.name,
                        state=str(estado_inicial),
                    )
                    guardrail_flags.append({"type": "tool_not_allowed", "tool": chamada.name})
                    resultados_da_rodada.append(
                        ToolResultBlock(tool_use_id=chamada.id, content=str(exc), is_error=True)
                    )
                    continue

                resultado = await _executar_chamada(
                    chamada.name,
                    chamada.input,
                    ctx=ctx,
                    tool_executor=tool_executor,
                    tool_timeout_seconds=tool_timeout_seconds,
                )
                ctx.update_signals(tools_called=ctx.signals.tools_called | {chamada.name})
                registros.append(
                    ToolCallRecord(
                        name=chamada.name, input=chamada.input, is_error=resultado.is_error
                    )
                )
                resultados_da_rodada.append(
                    ToolResultBlock(
                        tool_use_id=chamada.id,
                        content=resultado.content,
                        is_error=resultado.is_error,
                    )
                )

            ctx.messages.append(LLMMessage(role="user", content=resultados_da_rodada))
        else:
            # `for...else`: só roda se o `for` terminou sem `break`, ou seja,
            # esgotamos `max_iterations` ainda pedindo `tool_use`.
            logger.warning(
                "max_iterations_excedido",
                conversation_id=str(ctx.conversation_id),
                turn_id=str(ctx.turn_id),
            )
            erro = "max_iterations_excedido"
            ctx.update_signals(tools_called=ctx.signals.tools_called | {ESCALAR_PARA_HUMANO})
    except (TimeoutError, DomainError) as exc:
        logger.error("falha_definitiva_llm", error=str(exc), turn_id=str(ctx.turn_id))
        erro = str(exc)
        ctx.update_signals(tools_called=ctx.signals.tools_called | {ESCALAR_PARA_HUMANO})

    if erro == "max_iterations_excedido":
        texto_resposta = MENSAGEM_LOOP_EXCEDIDO
    elif erro is not None:
        texto_resposta = MENSAGEM_FALHA_LLM
    else:
        assert resposta is not None  # loop só sai sem erro depois de ao menos 1 resposta
        texto_resposta = resposta.text or MENSAGEM_FALHA_LLM

    sinais_finais = ctx.signals
    if BUSCAR_CONHECIMENTO in sinais_finais.tools_called:
        sinais_finais = replace(sinais_finais, has_open_question=True)

    novo_estado = decide_state(estado_inicial, sinais_finais)
    escalado = ESCALAR_PARA_HUMANO in sinais_finais.tools_called

    return TurnResult(
        reply=texto_resposta,
        new_state=novo_estado,
        iterations=iteracoes,
        tools_called=tuple(registros),
        escalated=escalado,
        error=erro,
        usage=usage_total,
        latency_ms=int((time.monotonic() - inicio) * 1000),
        guardrail_flags=tuple(guardrail_flags),
    )
