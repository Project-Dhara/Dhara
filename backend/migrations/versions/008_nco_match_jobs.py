"""Postgres queue for Suggest NCO match jobs + attach tokens + alias counter.

Revision ID: 008_nco_match_jobs
Revises: 007_nco_alias_nco_version
Create Date: 2026-04-10

Additive only — CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "008_nco_match_jobs"
down_revision: Union[str, None] = "007_nco_alias_nco_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS nco_match_jobs (
                id UUID PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                owner TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                stage TEXT,
                progress_done INTEGER,
                progress_total INTEGER,
                request JSONB,
                result JSONB,
                error TEXT,
                created_at TIMESTAMPTZ DEFAULT now(),
                claimed_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ DEFAULT now(),
                last_polled_at TIMESTAMPTZ DEFAULT now(),
                finished_at TIMESTAMPTZ
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_nco_match_jobs_active_owner_fp
            ON nco_match_jobs (owner, fingerprint)
            WHERE status IN ('queued', 'running')
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_nco_match_jobs_status_polled
            ON nco_match_jobs (status, last_polled_at)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS nco_match_job_attach_tokens (
                token UUID PRIMARY KEY,
                job_id UUID NOT NULL
                    REFERENCES nco_match_jobs(id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ DEFAULT now()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_nco_match_job_attach_tokens_job_id
            ON nco_match_job_attach_tokens (job_id)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS nco_steward_alias_counter (
                id INTEGER PRIMARY KEY,
                counter INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ DEFAULT now()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            INSERT INTO nco_steward_alias_counter (id, counter)
            VALUES (1, 0)
            ON CONFLICT (id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("DROP TABLE IF EXISTS nco_match_job_attach_tokens"))
    conn.execute(text("DROP TABLE IF EXISTS nco_match_jobs"))
    conn.execute(text("DROP TABLE IF EXISTS nco_steward_alias_counter"))
