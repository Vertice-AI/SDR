"""Vendedor que recebe as reuniões — `docs/03-modelo-de-dados.md` §1."""

import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPkMixin
from app.models.types import EncryptedString


class Seller(UUIDPkMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "sellers"
    __table_args__ = (
        CheckConstraint("calendar_provider IN ('google', 'none')", name="calendar_provider_valido"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    calendar_provider: Mapped[str] = mapped_column(String, nullable=False, default="none")
    calendar_credentials_encrypted: Mapped[str | None] = mapped_column(
        EncryptedString, nullable=True
    )
    calendar_id: Mapped[str] = mapped_column(String, nullable=False, default="primary")
    timezone: Mapped[str] = mapped_column(String, nullable=False, default="America/Sao_Paulo")
    availability_rules: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    round_robin_weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
