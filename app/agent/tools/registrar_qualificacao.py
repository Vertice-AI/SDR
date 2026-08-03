"""`registrar_qualificacao` — `docs/04-motor-de-conversa.md` §5,
`docs/08-qualificacao-e-handoff.md` §2-3, roadmap 3.5.

Uma chamada por campo do framework de qualificação do tenant. Recalcula
score e classificação a cada chamada (`app/services/qualification.py`,
roadmap 3.6) e atualiza `ctx.signals` para `decide_state` decidir se a
conversa já pode ir para `agendando`.
"""

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.agent.llm.base import ToolDefinition
from app.agent.runtime import ToolExecutionResult, TurnContext
from app.agent.state import REGISTRAR_QUALIFICACAO
from app.agent.tools.base import ToolDeps, validation_error_message
from app.models import Qualification
from app.repositories.qualification import QualificationRepository
from app.services.qualification import calculate_score, classify_score, required_fields_filled

NAME = REGISTRAR_QUALIFICACAO

DEFINITION = ToolDefinition(
    name=NAME,
    description=(
        "Registra a resposta de um campo do framework de qualificação. "
        "Chame assim que a informação aparecer na conversa, mesmo dita de "
        "forma indireta — uma chamada por campo."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "campo": {
                "type": "string",
                "description": "Chave do campo de qualificação (ver campos do tenant)",
            },
            "valor": {"type": "string", "description": "Valor informado pelo lead"},
            "confianca": {
                "type": "number",
                "description": "Confiança de 0 a 1 de que o valor extraído está correto",
            },
        },
        "required": ["campo", "valor"],
    },
)


class _Input(BaseModel):
    campo: str
    valor: str
    confianca: float = Field(default=1.0, ge=0.0, le=1.0)


async def execute(
    tool_input: dict[str, Any], *, ctx: TurnContext, deps: ToolDeps
) -> ToolExecutionResult:
    try:
        dados = _Input.model_validate(tool_input)
    except ValidationError as exc:
        return ToolExecutionResult(content=validation_error_message(exc), is_error=True)

    campos_config = deps.tenant_config.qualification_fields
    chaves_validas = {str(field.get("key")) for field in campos_config}
    if dados.campo not in chaves_validas:
        return ToolExecutionResult(
            content=(
                f"Campo de qualificação desconhecido: '{dados.campo}'. "
                f"Campos válidos: {', '.join(sorted(chaves_validas)) or 'nenhum configurado'}."
            ),
            is_error=True,
        )

    repo = QualificationRepository(deps.session)
    qualification = await repo.get_by_conversation_id(ctx.conversation_id)
    if qualification is None:
        qualification = await repo.add(Qualification(conversation_id=ctx.conversation_id))

    answers = dict(qualification.answers)
    answers[dados.campo] = {"valor": dados.valor, "confianca": dados.confianca}
    qualification.answers = answers

    score = calculate_score(answers, campos_config)
    classification = classify_score(score, deps.tenant_config.classification_bands)
    qualification.score = score
    qualification.classification = classification

    campos_completos = required_fields_filled(answers, campos_config)

    ctx.update_signals(
        qualification_score=score,
        required_fields_filled=campos_completos,
        scheduling_threshold=deps.tenant_config.scheduling_threshold,
    )

    faltando = sorted(
        str(field.get("key"))
        for field in campos_config
        if field.get("required") and field.get("key") not in answers
    )
    status_campos = (
        "todos os campos obrigatórios preenchidos"
        if not faltando
        else (f"faltam: {', '.join(faltando)}")
    )
    return ToolExecutionResult(
        content=f"Registrado. Score atual: {score} ({classification}); {status_campos}."
    )
