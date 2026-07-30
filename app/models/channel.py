"""Canal de WhatsApp — `docs/03-modelo-de-dados.md` §1."""

from sqlalchemy import CheckConstraint, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPkMixin
from app.models.types import EncryptedString


class Channel(UUIDPkMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "channels"
    __table_args__ = (
        UniqueConstraint("provider", "phone_number", name="uq_channels_provider_phone_number"),
        CheckConstraint("provider IN ('meta_cloud', 'evolution')", name="provider_valido"),
        CheckConstraint("status IN ('active', 'disconnected', 'banned')", name="status_valido"),
    )

    provider: Mapped[str] = mapped_column(String, nullable=False)
    phone_number: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    credentials_encrypted: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    webhook_verify_token_encrypted: Mapped[str | None] = mapped_column(
        EncryptedString, nullable=True
    )
    capabilities: Mapped[dict[str, bool]] = mapped_column(JSONB, nullable=False, default=dict)
