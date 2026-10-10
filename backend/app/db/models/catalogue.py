"""Catalogue / published dataset models (mirror existing DDL)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MetadataGroup(Base):
    __tablename__ = "metadata_groups"

    metadata_id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    product: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    geography: Mapped[str | None] = mapped_column(Text)
    frequency: Mapped[str | None] = mapped_column(Text)
    time_period: Mapped[str | None] = mapped_column(Text)
    data_source: Mapped[str | None] = mapped_column(Text)
    last_updated_date: Mapped[str | None] = mapped_column(Text)
    future_release: Mapped[str | None] = mapped_column(Text)
    key_statistics: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)
    metadata_excel: Mapped[str | None] = mapped_column(Text)
    table_ids: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    classifications: Mapped[dict[str, Any] | None] = mapped_column(JSONB, server_default="{}")
    concepts: Mapped[list[str] | None] = mapped_column(ARRAY(Text), server_default="{}")
    full_record: Mapped[dict[str, Any] | None] = mapped_column(JSONB, server_default="{}")
    user_email: Mapped[str | None] = mapped_column(Text)
    nmds_concepts: Mapped[dict[str, Any] | None] = mapped_column(JSONB, server_default="{}")
    sector: Mapped[str | None] = mapped_column(Text)
    theme: Mapped[str | None] = mapped_column(Text)
    catalogue_product: Mapped[str | None] = mapped_column(Text)
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=True
    )


class Dataset(Base):
    __tablename__ = "datasets"

    dataset_id: Mapped[str] = mapped_column(Text, primary_key=True)
    unique_dataset_id: Mapped[str | None] = mapped_column(Text)
    table_id: Mapped[str | None] = mapped_column(Text)
    metadata_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("metadata_groups.metadata_id")
    )
    title: Mapped[str | None] = mapped_column(Text)
    short_description: Mapped[str | None] = mapped_column(Text)
    long_description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    geography: Mapped[str | None] = mapped_column(Text)
    frequency: Mapped[str | None] = mapped_column(Text)
    time_period: Mapped[str | None] = mapped_column(Text)
    data_source: Mapped[str | None] = mapped_column(Text)
    units: Mapped[str | None] = mapped_column(Text)
    classifications: Mapped[dict[str, Any] | None] = mapped_column(JSONB, server_default="{}")
    concepts: Mapped[list[str] | None] = mapped_column(ARRAY(Text), server_default="{}")
    age_column_keys: Mapped[dict[str, Any] | None] = mapped_column(JSONB, server_default="{}")
    source_excel: Mapped[str | None] = mapped_column(Text)
    original_excel: Mapped[str | None] = mapped_column(Text)
    user_email: Mapped[str | None] = mapped_column(Text)
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=True
    )


class DatasetRow(Base):
    __tablename__ = "dataset_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("datasets.dataset_id", ondelete="CASCADE")
    )
    sl_no: Mapped[str | None] = mapped_column(Text)
    row_index: Mapped[int | None] = mapped_column(Integer)
    row_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    user_email: Mapped[str | None] = mapped_column(Text)
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=True
    )


class KydsEntry(Base):
    __tablename__ = "kyds_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_email: Mapped[str | None] = mapped_column(Text)
    user_name: Mapped[str | None] = mapped_column(Text)
    user_dept: Mapped[str | None] = mapped_column(Text)
    responses: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=True
    )


class LlmApiKey(Base):
    __tablename__ = "llm_api_keys"

    user_email: Mapped[str] = mapped_column(Text, primary_key=True)
    provider: Mapped[str | None] = mapped_column(Text)
    api_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
