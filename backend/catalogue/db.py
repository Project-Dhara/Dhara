"""Postgres connection + schema DDL for every catalogue-adjacent table."""
import os
from pathlib import Path

import psycopg2


def get_connection():
    url = os.environ["DATABASE_URL"]
    # Host-oriented .env often uses localhost; inside Compose that must be the
    # postgres service (sql_extract rewrite covers SQL upload DSNs separately).
    if Path("/.dockerenv").exists():
        from urllib.parse import urlparse, urlunparse, quote_plus

        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host in ("localhost", "127.0.0.1", "::1", "host.docker.internal"):
            userinfo = ""
            if parsed.username is not None:
                userinfo = quote_plus(parsed.username)
                if parsed.password is not None:
                    userinfo += ":" + quote_plus(parsed.password)
                userinfo += "@"
            port = parsed.port or 5432
            url = urlunparse(
                (parsed.scheme, f"{userinfo}postgres:{port}", parsed.path, parsed.params, parsed.query, parsed.fragment)
            )
    return psycopg2.connect(url)


def init_schema(conn):
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
            CREATE INDEX IF NOT EXISTS idx_kyds_entries_created_at
                ON kyds_entries (created_at DESC)
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
        from core import vector_store as _vs
        _vs.ensure_semantic_embeddings_table(conn)
    except Exception as exc:
        # Non-pgvector Postgres (e.g. managed DB without the extension) must
        # not break catalogue init; surface via /api/health when available.
        # Critical: roll back so the connection is usable for later queries
        # (otherwise callers hit InFailedSqlTransaction).
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"[catalogue.init_schema] pgvector setup skipped: {exc}")

    # PDF pipeline authoritative tables (Preview → Grouping).
    try:
        from pdf import pdf_store as _pdf_store
        _pdf_store.init_pdf_schema(conn)
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"[catalogue.init_schema] pdf_store setup skipped: {exc}")

    # Excel/SQL extract staging for slim batch-push payloads.
    try:
        from catalogue import extract_staging as _staging
        _staging.init_staging_schema(conn)
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"[catalogue.init_schema] extract_staging setup skipped: {exc}")
