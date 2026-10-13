"""Persist per-table PDF snapshot PNGs for review comparison.

Revision ID: 003_pdf_table_snapshots
Revises: 002_indexes_hnsw
Create Date: 2026-10-13

Additive only — CREATE TABLE IF NOT EXISTS.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "003_pdf_table_snapshots"
down_revision: Union[str, None] = "002_indexes_hnsw"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS pdf_table_snapshots (
                job_id       TEXT NOT NULL REFERENCES pdf_jobs(job_id) ON DELETE CASCADE,
                table_id     TEXT NOT NULL,
                png_bytes    BYTEA NOT NULL,
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                updated_at   TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (job_id, table_id)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_pdf_table_snapshots_job
                ON pdf_table_snapshots (job_id)
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("DROP TABLE IF EXISTS pdf_table_snapshots"))
