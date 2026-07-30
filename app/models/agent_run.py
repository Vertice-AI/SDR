"""Um registro por turno processado — `docs/03-modelo-de-dados.md` §5.

Base do custo e da depuração: uma linha por chamada ao loop de tool calling
(`app/agent/runtime.py`, Fase 3).
"""

import uuid

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPkMixin


class AgentRun(UUIDPkMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "agent_runs"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    turn_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_cents: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tools_called: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    state_before: Mapped[str | None] = mapped_column(String, nullable=True)
    state_after: Mapped[str | None] = mapped_column(String, nullable=True)
    guardrail_flags: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True)
