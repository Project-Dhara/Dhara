"""KYDS entries repository with tenant awareness."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.db.models.catalogue import KydsEntry


def save_entry(
    session: Session,
    *,
    responses: dict[str, Any],
    user_email: str,
    user_name: str | None,
    user_dept: str | None,
    organisation_id: uuid.UUID | None,
) -> KydsEntry:
    entry = KydsEntry(
        responses=responses,
        user_email=user_email,
        user_name=user_name,
        user_dept=user_dept,
        organisation_id=organisation_id,
    )
    session.add(entry)
    session.flush()
    return entry


def get_latest_for_user(
    session: Session,
    user_email: str,
    organisation_id: uuid.UUID | None = None,
) -> KydsEntry | None:
    stmt = (
        select(KydsEntry)
        .where(KydsEntry.user_email == user_email)
        .order_by(KydsEntry.created_at.desc())
        .limit(1)
    )
    if organisation_id is not None:
        stmt = stmt.where(
            (KydsEntry.organisation_id == organisation_id)
            | (KydsEntry.organisation_id.is_(None))
        )
    return session.scalars(stmt).first()


def get_latest_responses(
    session: Session,
    user_email: str,
    organisation_id: uuid.UUID | None = None,
) -> dict[str, Any] | None:
    """Return latest KYDS responses dict for metadata fill, or None."""
    entry = get_latest_for_user(
        session, user_email, organisation_id=organisation_id
    )
    return entry.responses if entry else None


def update_entry(
    session: Session,
    entry_id: int,
    user_email: str,
    responses: dict[str, Any],
    organisation_id: uuid.UUID | None = None,
) -> KydsEntry | None:
    stmt = select(KydsEntry).where(
        KydsEntry.id == entry_id, KydsEntry.user_email == user_email
    )
    if organisation_id is not None:
        stmt = stmt.where(
            (KydsEntry.organisation_id == organisation_id)
            | (KydsEntry.organisation_id.is_(None))
        )
    entry = session.scalars(stmt).first()
    if not entry:
        return None
    entry.responses = responses
    entry.updated_at = func.now()
    if organisation_id is not None and entry.organisation_id is None:
        entry.organisation_id = organisation_id
    session.flush()
    return entry
