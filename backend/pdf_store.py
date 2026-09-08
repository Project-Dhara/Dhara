"""
Authoritative Postgres storage for PDF pipeline tables & groupings.

JSON under data/pdf_jobs/ remains a processing cache for extraction/review.
On Continue from Preview, approved tables are upserted here — this module is
the source of truth for grouping and downstream stages. pgvector embeddings
are an ancillary index (see vector_store / pdf_grouping).
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional

import psycopg2.extras


CLASSIFICATION_FIELDS = (
    "domain", "subject", "entity", "table_type",
    "geography", "time_period", "frequency", "unit",
)


def init_pdf_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
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
        cur.execute(
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
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_pdf_tables_job
                ON pdf_tables (job_id) WHERE deleted_at IS NULL
            """
        )
        cur.execute(
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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pdf_table_group_members (
                group_id     UUID NOT NULL REFERENCES pdf_table_groups(group_id) ON DELETE CASCADE,
                table_pk     UUID NOT NULL REFERENCES pdf_tables(id) ON DELETE CASCADE,
                PRIMARY KEY (group_id, table_pk)
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_pdf_group_members_table
                ON pdf_table_group_members (table_pk)
            """
        )
    conn.commit()

    # Optional job_id on embeddings for same-job similarity filters.
    try:
        import vector_store as _vs
        _vs.ensure_semantic_embeddings_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                "ALTER TABLE semantic_embeddings ADD COLUMN IF NOT EXISTS job_id TEXT"
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_semantic_embeddings_job
                    ON semantic_embeddings (job_id)
                """
            )
        conn.commit()
    except Exception as exc:
        print(f"[pdf_store] vector column setup skipped: {exc}", flush=True)


def _class_value(field: Any) -> Optional[str]:
    if field is None:
        return None
    if isinstance(field, dict):
        v = field.get("value")
        return str(v).strip() if v is not None and str(v).strip() else None
    s = str(field).strip()
    return s or None


def classification_dict(table: dict) -> dict:
    out = {}
    for key in CLASSIFICATION_FIELDS:
        if key in table:
            out[key] = table[key]
    # Also keep full nested blobs if already present under classification
    if isinstance(table.get("classification"), dict):
        out = {**table["classification"], **out}
    return out


def flatten_classification_text(classification: dict) -> dict:
    """Pull .value strings for chunking / display."""
    flat = {}
    for key in CLASSIFICATION_FIELDS:
        flat[key] = _class_value(classification.get(key))
    return flat


def upsert_job(conn, *, job_id: str, user_email: str, filename: Optional[str], status: str = "done") -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pdf_jobs (job_id, user_email, filename, status, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (job_id) DO UPDATE SET
                user_email = EXCLUDED.user_email,
                filename = COALESCE(EXCLUDED.filename, pdf_jobs.filename),
                status = EXCLUDED.status,
                updated_at = NOW()
            """,
            (job_id, user_email, filename, status),
        )
    conn.commit()


def persist_approved_tables(
    conn,
    *,
    job_id: str,
    user_email: str,
    filename: Optional[str],
    tables: list[dict],
) -> list[dict]:
    """
    Replace active tables for a job with the approved preview set.
    Soft-deletes any previous rows not in the new set.
    Returns list of persisted table dicts including UUID `id`.
    """
    upsert_job(conn, job_id=job_id, user_email=user_email, filename=filename, status="done")
    kept_ids = []
    persisted = []
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for t in tables:
            table_id = str(t.get("table_id") or "")
            if not table_id:
                continue
            classification = classification_dict(t)
            page = t.get("page")
            try:
                page_i = int(page) if page is not None else None
            except (TypeError, ValueError):
                page_i = None
            cur.execute(
                """
                INSERT INTO pdf_tables (
                    id, job_id, table_id, page, title, source_rows, columns,
                    classification, human_review_needed, human_review_reason,
                    semantic_status, deleted_at, updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, NULL, NOW()
                )
                ON CONFLICT (job_id, table_id) DO UPDATE SET
                    page = EXCLUDED.page,
                    title = EXCLUDED.title,
                    source_rows = EXCLUDED.source_rows,
                    columns = EXCLUDED.columns,
                    classification = EXCLUDED.classification,
                    human_review_needed = EXCLUDED.human_review_needed,
                    human_review_reason = EXCLUDED.human_review_reason,
                    semantic_status = EXCLUDED.semantic_status,
                    deleted_at = NULL,
                    updated_at = NOW()
                RETURNING *
                """,
                (
                    str(uuid.uuid4()),
                    job_id,
                    table_id,
                    page_i,
                    t.get("title"),
                    psycopg2.extras.Json(t.get("rows") or t.get("source_rows") or []),
                    psycopg2.extras.Json(t.get("columns") or []),
                    psycopg2.extras.Json(classification),
                    bool(t.get("human_review_needed")),
                    t.get("human_review_reason"),
                    t.get("semantic_status"),
                ),
            )
            row = dict(cur.fetchone())
            kept_ids.append(row["id"])
            persisted.append(_row_to_table(row))

        # Soft-delete tables removed in preview
        if kept_ids:
            cur.execute(
                """
                UPDATE pdf_tables
                   SET deleted_at = NOW(), updated_at = NOW()
                 WHERE job_id = %s
                   AND deleted_at IS NULL
                   AND id <> ALL(%s::uuid[])
                """,
                (job_id, kept_ids),
            )
        else:
            cur.execute(
                """
                UPDATE pdf_tables
                   SET deleted_at = NOW(), updated_at = NOW()
                 WHERE job_id = %s AND deleted_at IS NULL
                """,
                (job_id,),
            )
        cur.execute(
            """
            UPDATE pdf_jobs
               SET grouping_status = 'pending', updated_at = NOW()
             WHERE job_id = %s
            """,
            (job_id,),
        )
    conn.commit()
    return persisted


def _row_to_table(row: dict) -> dict:
    classification = row.get("classification") or {}
    if isinstance(classification, str):
        classification = json.loads(classification)
    flat = flatten_classification_text(classification)
    return {
        "id": str(row["id"]),
        "job_id": row["job_id"],
        "table_id": row["table_id"],
        "page": row.get("page"),
        "title": row.get("title") or "",
        "columns": row.get("columns") or [],
        "rows": row.get("source_rows") or [],
        "classification": classification,
        "domain": flat.get("domain"),
        "subject": flat.get("subject"),
        "entity": flat.get("entity"),
        "table_type": flat.get("table_type"),
        "geography": flat.get("geography"),
        "time_period": flat.get("time_period"),
        "frequency": flat.get("frequency"),
        "unit": flat.get("unit"),
        "human_review_needed": row.get("human_review_needed"),
        "human_review_reason": row.get("human_review_reason"),
        "semantic_status": row.get("semantic_status"),
    }


def list_active_tables(conn, job_id: str) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT * FROM pdf_tables
             WHERE job_id = %s AND deleted_at IS NULL
             ORDER BY page NULLS LAST, table_id
            """,
            (job_id,),
        )
        return [_row_to_table(dict(r)) for r in cur.fetchall()]


def get_job(conn, job_id: str) -> Optional[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM pdf_jobs WHERE job_id = %s", (job_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def save_grouping(
    conn,
    *,
    job_id: str,
    groups: list[dict],
) -> None:
    """
    Replace grouping for a job.
    groups: [{ name, table_pks: [uuid, ...] }]
    Tables not listed remain unmatched (no membership rows).
    """
    with conn.cursor() as cur:
        cur.execute("DELETE FROM pdf_table_groups WHERE job_id = %s", (job_id,))
        for i, g in enumerate(groups):
            gid = str(uuid.uuid4())
            name = (g.get("name") or f"Group {i + 1}").strip() or f"Group {i + 1}"
            cur.execute(
                """
                INSERT INTO pdf_table_groups (group_id, job_id, name, sort_order)
                VALUES (%s, %s, %s, %s)
                """,
                (gid, job_id, name, i),
            )
            for pk in g.get("table_pks") or []:
                cur.execute(
                    """
                    INSERT INTO pdf_table_group_members (group_id, table_pk)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (gid, str(pk)),
                )
        cur.execute(
            """
            UPDATE pdf_jobs
               SET grouping_status = 'saved', updated_at = NOW()
             WHERE job_id = %s
            """,
            (job_id,),
        )
    conn.commit()


def load_grouping(conn, job_id: str) -> dict:
    """
    Returns { groups: [{group_id, name, tables: [...]}], unmatched_tables: [...] }
    """
    tables = {t["id"]: t for t in list_active_tables(conn, job_id)}
    assigned = set()
    groups_out = []
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT group_id, name, sort_order
              FROM pdf_table_groups
             WHERE job_id = %s
             ORDER BY sort_order, name
            """,
            (job_id,),
        )
        group_rows = list(cur.fetchall())
        for gr in group_rows:
            cur.execute(
                """
                SELECT table_pk FROM pdf_table_group_members WHERE group_id = %s
                """,
                (str(gr["group_id"]),),
            )
            members = []
            for m in cur.fetchall():
                pk = str(m["table_pk"])
                if pk in tables:
                    members.append(tables[pk])
                    assigned.add(pk)
            groups_out.append(
                {
                    "group_id": str(gr["group_id"]),
                    "name": gr["name"],
                    "tables": members,
                }
            )
    unmatched = [t for tid, t in tables.items() if tid not in assigned]
    return {"groups": groups_out, "unmatched_tables": unmatched}
