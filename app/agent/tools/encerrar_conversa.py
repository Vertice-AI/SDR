"""`encerrar_conversa` — `docs/04-motor-de-conversa.md` §5, roadmap 3.5.

Para agradecimento final ou lead que só queria uma informação pontual — não
é desqualificação nem handoff, só o fim natural da conversa.
"""

from typing import Any

from pydantic import BaseModel, ValidationError

from app.agent.llm.base import ToolDefinition
from app.agent.runtime import ToolExecutionResult, TurnContext
from app.agent.state import ENCERRAR_CONVERSA
from app.agent.tools.base import ToolDeps, validation_error_message
from app.repositories.conversation import ConversationRepository

NAME = ENCERRAR_CONVERSA

DEFINITION = ToolDefinition(
    name=NAME,
    description=(
        "Encerra a conversa quando o lead agradece e não tem mais nada a "
        "tratar, ou só queria uma informação pontual e não segue para "
        "qualificação."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "motivo": {"type": "string", "description": "Motivo do encerramento"},
        },
        "required": ["motivo"],
    },
)


class _Input(BaseModel):
    motivo: str


async def execute(
    tool_input: dict[str, Any], *, ctx: TurnContext, deps: ToolDeps
) -> ToolExecutionResult:
    try:
        dados = _Input.model_validate(tool_input)
    except ValidationError as exc:
        return ToolExecutionResult(content=validation_error_message(exc), is_error=True)

    conversa = await ConversationRepository(deps.session).get(ctx.conversation_id)
    if conversa is not None:
        conversa.status = "closed"
        conversa.closed_reason = dados.motivo

    return ToolExecutionResult(content="Conversa encerrada.")
