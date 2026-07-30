"""Parsing de payload do EvolutionAdapter com fixtures — sem rede, sem
instância real (`docs/06` §3, roadmap 2.2)."""

import httpx
import pytest

from app.channels.evolution import EvolutionAdapter, map_message_status, normalize_phone
from app.core.errors import ChannelCapabilityUnavailableError


def _make_adapter(**kwargs: object) -> EvolutionAdapter:
    defaults: dict[str, object] = {
        "base_url": "http://localhost:8080",
        "api_key": "instance-key",
        "instance_name": "tenant-demo",
        "webhook_verify_token": "webhook-secret",
        "capabilities": {"typing": True, "buttons": False},
    }
    defaults.update(kwargs)
    return EvolutionAdapter(**defaults)  # type: ignore[arg-type]


def test_normalize_phone_remove_sufixo_whatsapp() -> None:
    assert normalize_phone("5511999990000@s.whatsapp.net") == "+5511999990000"
    assert normalize_phone("5511999990000:12@s.whatsapp.net") == "+5511999990000"


def test_map_message_status() -> None:
    assert map_message_status(3) == "delivered"
    assert map_message_status(4) == "read"
    assert map_message_status(0) == "failed"
    assert map_message_status(99) == "sent"


async def test_verify_webhook_aceita_apikey_correta() -> None:
    adapter = _make_adapter()
    ok = await adapter.verify_webhook({}, {"apikey": "webhook-secret"}, b"{}")
    assert ok is True


async def test_verify_webhook_rejeita_apikey_errada() -> None:
    adapter = _make_adapter()
    ok = await adapter.verify_webhook({}, {"apikey": "errada"}, b"{}")
    assert ok is False


async def test_parse_inbound_mensagem_de_texto_simples() -> None:
    adapter = _make_adapter()
    payload = {
        "event": "messages.upsert",
        "instance": "tenant-demo",
        "data": {
            "key": {
                "remoteJid": "5511988887777@s.whatsapp.net",
                "fromMe": False,
                "id": "3EB0AAA111",
            },
            "pushName": "Maria",
            "message": {"conversation": "oi, vi o anúncio de vocês"},
            "messageType": "conversation",
            "messageTimestamp": 1735689600,
        },
    }

    mensagens = await adapter.parse_inbound(payload)

    assert len(mensagens) == 1
    msg = mensagens[0]
    assert msg.provider_message_id == "3EB0AAA111"
    assert msg.from_phone == "+5511988887777"
    assert msg.profile_name == "Maria"
    assert msg.content_type == "text"
    assert msg.text == "oi, vi o anúncio de vocês"


async def test_parse_inbound_extended_text_com_resposta() -> None:
    adapter = _make_adapter()
    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {"remoteJid": "5511988887777@s.whatsapp.net", "fromMe": False, "id": "ID2"},
            "pushName": "Maria",
            "message": {
                "extendedTextMessage": {
                    "text": "quanto custa?",
                    "contextInfo": {"stanzaId": "ID1"},
                }
            },
            "messageType": "extendedTextMessage",
            "messageTimestamp": 1735689600,
        },
    }

    mensagens = await adapter.parse_inbound(payload)

    assert mensagens[0].text == "quanto custa?"
    assert mensagens[0].context_message_id == "ID1"


async def test_parse_inbound_ignora_mensagem_propria() -> None:
    adapter = _make_adapter()
    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {"remoteJid": "5511988887777@s.whatsapp.net", "fromMe": True, "id": "ID3"},
            "message": {"conversation": "resposta nossa"},
            "messageTimestamp": 1735689600,
        },
    }

    assert await adapter.parse_inbound(payload) == []


async def test_parse_inbound_ignora_mensagem_de_grupo() -> None:
    adapter = _make_adapter()
    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {"remoteJid": "123456-group@g.us", "fromMe": False, "id": "ID4"},
            "message": {"conversation": "mensagem de grupo"},
            "messageTimestamp": 1735689600,
        },
    }

    assert await adapter.parse_inbound(payload) == []


async def test_parse_inbound_ignora_evento_que_nao_e_mensagem() -> None:
    adapter = _make_adapter()
    payload = {"event": "connection.update", "data": {"state": "open"}}

    assert await adapter.parse_inbound(payload) == []


async def test_send_text_chama_endpoint_correto_e_retorna_sent_message() -> None:
    capturado: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        capturado["url"] = str(request.url)
        capturado["json"] = request.read()
        return httpx.Response(200, json={"key": {"id": "OUT123"}})

    adapter = _make_adapter()
    adapter._client = httpx.AsyncClient(
        base_url="http://localhost:8080",
        transport=httpx.MockTransport(handler),
    )

    resultado = await adapter.send_text("+5511988887777", "olá!")

    assert resultado.provider_message_id == "OUT123"
    assert resultado.to_phone == "+5511988887777"
    assert "/message/sendText/tenant-demo" in str(capturado["url"])


async def test_send_template_nao_suportado_pela_evolution() -> None:
    adapter = _make_adapter()
    with pytest.raises(ChannelCapabilityUnavailableError):
        await adapter.send_template("+5511988887777", "qualquer", [])


def test_supports_le_capacidades_declaradas() -> None:
    adapter = _make_adapter(capabilities={"typing": True, "buttons": False})
    assert adapter.supports("typing") is True
    assert adapter.supports("buttons") is False
    assert adapter.supports("templates") is False
