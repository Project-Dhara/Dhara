"""Durable counters for sequential catalogue dataset IDs.

Revision ID: 004_dataset_id_counters
Revises: 003_pdf_table_snapshots
Create Date: 2026-10-16

Additive only — CREATE TABLE IF NOT EXISTS.
Counters never decrease, so published ids like ``DDI_DES_DEL_VS_00042``
are not reused after delete.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "004_dataset_id_counters"
down_revision: Union[str, None] = "003_pdf_table_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS dataset_id_counters (
                stem         TEXT PRIMARY KEY,
                last_value   INTEGER NOT NULL DEFAULT 0,
                updated_at   TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("DROP TABLE IF EXISTS dataset_id_counters"))
