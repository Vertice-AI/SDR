"""Consentimento LGPD — `docs/03-modelo-de-dados.md` §5."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, UUIDPkMixin


class Consent(UUIDPkMixin, TenantMixin, Base):
    __tablename__ = "consents"
    __table_args__ = (
        CheckConstraint("type IN ('whatsapp_contact', 'data_processing')", name="type_valido"),
        CheckConstraint(
            "source IN ('optin_form', 'inbound_message', 'imported_list')", name="source_valido"
        ),
    )

    contact_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String, nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    evidence: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
