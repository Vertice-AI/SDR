"""Qualificação de uma conversa — `docs/03-modelo-de-dados.md` §3."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, UUIDPkMixin


class Qualification(UUIDPkMixin, TenantMixin, Base):
    __tablename__ = "qualifications"
    __table_args__ = (
        UniqueConstraint("conversation_id", name="uq_qualifications_conversation_id"),
        CheckConstraint(
            "classification IN ('hot', 'warm', 'cold', 'disqualified')",
            name="classification_valido",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    answers: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    classification: Mapped[str | None] = mapped_column(Text, nullable=True)
    disqualification_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
