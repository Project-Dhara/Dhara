"""Indexes and HNSW that previously lived only in request-time DDL.

Revision ID: 002_indexes_hnsw
Revises: 001_baseline
Create Date: 2026-10-11

Additive only — CREATE INDEX / EXTENSION IF NOT EXISTS.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "002_indexes_hnsw"
down_revision: Union[str, None] = "001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    try:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception:
        pass

    # Catalogue / KYDS / standards indexes from former init_schema
    for stmt in (
        "CREATE INDEX IF NOT EXISTS idx_kyds_entries_created_at "
        "ON kyds_entries (created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_classification_standard_codes_standard "
        "ON classification_standard_codes (standard_id)",
        "CREATE INDEX IF NOT EXISTS extract_staging_created_at_idx "
        "ON extract_staging (created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_pdf_tables_job "
        "ON pdf_tables (job_id) WHERE deleted_at IS NULL",
        "CREATE INDEX IF NOT EXISTS idx_pdf_group_members_table "
        "ON pdf_table_group_members (table_pk)",
    ):
        try:
            conn.execute(text(stmt))
        except Exception:
            pass

    # semantic_embeddings columns + indexes (incl. HNSW)
    try:
        conn.execute(
            text(
                "ALTER TABLE semantic_embeddings "
                "ADD COLUMN IF NOT EXISTS job_id TEXT"
            )
        )
    except Exception:
        pass

    for stmt in (
        "CREATE INDEX IF NOT EXISTS idx_semantic_embeddings_object "
        "ON semantic_embeddings (object_type, object_id)",
        "CREATE INDEX IF NOT EXISTS idx_semantic_embeddings_kind "
        "ON semantic_embeddings (chunk_kind)",
        "CREATE INDEX IF NOT EXISTS idx_semantic_embeddings_job "
        "ON semantic_embeddings (job_id)",
        """
        CREATE INDEX IF NOT EXISTS idx_semantic_embeddings_hnsw
            ON semantic_embeddings
            USING hnsw (embedding vector_cosine_ops)
        """,
    ):
        try:
            conn.execute(text(stmt))
        except Exception:
            # HNSW / vector type may be unavailable on some hosts.
            pass


def downgrade() -> None:
    conn = op.get_bind()
    for name in (
        "idx_semantic_embeddings_hnsw",
        "idx_semantic_embeddings_job",
        "idx_semantic_embeddings_kind",
        "idx_semantic_embeddings_object",
        "idx_pdf_group_members_table",
        "idx_pdf_tables_job",
        "extract_staging_created_at_idx",
        "idx_classification_standard_codes_standard",
        "idx_kyds_entries_created_at",
    ):
        try:
            conn.execute(text(f"DROP INDEX IF EXISTS {name}"))
        except Exception:
            pass
