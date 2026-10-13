"""Extract staging and semantic embeddings (Postgres / pgvector)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.db.base import Base


class Vector(UserDefinedType):
    """PostgreSQL ``vector`` type (pgvector). Dimension is not enforced here."""

    cache_ok = True

    def get_col_spec(self, **_kw: Any) -> str:
        return "vector"

    def bind_processor(self, dialect):
        def process(value):
            return value

        return process

    def result_processor(self, dialect, coltype):
        def process(value):
            return value

        return process


class ExtractStaging(Base):
    __tablename__ = "extract_staging"

    batch_id: Mapped[str] = mapped_column(Text, primary_key=True)
    uid: Mapped[str] = mapped_column(Text, primary_key=True)
    table_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    user_email: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=True
    )


class SemanticEmbedding(Base):
    """Ancillary embeddings store. Requires PostgreSQL pgvector extension.

    HNSW index and ``vector(dim)`` DDL are managed by Alembic / init_schema;
    the ORM column uses an untyped ``vector`` for portability of metadata.
    """

    __tablename__ = "semantic_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    object_type: Mapped[str] = mapped_column(Text, nullable=False)
    object_id: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_kind: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Any | None] = mapped_column(Vector)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, server_default="{}"
    )
    user_email: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=True
    )
