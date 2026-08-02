"""Máquina de estados da conversa — `docs/04-motor-de-conversa.md` §3.

O estado **não** controla o que o agente diz — isso é o LLM. O estado
controla o que é **permitido**: quais ferramentas ficam disponíveis
(`tools_for_state`) e para qual bloco de prompt o turno aponta
(`app/agent/prompts/state_blocks/`, `docs/05` §2).

Transições são decididas por código depois do turno, a partir do resultado
das ferramentas chamadas — nunca pelo texto que o LLM gerou. `decide_state`
é essa decisão; quem monta o `TurnSignals` é `app/agent/runtime.py`.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from app.core.errors import ToolNotAllowedError

DEFAULT_SCHEDULING_THRESHOLD = 45
"""`scheduling_threshold` padrão — `docs/08-qualificacao-e-handoff.md` §3."""


class ConversationState(StrEnum):
    NOVO = "novo"
    ABERTURA = "abertura"
    QUALIFICANDO = "qualificando"
    RESPONDENDO_DUVIDAS = "respondendo_duvidas"
    AGENDANDO = "agendando"
    AGENDADO = "agendado"
    AGUARDANDO_LEAD = "aguardando_lead"
    HANDOFF_HUMANO = "handoff_humano"
    DESQUALIFICADO = "desqualificado"
    ENCERRADO = "encerrado"
    OPT_OUT = "opt_out"


# Nomes das ferramentas — `docs/04` §5. Vivem aqui (e não em
# `app/agent/tools/`, tarefa 3.5) porque o mapeamento estado → ferramenta
# não depende da implementação da ferramenta, só do nome.
BUSCAR_CONHECIMENTO = "buscar_conhecimento"
REGISTRAR_DADOS_LEAD = "registrar_dados_lead"
REGISTRAR_QUALIFICACAO = "registrar_qualificacao"
DESQUALIFICAR = "desqualificar"
CONSULTAR_HORARIOS_DISPONIVEIS = "consultar_horarios_disponiveis"
AGENDAR_REUNIAO = "agendar_reuniao"
REAGENDAR_REUNIAO = "reagendar_reuniao"
CANCELAR_REUNIAO = "cancelar_reuniao"
ESCALAR_PARA_HUMANO = "escalar_para_humano"
ENCERRAR_CONVERSA = "encerrar_conversa"

_ABERTURA_TOOLS = frozenset({BUSCAR_CONHECIMENTO, REGISTRAR_DADOS_LEAD, ESCALAR_PARA_HUMANO})
_QUALIFICANDO_TOOLS = _ABERTURA_TOOLS | {REGISTRAR_QUALIFICACAO, DESQUALIFICAR}
# `respondendo_duvidas` é alcançado a partir de `qualificando` ou de
# `agendando` (docs/04 §3) — mantém tudo que já estava liberado, só muda a
# ênfase do prompt para `buscar_conhecimento` (ver `state_blocks/respondendo_duvidas.j2`).
_RESPONDENDO_DUVIDAS_TOOLS = _QUALIFICANDO_TOOLS
_AGENDANDO_TOOLS = _RESPONDENDO_DUVIDAS_TOOLS | {
    CONSULTAR_HORARIOS_DISPONIVEIS,
    AGENDAR_REUNIAO,
}
_AGENDADO_TOOLS = _AGENDANDO_TOOLS | {REAGENDAR_REUNIAO, CANCELAR_REUNIAO}

TOOLS_BY_STATE: dict[ConversationState, frozenset[str]] = {
    ConversationState.NOVO: frozenset(),
    ConversationState.ABERTURA: _ABERTURA_TOOLS,
    ConversationState.QUALIFICANDO: _QUALIFICANDO_TOOLS,
    ConversationState.RESPONDENDO_DUVIDAS: _RESPONDENDO_DUVIDAS_TOOLS,
    ConversationState.AGENDANDO: _AGENDANDO_TOOLS,
    ConversationState.AGENDADO: _AGENDADO_TOOLS,
    ConversationState.AGUARDANDO_LEAD: frozenset(),
    ConversationState.HANDOFF_HUMANO: frozenset(),
    ConversationState.DESQUALIFICADO: frozenset(),
    ConversationState.ENCERRADO: frozenset(),
    ConversationState.OPT_OUT: frozenset(),
}

# Estados em que o agente nunca gera mensagem — nem prompt de sistema é
# renderizado (`app/agent/prompts/renderer.py`). `desqualificado` fica de
# fora de propósito: se o lead insistir depois de desqualificado, o agente
# ainda responde uma vez, com gentileza (`state_blocks/desqualificado.j2`).
ESTADOS_SEM_RESPOSTA = frozenset(
    {
        ConversationState.NOVO,
        ConversationState.AGUARDANDO_LEAD,
        ConversationState.HANDOFF_HUMANO,
        ConversationState.ENCERRADO,
        ConversationState.OPT_OUT,
    }
)


def tools_for_state(state: ConversationState | str) -> frozenset[str]:
    """Ferramentas liberadas para o estado — `docs/04` §3."""
    return TOOLS_BY_STATE[ConversationState(state)]


def check_tool_allowed(tool_name: str, state: ConversationState | str) -> None:
    """Guardrail chamado antes de executar toda ferramenta (`docs/04` §4).

    O estado é a fonte da verdade sobre o que pode ser chamado — nunca o
    texto ou a intenção do LLM.
    """
    if tool_name not in tools_for_state(state):
        raise ToolNotAllowedError(
            f"ferramenta '{tool_name}' não é permitida no estado '{state}'",
            details={"tool_name": tool_name, "state": str(state)},
        )


@dataclass(frozen=True, slots=True)
class TurnSignals:
    """O que o turno produziu, relevante para decidir o próximo estado.

    Montado por `app/agent/runtime.py` a partir do resultado das ferramentas
    e da classificação de intenção — nunca a partir do texto gerado pelo LLM.
    """

    tools_called: frozenset[str] = field(default_factory=frozenset)
    opt_out_detected: bool = False
    has_open_question: bool = False
    qualification_score: int = 0
    required_fields_filled: bool = False
    scheduling_threshold: int = DEFAULT_SCHEDULING_THRESHOLD


def decide_state(current: ConversationState | str, signals: TurnSignals) -> ConversationState:
    """Próximo estado da conversa, a partir do estado atual e do que o
    turno produziu — `docs/04` §3, `docs/08` §5 e §7.

    Ordem de prioridade: opt-out e os desfechos definitivos (handoff,
    desqualificação, encerramento) sempre vencem, independente do estado de
    origem; o resto segue a progressão natural da qualificação.
    """
    current = ConversationState(current)
    called = signals.tools_called

    if signals.opt_out_detected:
        return ConversationState.OPT_OUT
    if ESCALAR_PARA_HUMANO in called:
        return ConversationState.HANDOFF_HUMANO
    if DESQUALIFICAR in called:
        return ConversationState.DESQUALIFICADO
    if ENCERRAR_CONVERSA in called:
        return ConversationState.ENCERRADO
    if AGENDAR_REUNIAO in called:
        return ConversationState.AGENDADO
    if CANCELAR_REUNIAO in called:
        return ConversationState.AGENDANDO
    if REAGENDAR_REUNIAO in called:
        return ConversationState.AGENDADO

    if current in (ConversationState.QUALIFICANDO, ConversationState.AGENDANDO) and (
        signals.has_open_question
    ):
        return ConversationState.RESPONDENDO_DUVIDAS

    progressao_liberada = current in (
        ConversationState.ABERTURA,
        ConversationState.QUALIFICANDO,
        ConversationState.RESPONDENDO_DUVIDAS,
    )
    if (
        progressao_liberada
        and signals.required_fields_filled
        and signals.qualification_score >= signals.scheduling_threshold
    ):
        return ConversationState.AGENDANDO

    if current is ConversationState.ABERTURA and (
        REGISTRAR_QUALIFICACAO in called or signals.qualification_score > 0
    ):
        return ConversationState.QUALIFICANDO

    if current is ConversationState.RESPONDENDO_DUVIDAS:
        return ConversationState.QUALIFICANDO

    return current
