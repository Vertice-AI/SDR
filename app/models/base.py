"""Base declarativa e mixins comuns a todo model SQLAlchemy.

Convenções de `docs/03-modelo-de-dados.md`: PK `uuid` gerada no banco,
timestamps `timestamptz` e `tenant_id` obrigatório em toda tabela de negócio
(`CLAUDE.md` §4.1) — RLS no Postgres é a segunda linha de defesa, não a única.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, MetaData, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPkMixin:
    """PK `id uuid` com default `gen_random_uuid()` (extensão `pgcrypto`)."""

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TenantMixin:
    """Toda tabela de negócio referencia o tenant dono da linha.

    Índice sempre começa por `tenant_id` (`docs/03` — convenções), e a
    política de RLS (`docs/03` §6) filtra por essa mesma coluna.
    """

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
