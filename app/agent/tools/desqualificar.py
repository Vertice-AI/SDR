"""`desqualificar` — `docs/04-motor-de-conversa.md` §5,
`docs/08-qualificacao-e-handoff.md` §4, roadmap 3.5.

Encerra educadamente um lead fora do ICP. `motivo` é texto livre porque
`disqualification_rules` é configurável por tenant (`docs/03` §7); quando o
motivo casa com o `reason` de uma regra configurada, devolve a `response`
dela ao LLM em vez de uma frase genérica — nunca "você não se qualifica"
(`docs/08` §4).
"""

from typing import Any

from pydantic import BaseModel, ValidationError

from app.agent.llm.base import ToolDefinition
from app.agent.runtime import ToolExecutionResult, TurnContext
from app.agent.state import DESQUALIFICAR
from app.agent.tools.base import ToolDeps, validation_error_message
from app.models import Qualification
from app.repositories.conversation import ConversationRepository
from app.repositories.qualification import QualificationRepository

NAME = DESQUALIFICAR

DEFAULT_MESSAGE = (
    "Pelo que você me contou, acho que esse não é o momento certo para "
    "avançarmos. Agradeço a conversa e, se algo mudar, será um prazer "
    "retomar."
)

DEFINITION = ToolDefinition(
    name=NAME,
    description=(
        "Encerra a qualificação de um lead fora do ICP, com gentileza. "
        "Nunca usar para maltratar ou explicar o critério interno ao lead."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "motivo": {
                "type": "string",
                "description": "Motivo da desqualificação, para o registro interno",
            },
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

    repo = QualificationRepository(deps.session)
    qualification = await repo.get_by_conversation_id(ctx.conversation_id)
    if qualification is None:
        qualification = await repo.add(Qualification(conversation_id=ctx.conversation_id))
    qualification.classification = "disqualified"
    qualification.disqualification_reason = dados.motivo

    conversa = await ConversationRepository(deps.session).get(ctx.conversation_id)
    if conversa is not None:
        conversa.status = "disqualified"
        conversa.closed_reason = dados.motivo

    regra = next(
        (
            rule
            for rule in deps.tenant_config.disqualification_rules
            if rule.get("reason") == dados.motivo
        ),
        None,
    )
    mensagem = (regra.get("response") if regra else None) or DEFAULT_MESSAGE
    return ToolExecutionResult(content=str(mensagem))
