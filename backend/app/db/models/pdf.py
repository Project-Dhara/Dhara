"""PDF job / table / grouping models."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PdfJob(Base):
    __tablename__ = "pdf_jobs"

    job_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_email: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="done")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    grouping_status: Mapped[str | None] = mapped_column(Text, server_default="pending")
    stage: Mapped[str | None] = mapped_column(Text)
    percent: Mapped[int | None] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reviews: Mapped[dict[str, Any] | None] = mapped_column(JSONB, server_default="{}")
    deleted_table_ids: Mapped[Any | None] = mapped_column(JSONB, server_default="[]")
    pdf_bytes: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at_epoch: Mapped[float | None] = mapped_column(Float)
    pipeline_step: Mapped[int | None] = mapped_column(Integer)
    source_type: Mapped[str | None] = mapped_column(Text)
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=True
    )


class PdfTable(Base):
    __tablename__ = "pdf_tables"
    __table_args__ = (UniqueConstraint("job_id", "table_id", name="uq_pdf_tables_job_table"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        Text, ForeignKey("pdf_jobs.job_id", ondelete="CASCADE"), nullable=False
    )
    table_id: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)
    source_rows: Mapped[Any | None] = mapped_column(JSONB, server_default="[]")
    columns: Mapped[Any | None] = mapped_column(JSONB, server_default="[]")
    classification: Mapped[Any | None] = mapped_column(JSONB, server_default="{}")
    human_review_needed: Mapped[bool | None] = mapped_column(Boolean, default=False)
    human_review_reason: Mapped[str | None] = mapped_column(Text)
    semantic_status: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PdfTableGroup(Base):
    __tablename__ = "pdf_table_groups"

    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        Text, ForeignKey("pdf_jobs.job_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PdfTableGroupMember(Base):
    __tablename__ = "pdf_table_group_members"

    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pdf_table_groups.group_id", ondelete="CASCADE"),
        primary_key=True,
    )
    table_pk: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pdf_tables.id", ondelete="CASCADE"),
        primary_key=True,
    )
