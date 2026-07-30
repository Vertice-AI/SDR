"""Log de exportação para CRM — `docs/03-modelo-de-dados.md` §5."""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPkMixin


class CrmSyncLog(UUIDPkMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "crm_sync_log"
    __table_args__ = (CheckConstraint("status IN ('success', 'failed')", name="status_valido"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String, nullable=False)
    operation: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    request: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    response: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
