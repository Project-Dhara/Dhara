"""Temporary storage for extracted Excel/SQL tables between extract and catalogue push.

batch-push used to receive full table rows inside a multipart form field, which
hits Starlette's 1MB max_part_size on large batches. Callers now stage tables
here at extract time and send only ids + steward overlays on push.
"""

from __future__ import annotations

import uuid
from typing import Iterable, Optional

import psycopg2.extras


def init_staging_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS extract_staging (
                batch_id   TEXT NOT NULL,
                uid        TEXT NOT NULL,
                table_json JSONB NOT NULL,
                user_email TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (batch_id, uid)
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS extract_staging_created_at_idx
                ON extract_staging (created_at)
            """
        )
    conn.commit()


def new_batch_id() -> str:
    return str(uuid.uuid4())


def save_staging_tables(
    conn,
    batch_id: str,
    tables: list,
    user_email: Optional[str] = None,
) -> int:
    """Replace all rows for batch_id with the given tables. Returns count saved."""
    if not batch_id:
        raise ValueError("batch_id is required")
    init_staging_schema(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM extract_staging WHERE batch_id = %s", (batch_id,))
        saved = 0
        for t in tables or []:
            if not isinstance(t, dict):
                continue
            uid = str(t.get("_uid") or t.get("id") or "").strip()
            if not uid:
                continue
            cur.execute(
                """
                INSERT INTO extract_staging (batch_id, uid, table_json, user_email)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (batch_id, uid) DO UPDATE SET
                    table_json = EXCLUDED.table_json,
                    user_email = EXCLUDED.user_email,
                    created_at = NOW()
                """,
                (batch_id, uid, psycopg2.extras.Json(t), user_email),
            )
            saved += 1
        # Drop stale batches so the table does not grow without bound.
        cur.execute(
            "DELETE FROM extract_staging WHERE created_at < NOW() - INTERVAL '7 days'"
        )
    conn.commit()
    return saved


def load_staging_tables(
    conn,
    batch_id: str,
    uids: Optional[Iterable[str]] = None,
) -> dict:
    """Return {uid: table_dict} for a batch. Optionally filter to uids."""
    if not batch_id:
        return {}
    init_staging_schema(conn)
    uid_list = [str(u) for u in (uids or []) if u]
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if uid_list:
            cur.execute(
                """
                SELECT uid, table_json FROM extract_staging
                 WHERE batch_id = %s AND uid = ANY(%s)
                """,
                (batch_id, uid_list),
            )
        else:
            cur.execute(
                "SELECT uid, table_json FROM extract_staging WHERE batch_id = %s",
                (batch_id,),
            )
        out = {}
        for row in cur.fetchall():
            raw = row["table_json"]
            if isinstance(raw, str):
                import json
                try:
                    raw = json.loads(raw)
                except Exception:
                    continue
            if isinstance(raw, dict):
                out[str(row["uid"])] = raw
        return out
