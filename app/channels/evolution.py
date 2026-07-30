"""Adapter Evolution API (dev/homologação) — `docs/06-integracao-whatsapp.md` §3.

Self-hosted, baseada em Baileys (WhatsApp Web não oficial). Os nomes de campo
do payload seguem o formato conhecido publicamente do Baileys/Evolution API
v2. **Ainda não foi validado contra uma instância real conectada a um
número** (tarefa 2.8 do roadmap, bloqueada até haver um número disponível) —
ajustar aqui se a instância real divergir no primeiro teste ponta a ponta.

Escopo desta v1 (item 2.2 do roadmap): parse de `messages.upsert`, envio de
texto e indicador de "digitando". Evolution não tem template (`docs/06` §3)
e mídia/botões ficam para quando viram necessários (Fase 6).
"""

import hmac
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.channels.base import Capability, ContentType, InboundMessage, SentMessage
from app.channels.http_errors import raise_external_service_error
from app.core.errors import ChannelCapabilityUnavailableError

_STATUS_MAP: dict[int, str] = {
    0: "failed",  # ERROR
    1: "sent",  # PENDING
    2: "sent",  # SERVER_ACK
    3: "delivered",  # DELIVERY_ACK
    4: "read",  # READ
    5: "read",  # PLAYED
}


def normalize_phone(remote_jid: str) -> str:
    """`5511999999999@s.whatsapp.net` -> `+5511999999999`."""
    numero = remote_jid.split("@", 1)[0].split(":", 1)[0]
    return f"+{numero}"


def map_message_status(status_code: int) -> str:
    """Status numérico do Baileys -> vocabulário de `messages.provider_status`."""
    return _STATUS_MAP.get(status_code, "sent")


def _parse_message_content(
    message: Mapping[str, Any],
) -> tuple[ContentType, str | None, str | None, str | None, str | None]:
    """Retorna `(content_type, text, media_id, media_mime, context_message_id)`.

    `contextInfo` (resposta a uma mensagem anterior) vem aninhado dentro do
    subtipo da mensagem no Baileys (ex.: `extendedTextMessage.contextInfo`),
    nunca no nível raiz de `message`.
    """
    if "conversation" in message:
        return "text", message["conversation"], None, None, None
    if "extendedTextMessage" in message:
        sub = message["extendedTextMessage"]
        context_id = (sub.get("contextInfo") or {}).get("stanzaId")
        return "text", sub.get("text"), None, None, context_id
    if "imageMessage" in message:
        img = message["imageMessage"]
        context_id = (img.get("contextInfo") or {}).get("stanzaId")
        return "image", img.get("caption"), img.get("url"), img.get("mimetype"), context_id
    if "audioMessage" in message:
        audio = message["audioMessage"]
        context_id = (audio.get("contextInfo") or {}).get("stanzaId")
        return "audio", None, audio.get("url"), audio.get("mimetype"), context_id
    if "documentMessage" in message:
        doc = message["documentMessage"]
        context_id = (doc.get("contextInfo") or {}).get("stanzaId")
        return "document", doc.get("caption"), doc.get("url"), doc.get("mimetype"), context_id
    if "locationMessage" in message:
        return "location", None, None, None, None
    if "stickerMessage" in message:
        return "sticker", None, None, None, None
    return "unknown", None, None, None, None


class EvolutionAdapter:
    provider = "evolution"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        instance_name: str,
        webhook_verify_token: str,
        capabilities: Mapping[str, bool],
    ) -> None:
        self._instance_name = instance_name
        self._webhook_verify_token = webhook_verify_token
        self._capabilities = capabilities
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"apikey": api_key},
            timeout=10.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def verify_webhook(
        self, params: Mapping[str, str], headers: Mapping[str, str], body: bytes
    ) -> bool:
        recebida = headers.get("apikey", "")
        return hmac.compare_digest(recebida, self._webhook_verify_token)

    async def parse_inbound(self, payload: dict[str, Any]) -> list[InboundMessage]:
        if payload.get("event", "").lower() != "messages.upsert":
            return []

        itens_brutos = payload.get("data")
        itens = itens_brutos if isinstance(itens_brutos, list) else [itens_brutos]

        mensagens: list[InboundMessage] = []
        for item in itens:
            if not item:
                continue

            key = item.get("key") or {}
            if key.get("fromMe"):
                continue  # eco da própria mensagem enviada por nós

            remote_jid = key.get("remoteJid", "")
            if not remote_jid or remote_jid.endswith("@g.us"):
                continue  # grupo — fora do escopo do produto (v1)

            message = item.get("message") or {}
            content_type, text, media_id, media_mime, context_message_id = _parse_message_content(
                message
            )

            timestamp_bruto = item.get("messageTimestamp")
            timestamp = (
                datetime.fromtimestamp(int(timestamp_bruto), tz=UTC)
                if timestamp_bruto
                else datetime.now(UTC)
            )

            mensagens.append(
                InboundMessage(
                    provider_message_id=key.get("id", ""),
                    from_phone=normalize_phone(remote_jid),
                    to_phone=payload.get("instance", self._instance_name),
                    profile_name=item.get("pushName"),
                    content_type=content_type,
                    text=text,
                    media_id=media_id,
                    media_mime=media_mime,
                    timestamp=timestamp,
                    context_message_id=context_message_id,
                    referral=None,
                    raw=item,
                )
            )
        return mensagens

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
    )
    async def send_text(self, to: str, text: str) -> SentMessage:
        try:
            response = await self._client.post(
                f"/message/sendText/{self._instance_name}",
                json={"number": to.lstrip("+"), "text": text},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise_external_service_error(f"Falha ao enviar texto via Evolution para {to}", exc)

        corpo = response.json()
        provider_message_id = (corpo.get("key") or {}).get("id", "")
        return SentMessage(
            provider_message_id=provider_message_id, to_phone=to, timestamp=datetime.now(UTC)
        )

    async def send_typing(self, to: str, on: bool) -> None:
        try:
            response = await self._client.post(
                f"/chat/sendPresence/{self._instance_name}",
                json={"number": to.lstrip("+"), "presence": "composing" if on else "paused"},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise_external_service_error(f"Falha ao enviar presença via Evolution para {to}", exc)

    async def send_template(self, to: str, name: str, params: list[str]) -> SentMessage:
        raise ChannelCapabilityUnavailableError(
            "Evolution API não suporta template — use send_text ou espere a janela de contato."
        )

    async def send_buttons(self, to: str, text: str, buttons: list[str]) -> SentMessage:
        raise ChannelCapabilityUnavailableError(
            "Botões via Evolution ainda não implementados nesta v1 (fora do escopo da tarefa 2.2)."
        )

    async def download_media(self, media_id: str) -> bytes:
        raise ChannelCapabilityUnavailableError(
            "Download de mídia via Evolution ainda não implementado nesta v1 "
            "(entra na Fase 6, transcrição de áudio)."
        )

    async def mark_read(self, provider_message_id: str) -> None:
        raise ChannelCapabilityUnavailableError(
            "Confirmação de leitura via Evolution ainda não implementada nesta v1."
        )

    def supports(self, capability: Capability) -> bool:
        return bool(self._capabilities.get(capability, False))
