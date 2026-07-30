"""Mensagens e templates HSM — `docs/03-modelo-de-dados.md` §2."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, UUIDPkMixin


class Message(UUIDPkMixin, TenantMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider_message_id",
            name="uq_messages_tenant_id_provider_message_id",
        ),
        Index("ix_messages_conversation_id_created_at", "conversation_id", "created_at"),
        CheckConstraint("direction IN ('inbound', 'outbound')", name="direction_valido"),
        CheckConstraint("sender_type IN ('lead', 'agent', 'human')", name="sender_type_valido"),
        CheckConstraint(
            "content_type IN "
            "('text', 'audio', 'image', 'document', 'location', 'template', 'system')",
            name="content_type_valido",
        ),
        CheckConstraint(
            "provider_status IN ('queued', 'sent', 'delivered', 'read', 'failed')",
            name="provider_status_valido",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String, nullable=False)
    sender_type: Mapped[str] = mapped_column(String, nullable=False)
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    content_type: Mapped[str] = mapped_column(String, nullable=False, default="text")
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_mime: Mapped[str | None] = mapped_column(String, nullable=True)
    transcription_confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    turn_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MessageTemplate(UUIDPkMixin, TenantMixin, Base):
    """Templates HSM aprovados na Meta. Só usados pelo `MetaCloudAdapter`."""

    __tablename__ = "message_templates"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "channel_id",
            "name",
            "language",
            name="uq_message_templates_tenant_id_channel_id_name_language",
        ),
        CheckConstraint(
            "category IN ('UTILITY', 'MARKETING', 'AUTHENTICATION')", name="category_valido"
        ),
        CheckConstraint(
            "purpose IN ('retomada_conversa', 'lembrete_24h', 'lembrete_1h', 'confirmacao')",
            name="purpose_valido",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'paused')", name="status_valido"
        ),
    )

    channel_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    language: Mapped[str] = mapped_column(String, nullable=False, default="pt_BR")
    category: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
