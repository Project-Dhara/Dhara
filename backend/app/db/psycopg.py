"""Postgres connection + schema DDL for every catalogue-adjacent table."""
import os

import psycopg2


def get_connection():
    from app.core.config import psycopg2_dsn

    return psycopg2.connect(psycopg2_dsn())


def init_schema(conn):
    """Request-time DDL. No-op when ``DISABLE_REQUEST_TIME_DDL=true`` (Alembic)."""
    from app.core.config import get_settings

    if get_settings().disable_request_time_ddl:
        return

    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                email          TEXT PRIMARY KEY,
                password_hash  TEXT NOT NULL,
                name           TEXT,
                dept           TEXT,
                created_at     TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            ALTER TABLE users ADD COLUMN IF NOT EXISTS id UUID DEFAULT gen_random_uuid()
        """)
        cur.execute("""
            UPDATE users SET id = gen_random_uuid() WHERE id IS NULL
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_users_id ON users (id)
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS organisations (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name        TEXT NOT NULL,
                slug        TEXT NOT NULL UNIQUE,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS organisation_memberships (
                organisation_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
                user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role            TEXT NOT NULL DEFAULT 'data_steward',
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (organisation_id, user_id)
            )
        """)
        cur.execute("""
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
        """)
        cur.execute("""
            ALTER TABLE metadata_groups ADD COLUMN IF NOT EXISTS user_email TEXT
        """)
        cur.execute("""
            ALTER TABLE metadata_groups ADD COLUMN IF NOT EXISTS nmds_concepts JSONB DEFAULT '{}'
        """)
        cur.execute("""
            ALTER TABLE metadata_groups ADD COLUMN IF NOT EXISTS sector TEXT
        """)
        cur.execute("""
            ALTER TABLE metadata_groups ADD COLUMN IF NOT EXISTS theme TEXT
        """)
        cur.execute("""
            ALTER TABLE metadata_groups ADD COLUMN IF NOT EXISTS catalogue_product TEXT
        """)
        cur.execute("""
            ALTER TABLE metadata_groups ADD COLUMN IF NOT EXISTS organisation_id UUID
        """)
        cur.execute("""
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
        """)
        cur.execute("""
            ALTER TABLE datasets ADD COLUMN IF NOT EXISTS source_excel TEXT
        """)
        cur.execute("""
            ALTER TABLE datasets ADD COLUMN IF NOT EXISTS original_excel TEXT
        """)
        cur.execute("""
            ALTER TABLE datasets ADD COLUMN IF NOT EXISTS user_email TEXT
        """)
        cur.execute("""
            ALTER TABLE datasets ADD COLUMN IF NOT EXISTS organisation_id UUID
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS dataset_rows (
                id         SERIAL PRIMARY KEY,
                dataset_id TEXT REFERENCES datasets ON DELETE CASCADE,
                sl_no      TEXT,
                row_index  INTEGER,
                row_data   JSONB NOT NULL,
                user_email TEXT
            )
        """)
        cur.execute("""
            ALTER TABLE dataset_rows ADD COLUMN IF NOT EXISTS user_email TEXT
        """)
        cur.execute("""
            ALTER TABLE dataset_rows ADD COLUMN IF NOT EXISTS organisation_id UUID
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_datasets_metadata_id
                ON datasets (metadata_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_dataset_rows_dataset_id
                ON dataset_rows (dataset_id)
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kyds_entries (
                id          SERIAL PRIMARY KEY,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                user_email  TEXT,
                user_name   TEXT,
                user_dept   TEXT,
                responses   JSONB NOT NULL
            )
        """)
        cur.execute("""
            ALTER TABLE kyds_entries ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ
        """)
        cur.execute("""
            ALTER TABLE kyds_entries ADD COLUMN IF NOT EXISTS organisation_id UUID
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_kyds_entries_created_at
                ON kyds_entries (created_at DESC)
        """)
        # Per-user LLM credentials — separate from users (not a column on users).
        cur.execute("""
            CREATE TABLE IF NOT EXISTS llm_api_keys (
                user_email  TEXT PRIMARY KEY,
                provider    TEXT,
                api_key     TEXT NOT NULL,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
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
        """)
        # Steward-uploaded concordance files (Settings → Classification).
        # Selecting one reloads nco_2015_codes for the existing match pipeline.
        cur.execute("""
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
        """)
        cur.execute("""
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
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_classification_standard_codes_standard
                ON classification_standard_codes (standard_id)
        """)
        # Steward-learned mappings from Classify verify — not a hardcoded label list.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nco_value_aliases (
                normalized_value TEXT PRIMARY KEY,
                level            TEXT NOT NULL,
                code             TEXT NOT NULL,
                title            TEXT,
                source           TEXT DEFAULT 'steward',
                updated_at       TIMESTAMPTZ DEFAULT NOW()
            )
        """)
    conn.commit()

    # Stage 6 — pgvector embeddings store (ancillary to authoritative tables above).
    try:
        from app.storage import vectors as _vs
        _vs.ensure_semantic_embeddings_table(conn)
    except Exception as exc:
        # Non-pgvector Postgres (e.g. managed DB without the extension) must
        # not break catalogue init; surface via /api/ready (and /api/health).
        # Critical: roll back so the connection is usable for later queries
        # (otherwise callers hit InFailedSqlTransaction).
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"[catalogue.init_schema] pgvector setup skipped: {exc}")

    # PDF pipeline authoritative tables (Preview → Grouping).
    try:
        from app.db import pdf_store as _pdf_store
        _pdf_store.init_pdf_schema(conn)
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"[catalogue.init_schema] pdf_store setup skipped: {exc}")

    # Excel/SQL extract staging for slim batch-push payloads.
    try:
        from app.services.catalogue import extract_staging as _staging
        _staging.init_staging_schema(conn)
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"[catalogue.init_schema] extract_staging setup skipped: {exc}")

    # Optional local NCO concordance → classification_standards list entry.
    try:
        from app.services.standards.classification_standards import ensure_bundled_nco_standard

        ensure_bundled_nco_standard(conn)
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"[catalogue.init_schema] bundled NCO standard skipped: {exc}")
