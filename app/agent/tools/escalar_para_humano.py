"""`escalar_para_humano` — `docs/04-motor-de-conversa.md` §5,
`docs/08-qualificacao-e-handoff.md` §5, roadmap 3.5.

Cria o registro de handoff, silencia o status da conversa para humano e
devolve ao LLM a frase de transição configurada pelo tenant — nunca deixar o
LLM improvisar promessa de prazo (`docs/08` §5).
"""

from typing import Any, Literal, get_args

from pydantic import BaseModel, ValidationError

from app.agent.llm.base import ToolDefinition
from app.agent.runtime import ToolExecutionResult, TurnContext
from app.agent.state import ESCALAR_PARA_HUMANO
from app.agent.tools.base import ToolDeps, validation_error_message
from app.models import Handoff
from app.repositories.conversation import ConversationRepository
from app.repositories.handoff import HandoffRepository

NAME = ESCALAR_PARA_HUMANO

Motivo = Literal[
    "lead_pediu",
    "sem_resposta_na_base",
    "irritacao",
    "tema_sensivel",
    "lead_quente",
    "manual",
    "erro_tecnico",
]
_MOTIVOS: tuple[Motivo, ...] = get_args(Motivo)

DEFAULT_TRANSITION_MESSAGE = (
    "Vou chamar alguém do time aqui para te ajudar com isso. Já te retorno."
)

DEFINITION = ToolDefinition(
    name=NAME,
    description=(
        "Escala a conversa para um humano do time e silencia o agente nela. "
        "Use quando o lead pedir para falar com alguém, quando não houver "
        "resposta na base para uma pergunta factual, em caso de irritação, "
        "tema sensível, pedido de desconto/proposta ou lead muito quente."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "motivo": {"type": "string", "enum": list(_MOTIVOS)},
            "resumo": {
                "type": "string",
                "description": "Resumo curto do que o lead precisa, para quem for assumir",
            },
        },
        "required": ["motivo", "resumo"],
    },
)


class _Input(BaseModel):
    motivo: Motivo
    resumo: str


async def execute(
    tool_input: dict[str, Any], *, ctx: TurnContext, deps: ToolDeps
) -> ToolExecutionResult:
    try:
        dados = _Input.model_validate(tool_input)
    except ValidationError as exc:
        return ToolExecutionResult(content=validation_error_message(exc), is_error=True)

    await HandoffRepository(deps.session).add(
        Handoff(
            conversation_id=ctx.conversation_id,
            reason=dados.motivo,
            notified_channels={"summary": dados.resumo},
        )
    )

    conversa = await ConversationRepository(deps.session).get(ctx.conversation_id)
    if conversa is not None:
        conversa.status = "human_handoff"

    mensagem = deps.tenant_config.handoff_transition_message or DEFAULT_TRANSITION_MESSAGE
    return ToolExecutionResult(content=mensagem)
