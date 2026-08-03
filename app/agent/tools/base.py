"""Infra comum das ferramentas do agente — `docs/04-motor-de-conversa.md`
§5, roadmap 3.5.

Cada ferramenta vive no seu próprio arquivo e expõe `NAME`, `DEFINITION`
(schema exposto ao LLM) e uma função `execute()` com a assinatura
`(tool_input, *, ctx, deps) -> ToolExecutionResult`. `ToolDeps` carrega o que
a maioria das ferramentas precisa e que `TurnContext` não tem, por não ser
dado de turno: a sessão do banco, o contato da conversa e a config viva do
tenant.
"""

import uuid
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TenantConfig


@dataclass(frozen=True, slots=True)
class ToolDeps:
    session: AsyncSession
    contact_id: uuid.UUID
    tenant_config: TenantConfig


def validation_error_message(exc: ValidationError) -> str:
    """Traduz o primeiro erro do Pydantic numa frase que o LLM entende e
    consegue corrigir na próxima chamada — nunca o repr da exceção
    (`docs/04` §5: "tratamento de erro que devolve mensagem útil ao LLM,
    nunca stacktrace")."""
    primeiro = exc.errors()[0]
    campo = ".".join(str(parte) for parte in primeiro["loc"]) or "entrada"
    return f"Entrada inválida em '{campo}': {primeiro['msg']}."
