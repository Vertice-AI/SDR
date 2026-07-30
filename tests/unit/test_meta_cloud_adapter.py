"""Parsing e assinatura do MetaCloudAdapter com fixtures — sem rede, sem
número real conectado (`docs/06` §2)."""

import hashlib
import hmac

import httpx
import pytest

from app.channels.meta_cloud import MetaCloudAdapter
from app.core.errors import ChannelCapabilityUnavailableError

_APP_SECRET = "app-secret-de-teste"
_VERIFY_TOKEN = "verify-token-de-teste"


def _make_adapter(**kwargs: object) -> MetaCloudAdapter:
    defaults: dict[str, object] = {
        "access_token": "token-permanente",
        "phone_number_id": "1234567890",
        "app_secret": _APP_SECRET,
        "webhook_verify_token": _VERIFY_TOKEN,
        "capabilities": {"templates": True, "buttons": True},
    }
    defaults.update(kwargs)
    return MetaCloudAdapter(**defaults)  # type: ignore[arg-type]


async def test_verify_webhook_desafio_get_aceita_token_correto() -> None:
    adapter = _make_adapter()
    ok = await adapter.verify_webhook(
        {"hub.mode": "subscribe", "hub.verify_token": _VERIFY_TOKEN, "hub.challenge": "123"},
        {},
        b"",
    )
    assert ok is True


async def test_verify_webhook_desafio_get_rejeita_token_errado() -> None:
    adapter = _make_adapter()
    ok = await adapter.verify_webhook(
        {"hub.mode": "subscribe", "hub.verify_token": "errado", "hub.challenge": "123"}, {}, b""
    )
    assert ok is False


async def test_verify_webhook_post_aceita_assinatura_valida() -> None:
    adapter = _make_adapter()
    body = b'{"object": "whatsapp_business_account"}'
    assinatura = hmac.new(_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()

    ok = await adapter.verify_webhook({}, {"x-hub-signature-256": f"sha256={assinatura}"}, body)

    assert ok is True


async def test_verify_webhook_post_rejeita_assinatura_invalida() -> None:
    adapter = _make_adapter()
    body = b'{"object": "whatsapp_business_account"}'

    ok = await adapter.verify_webhook({}, {"x-hub-signature-256": "sha256=errada"}, body)

    assert ok is False


async def test_verify_webhook_post_rejeita_sem_header() -> None:
    adapter = _make_adapter()
    assert await adapter.verify_webhook({}, {}, b"{}") is False


async def test_parse_inbound_mensagem_de_texto_com_nome_do_contato() -> None:
    adapter = _make_adapter()
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550001111",
                                "phone_number_id": "1234567890",
                            },
                            "contacts": [{"profile": {"name": "Maria"}, "wa_id": "5511988887777"}],
                            "messages": [
                                {
                                    "from": "5511988887777",
                                    "id": "wamid.AAA",
                                    "timestamp": "1735689600",
                                    "type": "text",
                                    "text": {"body": "oi, quanto custa?"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    mensagens = await adapter.parse_inbound(payload)

    assert len(mensagens) == 1
    msg = mensagens[0]
    assert msg.provider_message_id == "wamid.AAA"
    assert msg.from_phone == "+5511988887777"
    assert msg.to_phone == "+15550001111"
    assert msg.profile_name == "Maria"
    assert msg.content_type == "text"
    assert msg.text == "oi, quanto custa?"


async def test_parse_inbound_com_contexto_e_referral() -> None:
    adapter = _make_adapter()
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"display_phone_number": "15550001111"},
                            "contacts": [],
                            "messages": [
                                {
                                    "from": "5511988887777",
                                    "id": "wamid.BBB",
                                    "timestamp": "1735689600",
                                    "type": "text",
                                    "text": {"body": "quero saber mais"},
                                    "context": {"id": "wamid.AAA"},
                                    "referral": {
                                        "source_id": "12345",
                                        "ctwa_clid": "abc",
                                        "headline": "Anúncio X",
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }

    mensagens = await adapter.parse_inbound(payload)

    assert mensagens[0].context_message_id == "wamid.AAA"
    assert mensagens[0].referral == {
        "source_id": "12345",
        "ctwa_clid": "abc",
        "headline": "Anúncio X",
    }


async def test_parse_inbound_imagem_com_legenda() -> None:
    adapter = _make_adapter()
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"display_phone_number": "15550001111"},
                            "messages": [
                                {
                                    "from": "5511988887777",
                                    "id": "wamid.CCC",
                                    "timestamp": "1735689600",
                                    "type": "image",
                                    "image": {
                                        "id": "media123",
                                        "mime_type": "image/jpeg",
                                        "caption": "olha isso",
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }

    mensagens = await adapter.parse_inbound(payload)

    assert mensagens[0].content_type == "image"
    assert mensagens[0].text == "olha isso"
    assert mensagens[0].media_id == "media123"
    assert mensagens[0].media_mime == "image/jpeg"


def test_parse_statuses_extrai_status_de_entrega() -> None:
    adapter = _make_adapter()
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {
                                    "id": "wamid.AAA",
                                    "status": "delivered",
                                    "timestamp": "1735689600",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    statuses = adapter.parse_statuses(payload)

    assert statuses == [
        {
            "provider_message_id": "wamid.AAA",
            "status": "delivered",
            "timestamp": "1735689600",
            "errors": None,
        }
    ]


async def test_send_text_chama_endpoint_correto() -> None:
    capturado: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        capturado["url"] = str(request.url)
        capturado["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"messages": [{"id": "wamid.OUT"}]})

    adapter = _make_adapter()
    adapter._client = httpx.AsyncClient(
        base_url="https://graph.facebook.com/v21.0",
        headers={"Authorization": "Bearer token-permanente"},
        transport=httpx.MockTransport(handler),
    )

    resultado = await adapter.send_text("+5511988887777", "olá!")

    assert resultado.provider_message_id == "wamid.OUT"
    assert "1234567890/messages" in str(capturado["url"])
    assert capturado["auth"] == "Bearer token-permanente"


async def test_send_typing_nao_suportado() -> None:
    adapter = _make_adapter()
    with pytest.raises(ChannelCapabilityUnavailableError):
        await adapter.send_typing("+5511988887777", True)


async def test_send_buttons_rejeita_mais_de_tres_botoes() -> None:
    adapter = _make_adapter()
    with pytest.raises(ChannelCapabilityUnavailableError):
        await adapter.send_buttons("+5511988887777", "escolha", ["a", "b", "c", "d"])


def test_supports_le_capacidades_declaradas() -> None:
    adapter = _make_adapter(capabilities={"templates": True, "buttons": False})
    assert adapter.supports("templates") is True
    assert adapter.supports("buttons") is False
