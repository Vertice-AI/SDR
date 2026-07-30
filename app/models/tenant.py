"""Tenancy e configuração — `docs/03-modelo-de-dados.md` §1."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPkMixin


class Tenant(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'paused', 'churned')", name="status_valido"),
    )

    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    timezone: Mapped[str] = mapped_column(String, nullable=False, default="America/Sao_Paulo")
    plan: Mapped[str | None] = mapped_column(String, nullable=True)
    monthly_conversation_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TenantConfig(UUIDPkMixin, TenantMixin, Base):
    """Configuração viva do agente, versionada para permitir rollback de prompt."""

    __tablename__ = "tenant_configs"
    __table_args__ = (
        CheckConstraint(
            "tone IN ('consultivo', 'direto', 'informal', 'formal')", name="tone_valido"
        ),
        CheckConstraint(
            "out_of_hours_behavior IN ('responder', 'avisar_e_responder', 'so_avisar')",
            name="out_of_hours_behavior_valido",
        ),
        CheckConstraint(
            "seller_assignment_mode IN ('single', 'round_robin', 'by_rule')",
            name="seller_assignment_mode_valido",
        ),
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    company_description: Mapped[str] = mapped_column(Text, nullable=False)
    offer_description: Mapped[str] = mapped_column(Text, nullable=False)
    icp_description: Mapped[str] = mapped_column(Text, nullable=False)
    tone: Mapped[str] = mapped_column(String, nullable=False, default="consultivo")
    language: Mapped[str] = mapped_column(String, nullable=False, default="pt-BR")
    custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    forbidden_topics: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    qualification_fields: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    disqualification_rules: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    handoff_rules: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    followup_cadence: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    max_followups: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    debounce_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    business_hours: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    out_of_hours_behavior: Mapped[str] = mapped_column(
        String, nullable=False, default="avisar_e_responder"
    )
    scheduling_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=45)
    classification_bands: Mapped[dict[str, int]] = mapped_column(
        JSONB, nullable=False, default=lambda: {"hot": 70, "warm": 45, "cold": 20}
    )
    handoff_sla_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    handoff_transition_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    seller_assignment_mode: Mapped[str] = mapped_column(String, nullable=False, default="single")
    enable_vision: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enable_audio_transcription: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
