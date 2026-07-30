"""Abstração `LLMProvider` — isola o SDK da Anthropic do resto do agente
(ADR-007 em `docs/02-arquitetura.md`, `CLAUDE.md` §2). Trocar de provedor
(ex.: OpenAI) exige só uma nova implementação deste `Protocol`, sem tocar no
loop de tool calling (`app/agent/runtime.py`, tarefa 3.4).

Os blocos de conteúdo (`TextBlock`, `ToolUseBlock`, `ToolResultBlock`) são o
formato canônico usado para reconstruir o histórico da conversa entre
iterações do loop — ver pseudocódigo em `docs/04-motor-de-conversa.md` §4.
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol

Role = Literal["user", "assistant"]
StopReason = Literal["end_turn", "max_tokens", "tool_use", "stop_sequence"]


@dataclass(frozen=True, slots=True)
class TextBlock:
    text: str


@dataclass(frozen=True, slots=True)
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResultBlock:
    tool_use_id: str
    content: str
    is_error: bool = False


ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: Role
    content: str | list[ContentBlock]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LLMUsage:
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cost_cents: float = 0.0


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: list[ContentBlock]
    stop_reason: StopReason
    usage: LLMUsage
    latency_ms: int

    @property
    def text(self) -> str:
        return "".join(bloco.text for bloco in self.content if isinstance(bloco, TextBlock))

    @property
    def tool_calls(self) -> list[ToolUseBlock]:
        return [bloco for bloco in self.content if isinstance(bloco, ToolUseBlock)]


class LLMProvider(Protocol):
    """Contrato que todo provedor de LLM precisa cumprir. `system` é sempre
    string — cabe à implementação decidir como fatiar em blocos para o
    prompt caching (`docs/04` §4)."""

    async def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.4,
    ) -> LLMResponse: ...

    async def count_tokens(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str,
    ) -> int: ...
