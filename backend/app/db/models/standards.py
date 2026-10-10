"""Classification standards and NCO working set."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Nco2015Code(Base):
    __tablename__ = "nco_2015_codes"

    nco_code: Mapped[str] = mapped_column(Text, primary_key=True)
    occupation_title: Mapped[str] = mapped_column(Text, nullable=False)
    division_code: Mapped[str | None] = mapped_column(Text)
    division_title: Mapped[str | None] = mapped_column(Text)
    subdivision_code: Mapped[str | None] = mapped_column(Text)
    subdivision_title: Mapped[str | None] = mapped_column(Text)
    group_code: Mapped[str | None] = mapped_column(Text)
    group_title: Mapped[str | None] = mapped_column(Text)
    family_code: Mapped[str | None] = mapped_column(Text)
    family_title: Mapped[str | None] = mapped_column(Text)
    qp_nos_reference: Mapped[str | None] = mapped_column(Text)


class ClassificationStandard(Base):
    __tablename__ = "classification_standards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    original_filename: Mapped[str | None] = mapped_column(Text)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    uploaded_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ClassificationStandardCode(Base):
    __tablename__ = "classification_standard_codes"
    __table_args__ = (
        UniqueConstraint("standard_id", "nco_code", name="uq_standard_nco_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    standard_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("classification_standards.id", ondelete="CASCADE"),
        nullable=False,
    )
    nco_code: Mapped[str] = mapped_column(Text, nullable=False)
    occupation_title: Mapped[str] = mapped_column(Text, nullable=False)
    division_code: Mapped[str | None] = mapped_column(Text)
    division_title: Mapped[str | None] = mapped_column(Text)
    subdivision_code: Mapped[str | None] = mapped_column(Text)
    subdivision_title: Mapped[str | None] = mapped_column(Text)
    group_code: Mapped[str | None] = mapped_column(Text)
    group_title: Mapped[str | None] = mapped_column(Text)
    family_code: Mapped[str | None] = mapped_column(Text)
    family_title: Mapped[str | None] = mapped_column(Text)
    qp_nos_reference: Mapped[str | None] = mapped_column(Text)


class NcoValueAlias(Base):
    __tablename__ = "nco_value_aliases"

    normalized_value: Mapped[str] = mapped_column(Text, primary_key=True)
    level: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text, server_default="steward")
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
