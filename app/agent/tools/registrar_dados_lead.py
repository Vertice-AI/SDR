"""`registrar_dados_lead` — `docs/04-motor-de-conversa.md` §5, roadmap 3.5.

Atualiza `contacts` com o que o lead informou. Chamada sempre que um dado
novo aparece na conversa, para o agente nunca perguntar de novo depois.
"""

from typing import Any

from pydantic import BaseModel, ValidationError

from app.agent.llm.base import ToolDefinition
from app.agent.runtime import ToolExecutionResult, TurnContext
from app.agent.state import REGISTRAR_DADOS_LEAD
from app.agent.tools.base import ToolDeps, validation_error_message
from app.repositories.contact import ContactRepository

NAME = REGISTRAR_DADOS_LEAD

DEFINITION = ToolDefinition(
    name=NAME,
    description=(
        "Registra dados do lead assim que ele os informar (nome, e-mail, "
        "empresa, cargo). Chame sempre que um desses dados aparecer na "
        "conversa, mesmo de forma indireta, para nunca perguntar de novo."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "nome": {"type": "string", "description": "Nome do lead"},
            "email": {"type": "string", "description": "E-mail do lead"},
            "empresa": {"type": "string", "description": "Empresa do lead"},
            "cargo": {"type": "string", "description": "Cargo do lead"},
        },
    },
)


class _Input(BaseModel):
    nome: str | None = None
    email: str | None = None
    empresa: str | None = None
    cargo: str | None = None


async def execute(
    tool_input: dict[str, Any], *, ctx: TurnContext, deps: ToolDeps
) -> ToolExecutionResult:
    try:
        dados = _Input.model_validate(tool_input)
    except ValidationError as exc:
        return ToolExecutionResult(content=validation_error_message(exc), is_error=True)

    campos = dados.model_dump(exclude_none=True)
    if not campos:
        return ToolExecutionResult(
            content="Nenhum dado novo informado — nada para registrar.", is_error=True
        )

    contato = await ContactRepository(deps.session).get(deps.contact_id)
    if contato is None:
        return ToolExecutionResult(content="Contato não encontrado.", is_error=True)

    if dados.nome:
        contato.name = dados.nome
    if dados.email:
        contato.email = dados.email
    if dados.empresa:
        contato.company = dados.empresa
    if dados.cargo:
        contato.role_title = dados.cargo

    atualizados = ", ".join(campos.keys())
    return ToolExecutionResult(content=f"Dados do lead atualizados: {atualizados}.")
