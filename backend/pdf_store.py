"""
Authoritative Postgres storage for PDF pipeline jobs, tables & groupings.

Working extraction/review state (result, reviews, deleted ids, source PDF bytes)
lives on `pdf_jobs` — nothing is written under backend/data/. After Continue from
Preview, approved tables are also normalized into `pdf_tables` / groups.
pgvector embeddings are an ancillary index (see vector_store / pdf_grouping).
"""

from __future__ import annotations

import json
import time
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
        # Working-job columns (extraction + review). Added via ALTER so existing
        # deployments keep their pdf_jobs rows without a separate migration.
        for stmt in (
            "ALTER TABLE pdf_jobs ADD COLUMN IF NOT EXISTS stage TEXT",
            "ALTER TABLE pdf_jobs ADD COLUMN IF NOT EXISTS percent INTEGER DEFAULT 0",
            "ALTER TABLE pdf_jobs ADD COLUMN IF NOT EXISTS message TEXT",
            "ALTER TABLE pdf_jobs ADD COLUMN IF NOT EXISTS error TEXT",
            "ALTER TABLE pdf_jobs ADD COLUMN IF NOT EXISTS result JSONB",
            "ALTER TABLE pdf_jobs ADD COLUMN IF NOT EXISTS reviews JSONB DEFAULT '{}'::jsonb",
            "ALTER TABLE pdf_jobs ADD COLUMN IF NOT EXISTS deleted_table_ids JSONB DEFAULT '[]'::jsonb",
            "ALTER TABLE pdf_jobs ADD COLUMN IF NOT EXISTS pdf_bytes BYTEA",
            "ALTER TABLE pdf_jobs ADD COLUMN IF NOT EXISTS created_at_epoch DOUBLE PRECISION",
            "ALTER TABLE pdf_jobs ADD COLUMN IF NOT EXISTS pipeline_step INTEGER",
            """
            CREATE INDEX IF NOT EXISTS idx_pdf_jobs_user_updated
                ON pdf_jobs (user_email, updated_at DESC)
            """,
        ):
            cur.execute(stmt)
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


_WORKING_JOB_SELECT = """
    job_id, user_email, filename, status, stage, percent, message, error,
    result, reviews, deleted_table_ids, grouping_status, pipeline_step,
    created_at, created_at_epoch, updated_at
"""


def _json_obj(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


def _row_to_working_job(row: dict) -> dict:
    """Map a pdf_jobs row into the in-memory job dict used by main.py."""
    epoch = row.get("created_at_epoch")
    if epoch is None and row.get("created_at") is not None:
        try:
            epoch = float(row["created_at"].timestamp())
        except Exception:
            epoch = time.time()
    elif epoch is not None:
        epoch = float(epoch)
    else:
        epoch = time.time()

    return {
        "job_id": row["job_id"],
        "status": row.get("status") or "queued",
        "stage": row.get("stage") or row.get("status") or "queued",
        "percent": int(row.get("percent") or 0),
        "message": row.get("message") or "",
        "filename": row.get("filename"),
        "user_email": row.get("user_email"),
        "created_at": epoch,
        "result": _json_obj(row.get("result"), None),
        "error": row.get("error"),
        "reviews": _json_obj(row.get("reviews"), {}) or {},
        "deleted_table_ids": _json_obj(row.get("deleted_table_ids"), []) or [],
        "grouping_status": row.get("grouping_status"),
        "pipeline_step": int(row["pipeline_step"]) if row.get("pipeline_step") is not None else None,
    }


def save_working_job(
    conn,
    job: dict,
    *,
    pdf_bytes: Optional[bytes] = None,
    clear_pdf_bytes: bool = False,
) -> None:
    """Upsert extraction/review working state. pdf_bytes only written when provided."""
    job_id = job["job_id"]
    created_epoch = float(job.get("created_at") or time.time())
    reviews = job.get("reviews") if isinstance(job.get("reviews"), dict) else {}
    deleted = job.get("deleted_table_ids") if isinstance(job.get("deleted_table_ids"), list) else []
    result = job.get("result")

    with conn.cursor() as cur:
        if pdf_bytes is not None or clear_pdf_bytes:
            cur.execute(
                """
                INSERT INTO pdf_jobs (
                    job_id, user_email, filename, status, stage, percent, message, error,
                    result, reviews, deleted_table_ids, pdf_bytes, created_at_epoch, updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, NOW()
                )
                ON CONFLICT (job_id) DO UPDATE SET
                    user_email = EXCLUDED.user_email,
                    filename = COALESCE(EXCLUDED.filename, pdf_jobs.filename),
                    status = EXCLUDED.status,
                    stage = EXCLUDED.stage,
                    percent = EXCLUDED.percent,
                    message = EXCLUDED.message,
                    error = EXCLUDED.error,
                    result = EXCLUDED.result,
                    reviews = EXCLUDED.reviews,
                    deleted_table_ids = EXCLUDED.deleted_table_ids,
                    pdf_bytes = EXCLUDED.pdf_bytes,
                    created_at_epoch = COALESCE(pdf_jobs.created_at_epoch, EXCLUDED.created_at_epoch),
                    updated_at = NOW()
                """,
                (
                    job_id,
                    job.get("user_email"),
                    job.get("filename"),
                    job.get("status") or "queued",
                    job.get("stage"),
                    int(job.get("percent") or 0),
                    job.get("message"),
                    job.get("error"),
                    psycopg2.extras.Json(result) if result is not None else None,
                    psycopg2.extras.Json(reviews),
                    psycopg2.extras.Json(deleted),
                    None if clear_pdf_bytes else psycopg2.Binary(pdf_bytes),
                    created_epoch,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO pdf_jobs (
                    job_id, user_email, filename, status, stage, percent, message, error,
                    result, reviews, deleted_table_ids, created_at_epoch, updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, NOW()
                )
                ON CONFLICT (job_id) DO UPDATE SET
                    user_email = EXCLUDED.user_email,
                    filename = COALESCE(EXCLUDED.filename, pdf_jobs.filename),
                    status = EXCLUDED.status,
                    stage = EXCLUDED.stage,
                    percent = EXCLUDED.percent,
                    message = EXCLUDED.message,
                    error = EXCLUDED.error,
                    result = EXCLUDED.result,
                    reviews = EXCLUDED.reviews,
                    deleted_table_ids = EXCLUDED.deleted_table_ids,
                    created_at_epoch = COALESCE(pdf_jobs.created_at_epoch, EXCLUDED.created_at_epoch),
                    updated_at = NOW()
                """,
                (
                    job_id,
                    job.get("user_email"),
                    job.get("filename"),
                    job.get("status") or "queued",
                    job.get("stage"),
                    int(job.get("percent") or 0),
                    job.get("message"),
                    job.get("error"),
                    psycopg2.extras.Json(result) if result is not None else None,
                    psycopg2.extras.Json(reviews),
                    psycopg2.extras.Json(deleted),
                    created_epoch,
                ),
            )
    conn.commit()


def load_working_job(conn, job_id: str) -> Optional[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_WORKING_JOB_SELECT} FROM pdf_jobs WHERE job_id = %s",
            (job_id,),
        )
        row = cur.fetchone()
        return _row_to_working_job(dict(row)) if row else None


def list_working_jobs(conn, user_email: str) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT {_WORKING_JOB_SELECT}
              FROM pdf_jobs
             WHERE user_email = %s
             ORDER BY COALESCE(created_at_epoch, EXTRACT(EPOCH FROM created_at)) DESC NULLS LAST
            """,
            (user_email,),
        )
        return [_row_to_working_job(dict(r)) for r in cur.fetchall()]


def get_pdf_bytes(conn, job_id: str) -> Optional[bytes]:
    with conn.cursor() as cur:
        cur.execute("SELECT pdf_bytes FROM pdf_jobs WHERE job_id = %s", (job_id,))
        row = cur.fetchone()
        if not row or row[0] is None:
            return None
        return bytes(row[0])


def set_pipeline_step(conn, job_id: str, step: int) -> None:
    """Record the furthest console step reached for dashboard readiness."""
    step_i = max(1, min(6, int(step)))
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE pdf_jobs
               SET pipeline_step = GREATEST(COALESCE(pipeline_step, 0), %s),
                   updated_at = NOW()
             WHERE job_id = %s
            """,
            (step_i, job_id),
        )
    conn.commit()


def get_pipeline_step(conn, job_id: str) -> Optional[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT pipeline_step FROM pdf_jobs WHERE job_id = %s", (job_id,))
        row = cur.fetchone()
        if not row or row[0] is None:
            return None
        return int(row[0])
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
               SET grouping_status = 'pending',
                   pipeline_step = GREATEST(COALESCE(pipeline_step, 0), 3),
                   updated_at = NOW()
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
               SET grouping_status = 'saved',
                   pipeline_step = GREATEST(COALESCE(pipeline_step, 0), 4),
                   updated_at = NOW()
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
