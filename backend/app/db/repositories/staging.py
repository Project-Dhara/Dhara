"""Extract staging repository (SQLAlchemy)."""
from __future__ import annotations

import json
import uuid
from typing import Any, Iterable, Optional

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.db.models.staging import ExtractStaging


def new_batch_id() -> str:
    return str(uuid.uuid4())


def save_staging_tables(
    session: Session,
    batch_id: str,
    tables: list,
    user_email: Optional[str] = None,
    organisation_id: uuid.UUID | None = None,
) -> int:
    if not batch_id:
        raise ValueError("batch_id is required")
    session.execute(
        delete(ExtractStaging).where(ExtractStaging.batch_id == batch_id)
    )
    saved = 0
    for t in tables or []:
        if not isinstance(t, dict):
            continue
        uid = str(t.get("_uid") or t.get("id") or "").strip()
        if not uid:
            continue
        session.add(
            ExtractStaging(
                batch_id=batch_id,
                uid=uid,
                table_json=t,
                user_email=user_email,
                organisation_id=organisation_id,
            )
        )
        saved += 1
    session.execute(
        text(
            "DELETE FROM extract_staging WHERE created_at < NOW() - INTERVAL '7 days'"
        )
    )
    session.flush()
    return saved


def load_staging_tables(
    session: Session,
    batch_id: str,
    uids: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    if not batch_id:
        return {}
    uid_list = [str(u) for u in (uids or []) if u]
    stmt = select(ExtractStaging).where(ExtractStaging.batch_id == batch_id)
    if uid_list:
        stmt = stmt.where(ExtractStaging.uid.in_(uid_list))
    out: dict[str, Any] = {}
    for row in session.scalars(stmt).all():
        raw = row.table_json
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                continue
        if isinstance(raw, dict):
            out[str(row.uid)] = raw
    return out
