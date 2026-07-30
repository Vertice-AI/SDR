"""Interface comum a todo canal de WhatsApp — `docs/06-integracao-whatsapp.md` §1.

Duas implementações: `EvolutionAdapter` (dev/homologação) e `MetaCloudAdapter`
(produção). O resto do sistema fala só com `ChannelAdapter`, nunca com um
provedor específico — trocar de provedor é trocar a implementação injetada.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

ContentType = Literal[
    "text", "audio", "image", "document", "location", "interactive", "sticker", "unknown"
]

Capability = Literal[
    "templates", "buttons", "lists", "typing", "read_receipts", "audio_download", "media_upload"
]


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """Mensagem recebida, já normalizada — nenhum código fora do adapter lida
    com o formato bruto de um provedor."""

    provider_message_id: str
    from_phone: str  # E.164 sempre com "+"
    to_phone: str
    profile_name: str | None
    content_type: ContentType
    text: str | None
    media_id: str | None
    media_mime: str | None
    timestamp: datetime  # sempre UTC
    context_message_id: str | None  # resposta a mensagem anterior
    referral: dict[str, Any] | None  # click-to-WhatsApp: campanha, anúncio
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SentMessage:
    """Confirmação de envio, retornada pelo adapter."""

    provider_message_id: str
    to_phone: str
    timestamp: datetime


class ChannelAdapter(Protocol):
    provider: str

    async def verify_webhook(
        self, params: Mapping[str, str], headers: Mapping[str, str], body: bytes
    ) -> bool: ...

    async def parse_inbound(self, payload: dict[str, Any]) -> list[InboundMessage]: ...

    async def send_text(self, to: str, text: str) -> SentMessage: ...

    async def send_typing(self, to: str, on: bool) -> None: ...

    async def send_template(self, to: str, name: str, params: list[str]) -> SentMessage: ...

    async def send_buttons(self, to: str, text: str, buttons: list[str]) -> SentMessage: ...

    async def download_media(self, media_id: str) -> bytes: ...

    async def mark_read(self, provider_message_id: str) -> None: ...

    def supports(self, capability: Capability) -> bool: ...
