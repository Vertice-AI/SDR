"""Escalonamento para humano — `docs/03-modelo-de-dados.md` §3."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, UUIDPkMixin


class Handoff(UUIDPkMixin, TenantMixin, Base):
    __tablename__ = "handoffs"
    __table_args__ = (
        CheckConstraint(
            "reason IN "
            "('lead_pediu', 'sem_resposta_na_base', 'irritacao', 'tema_sensivel', "
            "'lead_quente', 'manual', 'erro_tecnico')",
            name="reason_valido",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_message_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("messages.id"), nullable=True
    )
    notified_channels: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    assumed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    assumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
