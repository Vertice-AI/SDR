"""Leads — `docs/03-modelo-de-dados.md` §2."""

from datetime import datetime

from sqlalchemy import ARRAY, CheckConstraint, DateTime, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, UUIDPkMixin


class Contact(UUIDPkMixin, TenantMixin, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "phone_e164", name="uq_contacts_tenant_id_phone_e164"),
        CheckConstraint(
            "source IN ('anuncio_meta', 'site', 'indicacao', 'lista', 'desconhecido')",
            name="source_valido",
        ),
    )

    phone_e164: Mapped[str] = mapped_column(String, nullable=False)
    phone_hash: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    company: Mapped[str | None] = mapped_column(String, nullable=True)
    role_title: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default="desconhecido")
    source_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_contact_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    crm_external_id: Mapped[str | None] = mapped_column(String, nullable=True)
