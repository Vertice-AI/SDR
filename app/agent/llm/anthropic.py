"""`LLMProvider` sobre o SDK oficial da Anthropic (ADR-007).

Cobre a tarefa 3.1 do roadmap: tool calling, contagem de tokens, custo por
chamada, prompt caching no bloco de sistema e retry só em erro transitório
(`docs/04-motor-de-conversa.md` §4 — 2 tentativas, só em 429/5xx/timeout).
"""

import time
from typing import Any, cast

import anthropic
import structlog
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.agent.llm.base import (
    ContentBlock,
    LLMMessage,
    LLMResponse,
    LLMUsage,
    StopReason,
    TextBlock,
    ToolDefinition,
    ToolUseBlock,
)
from app.core.errors import ExternalServiceError

logger = structlog.get_logger()

# USD por milhão de tokens: (entrada, saída, escrita em cache, leitura de
# cache). Atualizar aqui se a Anthropic mudar preço — não há como consultar
# isso via API. Prefixo porque o nome completo do modelo às vezes carrega
# sufixo de versão/data.
_PRICING_USD_POR_MILHAO: dict[str, tuple[float, float, float, float]] = {
    "claude-sonnet-5": (3.0, 15.0, 3.75, 0.30),
    "claude-haiku-4-5": (0.80, 4.0, 1.0, 0.08),
}
_PRICING_PADRAO = (3.0, 15.0, 3.75, 0.30)

_STOP_REASONS_CONHECIDOS: set[str] = {"end_turn", "max_tokens", "tool_use", "stop_sequence"}


def _pricing_para(model: str) -> tuple[float, float, float, float]:
    for prefixo, valores in _PRICING_USD_POR_MILHAO.items():
        if model.startswith(prefixo):
            return valores
    logger.warning("preco_desconhecido_para_modelo", model=model)
    return _PRICING_PADRAO


def _custo_centavos(model: str, usage: anthropic.types.Usage) -> float:
    preco_entrada, preco_saida, preco_escrita_cache, preco_leitura_cache = _pricing_para(model)
    escrita_cache = usage.cache_creation_input_tokens or 0
    leitura_cache = usage.cache_read_input_tokens or 0
    usd = (
        usage.input_tokens * preco_entrada
        + usage.output_tokens * preco_saida
        + escrita_cache * preco_escrita_cache
        + leitura_cache * preco_leitura_cache
    ) / 1_000_000
    return float(usd * 100)


def _bloco_para_anthropic(bloco: ContentBlock) -> dict[str, Any]:
    if isinstance(bloco, TextBlock):
        return {"type": "text", "text": bloco.text}
    if isinstance(bloco, ToolUseBlock):
        return {"type": "tool_use", "id": bloco.id, "name": bloco.name, "input": bloco.input}
    return {
        "type": "tool_result",
        "tool_use_id": bloco.tool_use_id,
        "content": bloco.content,
        "is_error": bloco.is_error,
    }


def _mensagem_para_anthropic(msg: LLMMessage) -> dict[str, Any]:
    if isinstance(msg.content, str):
        return {"role": msg.role, "content": msg.content}
    return {"role": msg.role, "content": [_bloco_para_anthropic(b) for b in msg.content]}


def _ferramenta_para_anthropic(tool: ToolDefinition) -> dict[str, Any]:
    return {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}


def _bloco_de_resposta_para_canonico(bloco: Any) -> ContentBlock | None:
    if bloco.type == "text":
        return TextBlock(text=bloco.text)
    if bloco.type == "tool_use":
        return ToolUseBlock(id=bloco.id, name=bloco.name, input=dict(bloco.input))
    logger.warning("bloco_de_resposta_ignorado", tipo=bloco.type)
    return None


def _stop_reason_canonico(valor: str | None) -> StopReason:
    if valor in _STOP_REASONS_CONHECIDOS:
        return cast(StopReason, valor)
    # `pause_turn`/`refusal`/`model_context_window_exceeded` são casos raros
    # e novos na API — tratamos como fim de turno normal em vez de quebrar
    # o loop; quem chama só reage a "tool_use" de forma diferente.
    logger.warning("stop_reason_desconhecido", stop_reason=valor)
    return "end_turn"


def _erro_retryable(exc: BaseException) -> bool:
    return isinstance(exc, ExternalServiceError) and exc.retryable


class AnthropicProvider:
    """Implementação de `LLMProvider` sobre `anthropic.AsyncAnthropic`."""

    def __init__(self, api_key: str, *, timeout_seconds: float = 20.0) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout_seconds)

    async def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.4,
    ) -> LLMResponse:
        return await self._complete_com_retry(
            system=system,
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    @retry(
        retry=retry_if_exception(_erro_retryable),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, max=8),
        reraise=True,
    )
    async def _complete_com_retry(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        inicio = time.monotonic()
        anthropic_tools = [_ferramenta_para_anthropic(t) for t in (tools or [])]
        kwargs: dict[str, Any] = {}
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools
        try:
            # As TypedDicts do SDK para `tools`/`messages` são uma união
            # grande demais para valer a pena espelhar aqui — construímos
            # dicts equivalentes e confiamos no formato documentado da API.
            response = await self._client.messages.create(
                model=model,
                # Bloco único de sistema com `cache_control`: é o que segura
                # o custo por conversa (`docs/04` §4) — o prompt de sistema
                # renderizado por tenant costuma ser grande e repete a cada
                # turno.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=cast(Any, [_mensagem_para_anthropic(m) for m in messages]),
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            )
        except anthropic.APIStatusError as exc:
            retryable = exc.status_code >= 500 or exc.status_code == 429
            raise ExternalServiceError(
                f"Anthropic API: {exc.message}", retryable=retryable
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ExternalServiceError("Anthropic API: falha de conexão", retryable=True) from exc

        latencia_ms = int((time.monotonic() - inicio) * 1000)
        blocos = [
            bloco
            for bloco in (_bloco_de_resposta_para_canonico(b) for b in response.content)
            if bloco is not None
        ]
        usage = LLMUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_creation_input_tokens=response.usage.cache_creation_input_tokens or 0,
            cache_read_input_tokens=response.usage.cache_read_input_tokens or 0,
            cost_cents=_custo_centavos(model, response.usage),
        )
        return LLMResponse(
            content=blocos,
            stop_reason=_stop_reason_canonico(response.stop_reason),
            usage=usage,
            latency_ms=latencia_ms,
        )

    async def count_tokens(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str,
    ) -> int:
        anthropic_tools = [_ferramenta_para_anthropic(t) for t in (tools or [])]
        kwargs: dict[str, Any] = {}
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools
        response = await self._client.messages.count_tokens(
            model=model,
            system=system,
            messages=cast(Any, [_mensagem_para_anthropic(m) for m in messages]),
            **kwargs,
        )
        return response.input_tokens
