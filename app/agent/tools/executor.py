"""Executor concreto de ferramentas — implementa o `Protocol` `ToolExecutor`
de `app/agent/runtime.py` roteando por nome (roadmap 3.5).

`TOOL_DEFINITIONS` é o catálogo completo passado a `run_turn` como
`tool_definitions`; `tools_for_state` (`app/agent/state.py`) já filtra o que
fica visível ao LLM a cada turno.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from app.agent.llm.base import ToolDefinition
from app.agent.runtime import ToolExecutionResult, TurnContext
from app.agent.tools import (
    desqualificar,
    encerrar_conversa,
    escalar_para_humano,
    registrar_dados_lead,
    registrar_qualificacao,
)
from app.agent.tools.base import ToolDeps

_Handler = Callable[..., Awaitable[ToolExecutionResult]]

_HANDLERS: dict[str, _Handler] = {
    registrar_dados_lead.NAME: registrar_dados_lead.execute,
    registrar_qualificacao.NAME: registrar_qualificacao.execute,
    escalar_para_humano.NAME: escalar_para_humano.execute,
    desqualificar.NAME: desqualificar.execute,
    encerrar_conversa.NAME: encerrar_conversa.execute,
}

TOOL_DEFINITIONS: dict[str, ToolDefinition] = {
    registrar_dados_lead.NAME: registrar_dados_lead.DEFINITION,
    registrar_qualificacao.NAME: registrar_qualificacao.DEFINITION,
    escalar_para_humano.NAME: escalar_para_humano.DEFINITION,
    desqualificar.NAME: desqualificar.DEFINITION,
    encerrar_conversa.NAME: encerrar_conversa.DEFINITION,
}


class DefaultToolExecutor:
    """`ToolDeps` é fixo para todas as ferramentas do turno — a sessão, o
    contato e a config do tenant não mudam entre chamadas dentro do mesmo
    `run_turn`."""

    def __init__(self, deps: ToolDeps) -> None:
        self._deps = deps

    async def execute(
        self, *, name: str, tool_input: dict[str, Any], ctx: TurnContext
    ) -> ToolExecutionResult:
        handler = _HANDLERS.get(name)
        if handler is None:
            return ToolExecutionResult(
                content=f"Ferramenta '{name}' não está implementada.", is_error=True
            )
        return await handler(tool_input, ctx=ctx, deps=self._deps)
