"""Conversa — `docs/03-modelo-de-dados.md` §2."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, UUIDPkMixin

_STATUSES = (
    "active",
    "awaiting_lead",
    "human_handoff",
    "scheduled",
    "disqualified",
    "closed",
    "opted_out",
)


class Conversation(UUIDPkMixin, TenantMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint(f"status IN {_STATUSES}", name="status_valido"),
        Index("ix_conversations_tenant_id_status", "tenant_id", "status"),
        Index(
            "ix_conversations_tenant_id_next_followup_at",
            "tenant_id",
            "next_followup_at",
            postgresql_where=text("next_followup_at IS NOT NULL"),
        ),
        Index("ix_conversations_tenant_id_contact_id", "tenant_id", "contact_id"),
    )

    contact_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    state: Mapped[str] = mapped_column(String, nullable=False)
    assigned_seller_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sellers.id"), nullable=True
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # `use_alter`: quebra o ciclo de FK com `messages` (que referencia esta
    # tabela via `conversation_id`) — a constraint é adicionada depois que
    # ambas as tabelas existem.
    summary_updated_at_message_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "messages.id",
            use_alter=True,
            name="fk_conversations_summary_updated_at_message_id",
        ),
        nullable=True,
    )
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_outbound_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    within_24h_window_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    followup_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_followup_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_cost_cents: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=0)
