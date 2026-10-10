"""PDF job repository — scoped read helpers for tenant isolation."""
from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models.pdf import PdfJob


def get_for_user(
    session: Session,
    job_id: str,
    *,
    user_email: str,
    organisation_id: uuid.UUID | None = None,
) -> PdfJob | None:
    """Return a job owned by ``user_email`` within the caller's organisation."""
    stmt = select(PdfJob).where(
        PdfJob.job_id == job_id,
        PdfJob.user_email == user_email,
    )
    if organisation_id is not None:
        stmt = stmt.where(
            or_(
                PdfJob.organisation_id == organisation_id,
                PdfJob.organisation_id.is_(None),
            )
        )
    return session.scalars(stmt).first()


def list_for_user(
    session: Session,
    *,
    user_email: str,
    organisation_id: uuid.UUID | None = None,
) -> list[PdfJob]:
    stmt = select(PdfJob).where(PdfJob.user_email == user_email)
    if organisation_id is not None:
        stmt = stmt.where(
            or_(
                PdfJob.organisation_id == organisation_id,
                PdfJob.organisation_id.is_(None),
            )
        )
    stmt = stmt.order_by(PdfJob.updated_at.desc().nullslast())
    return list(session.scalars(stmt).all())
