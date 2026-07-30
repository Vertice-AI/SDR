"""Adapter Meta Cloud API (produção) — `docs/06-integracao-whatsapp.md` §2.

Diferente do Evolution, aqui a validação de segurança é dupla: verificação
do `hub.challenge` na assinatura da instância (`GET`) e HMAC-SHA256 do corpo
cru com `app_secret` em todo evento (`POST`) — nunca confiar só na origem
do IP.
"""

import hashlib
import hmac
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.channels.base import Capability, ContentType, InboundMessage, SentMessage
from app.channels.http_errors import raise_external_service_error
from app.core.errors import ChannelCapabilityUnavailableError


def _extract_interactive_text(message: Mapping[str, Any]) -> str | None:
    interactive = message.get("interactive") or {}
    button_reply = interactive.get("button_reply")
    if button_reply:
        text = button_reply.get("title")
        return text if isinstance(text, str) else None
    list_reply = interactive.get("list_reply")
    if list_reply:
        text = list_reply.get("title")
        return text if isinstance(text, str) else None
    button = message.get("button") or {}
    text = button.get("text")
    return text if isinstance(text, str) else None


def _parse_message_content(
    message: Mapping[str, Any],
) -> tuple[ContentType, str | None, str | None, str | None]:
    """Retorna `(content_type, text, media_id, media_mime)`."""
    tipo = message.get("type")
    if tipo == "text":
        return "text", message.get("text", {}).get("body"), None, None
    if tipo == "image":
        img = message.get("image", {})
        return "image", img.get("caption"), img.get("id"), img.get("mime_type")
    if tipo == "audio":
        audio = message.get("audio", {})
        return "audio", None, audio.get("id"), audio.get("mime_type")
    if tipo == "document":
        doc = message.get("document", {})
        return "document", doc.get("caption"), doc.get("id"), doc.get("mime_type")
    if tipo == "sticker":
        sticker = message.get("sticker", {})
        return "sticker", None, sticker.get("id"), sticker.get("mime_type")
    if tipo == "location":
        return "location", None, None, None
    if tipo in ("interactive", "button"):
        return "interactive", _extract_interactive_text(message), None, None
    return "unknown", None, None, None


class MetaCloudAdapter:
    provider = "meta_cloud"

    def __init__(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        app_secret: str,
        webhook_verify_token: str,
        capabilities: Mapping[str, bool],
        api_version: str = "v21.0",
    ) -> None:
        self._phone_number_id = phone_number_id
        self._app_secret = app_secret
        self._webhook_verify_token = webhook_verify_token
        self._capabilities = capabilities
        self._client = httpx.AsyncClient(
            base_url=f"https://graph.facebook.com/{api_version}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def verify_webhook(
        self, params: Mapping[str, str], headers: Mapping[str, str], body: bytes
    ) -> bool:
        """Cobre os dois mecanismos de verificação da Meta: o desafio da `GET`
        de configuração do webhook e a assinatura HMAC de toda `POST` de evento."""
        if "hub.mode" in params or "hub.verify_token" in params:
            return params.get("hub.mode") == "subscribe" and hmac.compare_digest(
                params.get("hub.verify_token", ""), self._webhook_verify_token
            )

        assinatura_recebida = headers.get("x-hub-signature-256", "")
        if not assinatura_recebida.startswith("sha256="):
            return False
        esperada = hmac.new(self._app_secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(assinatura_recebida.removeprefix("sha256="), esperada)

    async def parse_inbound(self, payload: dict[str, Any]) -> list[InboundMessage]:
        mensagens: list[InboundMessage] = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                nomes_por_wa_id = {
                    contato["wa_id"]: contato.get("profile", {}).get("name")
                    for contato in value.get("contacts", [])
                }
                display_phone = value.get("metadata", {}).get("display_phone_number", "")

                for msg in value.get("messages", []):
                    content_type, text, media_id, media_mime = _parse_message_content(msg)
                    timestamp_bruto = msg.get("timestamp")
                    timestamp = (
                        datetime.fromtimestamp(int(timestamp_bruto), tz=UTC)
                        if timestamp_bruto
                        else datetime.now(UTC)
                    )
                    contexto = msg.get("context") or {}
                    from_wa_id = msg.get("from", "")

                    mensagens.append(
                        InboundMessage(
                            provider_message_id=msg.get("id", ""),
                            from_phone=f"+{from_wa_id}",
                            to_phone=f"+{display_phone}" if display_phone else "",
                            profile_name=nomes_por_wa_id.get(from_wa_id),
                            content_type=content_type,
                            text=text,
                            media_id=media_id,
                            media_mime=media_mime,
                            timestamp=timestamp,
                            context_message_id=contexto.get("id"),
                            referral=msg.get("referral"),
                            raw=msg,
                        )
                    )
        return mensagens

    def parse_statuses(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Não faz parte do `ChannelAdapter` — usado pelo worker (2.5) para
        atualizar `messages.provider_status`. Só a Meta manda status de entrega."""
        statuses: list[dict[str, Any]] = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for status in value.get("statuses", []):
                    statuses.append(
                        {
                            "provider_message_id": status.get("id"),
                            "status": status.get("status"),
                            "timestamp": status.get("timestamp"),
                            "errors": status.get("errors"),
                        }
                    )
        return statuses

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
    )
    async def send_text(self, to: str, text: str) -> SentMessage:
        return await self._post_messages(
            to, {"type": "text", "text": {"body": text}}, erro_contexto="texto"
        )

    async def send_typing(self, to: str, on: bool) -> None:
        # O indicador de digitando da Cloud API (`typing_indicator`) exige o
        # id da mensagem recebida sendo respondida, não só o telefone — não
        # cabe no contrato genérico de `ChannelAdapter.send_typing(to, on)`.
        # Configurar `channels.capabilities.typing = false` para este canal.
        raise ChannelCapabilityUnavailableError(
            "Indicador de digitando da Meta Cloud API precisa do id da mensagem "
            "recebida — não suportado por este adapter com a assinatura genérica."
        )

    async def send_template(self, to: str, name: str, params: list[str]) -> SentMessage:
        components = (
            [{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}]
            if params
            else []
        )
        return await self._post_messages(
            to,
            {
                "type": "template",
                "template": {"name": name, "language": {"code": "pt_BR"}, "components": components},
            },
            erro_contexto=f"template '{name}'",
        )

    async def send_buttons(self, to: str, text: str, buttons: list[str]) -> SentMessage:
        if len(buttons) > 3:
            raise ChannelCapabilityUnavailableError(
                "Meta Cloud API aceita no máximo 3 botões de resposta rápida."
            )
        return await self._post_messages(
            to,
            {
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": text},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": str(i), "title": botao}}
                            for i, botao in enumerate(buttons)
                        ]
                    },
                },
            },
            erro_contexto="botões",
        )

    async def _post_messages(
        self, to: str, corpo_extra: dict[str, Any], *, erro_contexto: str
    ) -> SentMessage:
        try:
            response = await self._client.post(
                f"/{self._phone_number_id}/messages",
                json={"messaging_product": "whatsapp", "to": to.lstrip("+"), **corpo_extra},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise_external_service_error(
                f"Falha ao enviar {erro_contexto} via Meta Cloud API para {to}", exc
            )

        corpo = response.json()
        mensagens_enviadas = corpo.get("messages") or [{}]
        provider_message_id = mensagens_enviadas[0].get("id", "")
        return SentMessage(
            provider_message_id=provider_message_id, to_phone=to, timestamp=datetime.now(UTC)
        )

    async def download_media(self, media_id: str) -> bytes:
        try:
            info_response = await self._client.get(f"/{media_id}")
            info_response.raise_for_status()
            media_url = info_response.json()["url"]
            media_response = await self._client.get(media_url)
            media_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise_external_service_error(
                f"Falha ao baixar mídia {media_id} via Meta Cloud API", exc
            )
        return media_response.content

    async def mark_read(self, provider_message_id: str) -> None:
        try:
            response = await self._client.post(
                f"/{self._phone_number_id}/messages",
                json={
                    "messaging_product": "whatsapp",
                    "status": "read",
                    "message_id": provider_message_id,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise_external_service_error(
                f"Falha ao marcar mensagem {provider_message_id} como lida", exc
            )

    def supports(self, capability: Capability) -> bool:
        return bool(self._capabilities.get(capability, False))
