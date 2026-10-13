"""Baseline schema + organisations + tenant columns + backfill.

Revision ID: 001_baseline
Revises:
Create Date: 2026-10-10

Additive only — does not drop existing tables or data.
Creates missing tables for fresh databases; adds columns for existing ones.
"""
from __future__ import annotations

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision: str = "001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(conn, name: str) -> bool:
    row = conn.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :n"
        ),
        {"n": name},
    ).fetchone()
    return row is not None


def _has_column(conn, table: str, column: str) -> bool:
    row = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return row is not None


def upgrade() -> None:
    conn = op.get_bind()

    # Optional pgvector extension (non-fatal if unavailable).
    try:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    except Exception:
        conn.execute(text("ROLLBACK"))
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        except Exception:
            pass

    # --- Core catalogue tables (CREATE IF NOT EXISTS for fresh DBs) ---
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS users (
                email          TEXT PRIMARY KEY,
                password_hash  TEXT NOT NULL,
                name           TEXT,
                dept           TEXT,
                created_at     TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    )
    if not _has_column(conn, "users", "id"):
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN id UUID "
                "DEFAULT gen_random_uuid()"
            )
        )
        conn.execute(text("UPDATE users SET id = gen_random_uuid() WHERE id IS NULL"))
        conn.execute(text("ALTER TABLE users ALTER COLUMN id SET NOT NULL"))
        conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ux_users_id ON users (id)")
        )

    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS organisations (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name        TEXT NOT NULL,
                slug        TEXT NOT NULL UNIQUE,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS organisation_memberships (
                organisation_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
                user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role            TEXT NOT NULL DEFAULT 'data_steward',
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (organisation_id, user_id)
            )
            """
        )
    )

    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS metadata_groups (
                metadata_id       TEXT PRIMARY KEY,
                title             TEXT,
                description       TEXT,
                product           TEXT,
                category          TEXT,
                geography         TEXT,
                frequency         TEXT,
                time_period       TEXT,
                data_source       TEXT,
                last_updated_date TEXT,
                future_release    TEXT,
                key_statistics    TEXT,
                remarks           TEXT,
                metadata_excel    TEXT,
                table_ids         TEXT[],
                classifications   JSONB DEFAULT '{}',
                concepts          TEXT[] DEFAULT '{}',
                full_record       JSONB DEFAULT '{}',
                user_email        TEXT
            )
            """
        )
    )
    for col, ddl in (
        ("user_email", "TEXT"),
        ("nmds_concepts", "JSONB DEFAULT '{}'"),
        ("sector", "TEXT"),
        ("theme", "TEXT"),
        ("catalogue_product", "TEXT"),
        ("organisation_id", "UUID REFERENCES organisations(id)"),
    ):
        if not _has_column(conn, "metadata_groups", col):
            conn.execute(text(f"ALTER TABLE metadata_groups ADD COLUMN {col} {ddl}"))

    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS datasets (
                dataset_id         TEXT PRIMARY KEY,
                unique_dataset_id  TEXT,
                table_id           TEXT,
                metadata_id        TEXT REFERENCES metadata_groups,
                title              TEXT,
                short_description  TEXT,
                long_description   TEXT,
                category           TEXT,
                geography          TEXT,
                frequency          TEXT,
                time_period        TEXT,
                data_source        TEXT,
                units              TEXT,
                classifications    JSONB DEFAULT '{}',
                concepts           TEXT[] DEFAULT '{}',
                age_column_keys    JSONB DEFAULT '{}',
                source_excel       TEXT,
                original_excel     TEXT,
                user_email         TEXT
            )
            """
        )
    )
    for col, ddl in (
        ("source_excel", "TEXT"),
        ("original_excel", "TEXT"),
        ("user_email", "TEXT"),
        ("organisation_id", "UUID REFERENCES organisations(id)"),
    ):
        if not _has_column(conn, "datasets", col):
            conn.execute(text(f"ALTER TABLE datasets ADD COLUMN {col} {ddl}"))

    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS dataset_rows (
                id         SERIAL PRIMARY KEY,
                dataset_id TEXT REFERENCES datasets ON DELETE CASCADE,
                sl_no      TEXT,
                row_index  INTEGER,
                row_data   JSONB NOT NULL,
                user_email TEXT
            )
            """
        )
    )
    if not _has_column(conn, "dataset_rows", "organisation_id"):
        conn.execute(
            text(
                "ALTER TABLE dataset_rows ADD COLUMN organisation_id "
                "UUID REFERENCES organisations(id)"
            )
        )

    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS kyds_entries (
                id          SERIAL PRIMARY KEY,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                user_email  TEXT,
                user_name   TEXT,
                user_dept   TEXT,
                responses   JSONB NOT NULL
            )
            """
        )
    )
    if not _has_column(conn, "kyds_entries", "updated_at"):
        conn.execute(text("ALTER TABLE kyds_entries ADD COLUMN updated_at TIMESTAMPTZ"))
    if not _has_column(conn, "kyds_entries", "organisation_id"):
        conn.execute(
            text(
                "ALTER TABLE kyds_entries ADD COLUMN organisation_id "
                "UUID REFERENCES organisations(id)"
            )
        )

    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS llm_api_keys (
                user_email  TEXT PRIMARY KEY,
                provider    TEXT,
                api_key     TEXT NOT NULL,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    )

    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS nco_2015_codes (
                nco_code           TEXT PRIMARY KEY,
                occupation_title   TEXT NOT NULL,
                division_code      TEXT,
                division_title     TEXT,
                subdivision_code   TEXT,
                subdivision_title  TEXT,
                group_code         TEXT,
                group_title        TEXT,
                family_code        TEXT,
                family_title       TEXT,
                qp_nos_reference   TEXT
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS classification_standards (
                id                 SERIAL PRIMARY KEY,
                name               TEXT NOT NULL UNIQUE,
                description        TEXT,
                original_filename  TEXT,
                row_count          INTEGER NOT NULL DEFAULT 0,
                is_selected        BOOLEAN NOT NULL DEFAULT FALSE,
                uploaded_by        TEXT,
                created_at         TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS classification_standard_codes (
                id                 SERIAL PRIMARY KEY,
                standard_id        INTEGER NOT NULL
                                       REFERENCES classification_standards(id) ON DELETE CASCADE,
                nco_code           TEXT NOT NULL,
                occupation_title   TEXT NOT NULL,
                division_code      TEXT,
                division_title     TEXT,
                subdivision_code   TEXT,
                subdivision_title  TEXT,
                group_code         TEXT,
                group_title        TEXT,
                family_code        TEXT,
                family_title       TEXT,
                qp_nos_reference   TEXT,
                UNIQUE (standard_id, nco_code)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS nco_value_aliases (
                normalized_value TEXT PRIMARY KEY,
                level            TEXT NOT NULL,
                code             TEXT NOT NULL,
                title            TEXT,
                source           TEXT DEFAULT 'steward',
                updated_at       TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    )

    # PDF tables
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS pdf_jobs (
                job_id       TEXT PRIMARY KEY,
                user_email   TEXT NOT NULL,
                filename     TEXT,
                status       TEXT NOT NULL DEFAULT 'done',
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                updated_at   TIMESTAMPTZ DEFAULT NOW(),
                grouping_status TEXT DEFAULT 'pending'
            )
            """
        )
    )
    for col, ddl in (
        ("stage", "TEXT"),
        ("percent", "INTEGER DEFAULT 0"),
        ("message", "TEXT"),
        ("error", "TEXT"),
        ("result", "JSONB"),
        ("reviews", "JSONB DEFAULT '{}'::jsonb"),
        ("deleted_table_ids", "JSONB DEFAULT '[]'::jsonb"),
        ("pdf_bytes", "BYTEA"),
        ("created_at_epoch", "DOUBLE PRECISION"),
        ("pipeline_step", "INTEGER"),
        ("source_type", "TEXT"),
        ("organisation_id", "UUID REFERENCES organisations(id)"),
    ):
        if not _has_column(conn, "pdf_jobs", col):
            conn.execute(text(f"ALTER TABLE pdf_jobs ADD COLUMN {col} {ddl}"))

    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS pdf_tables (
                id                 UUID PRIMARY KEY,
                job_id             TEXT NOT NULL REFERENCES pdf_jobs(job_id) ON DELETE CASCADE,
                table_id           TEXT NOT NULL,
                page               INTEGER,
                title              TEXT,
                source_rows        JSONB DEFAULT '[]',
                columns            JSONB DEFAULT '[]',
                classification     JSONB DEFAULT '{}',
                human_review_needed BOOLEAN DEFAULT FALSE,
                human_review_reason TEXT,
                semantic_status    TEXT,
                deleted_at         TIMESTAMPTZ,
                created_at         TIMESTAMPTZ DEFAULT NOW(),
                updated_at         TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (job_id, table_id)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS pdf_table_groups (
                group_id     UUID PRIMARY KEY,
                job_id       TEXT NOT NULL REFERENCES pdf_jobs(job_id) ON DELETE CASCADE,
                name         TEXT NOT NULL,
                sort_order   INTEGER NOT NULL DEFAULT 0,
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                updated_at   TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS pdf_table_group_members (
                group_id     UUID NOT NULL REFERENCES pdf_table_groups(group_id) ON DELETE CASCADE,
                table_pk     UUID NOT NULL REFERENCES pdf_tables(id) ON DELETE CASCADE,
                PRIMARY KEY (group_id, table_pk)
            )
            """
        )
    )

    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS extract_staging (
                batch_id   TEXT NOT NULL,
                uid        TEXT NOT NULL,
                table_json JSONB,
                user_email TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (batch_id, uid)
            )
            """
        )
    )
    if not _has_column(conn, "extract_staging", "organisation_id"):
        conn.execute(
            text(
                "ALTER TABLE extract_staging ADD COLUMN organisation_id "
                "UUID REFERENCES organisations(id)"
            )
        )

    # semantic_embeddings — best effort with vector type
    dim = int(os.environ.get("EMBEDDING_DIM", "1536"))
    try:
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS semantic_embeddings (
                    id            UUID PRIMARY KEY,
                    object_type   TEXT NOT NULL,
                    object_id     TEXT NOT NULL,
                    chunk_kind    TEXT NOT NULL,
                    chunk_text    TEXT NOT NULL,
                    embedding     vector({dim}),
                    metadata      JSONB DEFAULT '{{}}',
                    user_email    TEXT,
                    created_at    TIMESTAMPTZ DEFAULT NOW(),
                    updated_at    TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (object_type, object_id, chunk_kind)
                )
                """
            )
        )
        if not _has_column(conn, "semantic_embeddings", "job_id"):
            conn.execute(text("ALTER TABLE semantic_embeddings ADD COLUMN job_id TEXT"))
        if not _has_column(conn, "semantic_embeddings", "organisation_id"):
            conn.execute(
                text(
                    "ALTER TABLE semantic_embeddings ADD COLUMN organisation_id "
                    "UUID REFERENCES organisations(id)"
                )
            )
    except Exception:
        # Extension missing — skip embeddings table; readiness reports pgvector false.
        pass

    # --- Data backfill: default organisation + memberships + tenant columns ---
    slug = (os.environ.get("DEFAULT_ORGANISATION_SLUG") or "default").strip()
    name = (os.environ.get("DEFAULT_ORGANISATION_NAME") or "Default Organisation").strip()
    admin_email = (os.environ.get("BOOTSTRAP_ADMIN_EMAIL") or "").strip().lower() or None

    conn.execute(
        text(
            """
            INSERT INTO organisations (id, name, slug)
            SELECT gen_random_uuid(), :name, :slug
            WHERE NOT EXISTS (SELECT 1 FROM organisations WHERE slug = :slug)
            """
        ),
        {"name": name, "slug": slug},
    )
    org_id = conn.execute(
        text("SELECT id FROM organisations WHERE slug = :slug"),
        {"slug": slug},
    ).scalar()

    if org_id is not None:
        users = conn.execute(text("SELECT email, id FROM users")).fetchall()
        first = True
        for email, user_id in users:
            role = "data_steward"
            if admin_email and email and email.lower() == admin_email:
                role = "administrator"
            elif first and not admin_email:
                role = "administrator"
            first = False
            conn.execute(
                text(
                    """
                    INSERT INTO organisation_memberships (organisation_id, user_id, role)
                    VALUES (:oid, :uid, :role)
                    ON CONFLICT (organisation_id, user_id) DO NOTHING
                    """
                ),
                {"oid": org_id, "uid": user_id, "role": role},
            )

        # Backfill organisation_id from user_email → users → membership
        for table in (
            "metadata_groups",
            "datasets",
            "dataset_rows",
            "kyds_entries",
            "pdf_jobs",
            "extract_staging",
        ):
            if _has_table(conn, table) and _has_column(conn, table, "organisation_id"):
                conn.execute(
                    text(
                        f"""
                        UPDATE {table} t
                           SET organisation_id = :oid
                         WHERE organisation_id IS NULL
                           AND (
                             user_email IS NULL
                             OR EXISTS (
                               SELECT 1 FROM users u
                               WHERE u.email = t.user_email
                             )
                           )
                        """
                    ),
                    {"oid": org_id},
                )
        if _has_table(conn, "semantic_embeddings") and _has_column(
            conn, "semantic_embeddings", "organisation_id"
        ):
            conn.execute(
                text(
                    """
                    UPDATE semantic_embeddings
                       SET organisation_id = :oid
                     WHERE organisation_id IS NULL
                    """
                ),
                {"oid": org_id},
            )

    # Helpful indexes
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_datasets_metadata_id ON datasets (metadata_id)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_dataset_rows_dataset_id ON dataset_rows (dataset_id)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_pdf_jobs_user_updated "
            "ON pdf_jobs (user_email, updated_at DESC)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_pdf_jobs_organisation "
            "ON pdf_jobs (organisation_id)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_datasets_organisation "
            "ON datasets (organisation_id)"
        )
    )


def downgrade() -> None:
    # Additive migration — downgrade only removes new org structures, not baseline tables.
    op.execute("DROP TABLE IF EXISTS organisation_memberships CASCADE")
    op.execute("DROP TABLE IF EXISTS organisations CASCADE")
    # Do not drop users.id or tenant columns (would lose data / break FKs).
