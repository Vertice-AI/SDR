"""Base de conhecimento — `docs/03-modelo-de-dados.md` §4.

Dimensão do embedding fixa em 1024, igual ao default de
`Settings.embedding_dimensions` (`app/config.py`) — mudar de modelo de
embedding com dimensão diferente exige nova migração.
"""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, Boolean, CheckConstraint, Computed, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPkMixin

_EMBEDDING_DIM = 1024


class KnowledgeDocument(UUIDPkMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('upload', 'url', 'manual', 'faq')", name="source_type_valido"
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'failed')", name="status_valido"
        ),
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class KnowledgeChunk(UUIDPkMixin, TenantMixin, Base):
    __tablename__ = "knowledge_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('portuguese', immutable_unaccent(content))", persisted=True),
        nullable=True,
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(_EMBEDDING_DIM), nullable=True)
    chunk_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )


class FaqEntry(UUIDPkMixin, TenantMixin, TimestampMixin, Base):
    """Perguntas e respostas curadas, com prioridade sobre o RAG."""

    __tablename__ = "faq_entries"

    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    variations: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(_EMBEDDING_DIM), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
