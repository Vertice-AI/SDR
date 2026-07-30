"""`AnthropicProvider` — conversão de/para o formato canônico, custo por
chamada e retry só em erro transitório (`docs/04` §4, roadmap 3.1).

O cliente da Anthropic é substituído por um dublê: nenhum destes testes fala
com a rede.
"""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from anthropic import APIConnectionError, APIStatusError

from app.agent.llm.anthropic import AnthropicProvider
from app.agent.llm.base import LLMMessage, ToolDefinition, ToolUseBlock
from app.core.errors import ExternalServiceError


def _usage(
    *, input_tokens: int = 100, output_tokens: int = 50, cache_write: int = 0, cache_read: int = 0
) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_write,
        cache_read_input_tokens=cache_read,
    )


def _texto(texto: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=texto)


def _tool_use(*, id: str, name: str, input: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


def _message(
    *,
    content: list[Any],
    stop_reason: str | None = "end_turn",
    usage: SimpleNamespace | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(content=content, stop_reason=stop_reason, usage=usage or _usage())


def _provider_com_client_fake(create: AsyncMock | None = None) -> AnthropicProvider:
    provider = AnthropicProvider(api_key="test-key")
    cast(Any, provider)._client = SimpleNamespace(
        messages=SimpleNamespace(
            create=create or AsyncMock(),
            count_tokens=AsyncMock(return_value=SimpleNamespace(input_tokens=42)),
        )
    )
    return provider


def _resposta_http(status_code: int) -> httpx.Response:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx.Response(status_code=status_code, request=request, json={"error": {}})


async def test_complete_resposta_de_texto_simples() -> None:
    create = AsyncMock(return_value=_message(content=[_texto("oi, tudo bem?")]))
    provider = _provider_com_client_fake(create)

    resposta = await provider.complete(
        system="prompt do sistema",
        messages=[LLMMessage(role="user", content="oi")],
        model="claude-sonnet-5",
    )

    assert resposta.text == "oi, tudo bem?"
    assert resposta.stop_reason == "end_turn"
    assert resposta.tool_calls == []
    assert resposta.usage.input_tokens == 100
    assert resposta.usage.output_tokens == 50


async def test_complete_envia_bloco_de_sistema_com_cache_control() -> None:
    create = AsyncMock(return_value=_message(content=[_texto("ok")]))
    provider = _provider_com_client_fake(create)

    await provider.complete(
        system="prompt grande do tenant",
        messages=[LLMMessage(role="user", content="oi")],
        model="claude-sonnet-5",
    )

    kwargs = create.call_args.kwargs
    assert kwargs["system"] == [
        {"type": "text", "text": "prompt grande do tenant", "cache_control": {"type": "ephemeral"}}
    ]
    assert "tools" not in kwargs


async def test_complete_com_tool_use() -> None:
    create = AsyncMock(
        return_value=_message(
            content=[_tool_use(id="call_1", name="registrar_dados_lead", input={"nome": "Ana"})],
            stop_reason="tool_use",
        )
    )
    provider = _provider_com_client_fake(create)

    resposta = await provider.complete(
        system="sistema",
        messages=[LLMMessage(role="user", content="me chamo Ana")],
        tools=[
            ToolDefinition(
                name="registrar_dados_lead", description="...", input_schema={"type": "object"}
            )
        ],
        model="claude-sonnet-5",
    )

    assert resposta.stop_reason == "tool_use"
    assert resposta.tool_calls == [
        ToolUseBlock(id="call_1", name="registrar_dados_lead", input={"nome": "Ana"})
    ]
    kwargs = create.call_args.kwargs
    assert kwargs["tools"] == [
        {"name": "registrar_dados_lead", "description": "...", "input_schema": {"type": "object"}}
    ]


async def test_complete_calcula_custo_com_pricing_conhecido() -> None:
    create = AsyncMock(
        return_value=_message(
            content=[_texto("ok")],
            usage=_usage(input_tokens=1_000_000, output_tokens=1_000_000),
        )
    )
    provider = _provider_com_client_fake(create)

    resposta = await provider.complete(
        system="sistema", messages=[LLMMessage(role="user", content="oi")], model="claude-sonnet-5"
    )

    # 1M tokens de entrada a US$3 + 1M de saída a US$15 = US$18 = 1800 centavos.
    assert resposta.usage.cost_cents == pytest.approx(1800.0)


async def test_complete_pricing_desconhecido_nao_quebra() -> None:
    create = AsyncMock(return_value=_message(content=[_texto("ok")]))
    provider = _provider_com_client_fake(create)

    resposta = await provider.complete(
        system="sistema", messages=[LLMMessage(role="user", content="oi")], model="modelo-futuro-x"
    )

    assert resposta.usage.cost_cents > 0


async def test_complete_stop_reason_desconhecido_vira_end_turn() -> None:
    create = AsyncMock(return_value=_message(content=[_texto("ok")], stop_reason="pause_turn"))
    provider = _provider_com_client_fake(create)

    resposta = await provider.complete(
        system="sistema", messages=[LLMMessage(role="user", content="oi")], model="claude-sonnet-5"
    )

    assert resposta.stop_reason == "end_turn"


async def test_complete_erro_5xx_e_retryable_e_tenta_de_novo() -> None:
    create = AsyncMock(
        side_effect=[
            APIStatusError("erro interno", response=_resposta_http(500), body=None),
            _message(content=[_texto("recuperou")]),
        ]
    )
    provider = _provider_com_client_fake(create)

    resposta = await provider.complete(
        system="sistema", messages=[LLMMessage(role="user", content="oi")], model="claude-sonnet-5"
    )

    assert resposta.text == "recuperou"
    assert create.await_count == 2


async def test_complete_erro_429_e_retryable() -> None:
    create = AsyncMock(
        side_effect=[
            APIStatusError("rate limit", response=_resposta_http(429), body=None),
            _message(content=[_texto("recuperou")]),
        ]
    )
    provider = _provider_com_client_fake(create)

    resposta = await provider.complete(
        system="sistema", messages=[LLMMessage(role="user", content="oi")], model="claude-sonnet-5"
    )

    assert resposta.text == "recuperou"
    assert create.await_count == 2


async def test_complete_erro_4xx_nao_e_retryable() -> None:
    create = AsyncMock(
        side_effect=APIStatusError("payload inválido", response=_resposta_http(400), body=None)
    )
    provider = _provider_com_client_fake(create)

    with pytest.raises(ExternalServiceError) as exc_info:
        await provider.complete(
            system="sistema",
            messages=[LLMMessage(role="user", content="oi")],
            model="claude-sonnet-5",
        )

    assert exc_info.value.retryable is False
    assert create.await_count == 1


async def test_complete_erro_de_conexao_e_retryable() -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    create = AsyncMock(
        side_effect=[
            APIConnectionError(request=request),
            _message(content=[_texto("recuperou")]),
        ]
    )
    provider = _provider_com_client_fake(create)

    resposta = await provider.complete(
        system="sistema", messages=[LLMMessage(role="user", content="oi")], model="claude-sonnet-5"
    )

    assert resposta.text == "recuperou"
    assert create.await_count == 2


async def test_complete_esgota_tentativas_e_propaga_erro() -> None:
    create = AsyncMock(
        side_effect=APIStatusError("indisponível", response=_resposta_http(503), body=None)
    )
    provider = _provider_com_client_fake(create)

    with pytest.raises(ExternalServiceError) as exc_info:
        await provider.complete(
            system="sistema",
            messages=[LLMMessage(role="user", content="oi")],
            model="claude-sonnet-5",
        )

    assert exc_info.value.retryable is True
    assert create.await_count == 2  # docs/04 §4: 2 tentativas, não mais


async def test_count_tokens_retorna_input_tokens_da_resposta() -> None:
    provider = _provider_com_client_fake()

    total = await provider.count_tokens(
        system="sistema", messages=[LLMMessage(role="user", content="oi")], model="claude-sonnet-5"
    )

    assert total == 42
