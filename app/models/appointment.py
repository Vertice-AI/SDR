"""Agendamento — `docs/03-modelo-de-dados.md` §3."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, UUIDPkMixin


class Appointment(UUIDPkMixin, TenantMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        Index("ix_appointments_tenant_id_starts_at", "tenant_id", "starts_at"),
        Index("ix_appointments_seller_id_starts_at", "seller_id", "starts_at"),
        CheckConstraint(
            "status IN ('scheduled', 'rescheduled', 'cancelled', 'completed', 'no_show')",
            name="status_valido",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )
    seller_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sellers.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="scheduled")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String, nullable=False, default="America/Sao_Paulo")
    meeting_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    calendar_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    reminder_24h_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_1h_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rescheduled_from_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("appointments.id"), nullable=True
    )
