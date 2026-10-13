"""Classification standards and NCO aliases (SQLAlchemy Session)."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.db.models.standards import (
    ClassificationStandard,
    ClassificationStandardCode,
    Nco2015Code,
    NcoValueAlias,
)


def list_standards(session: Session) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(ClassificationStandard).order_by(ClassificationStandard.name)
    ).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "description": r.description,
            "original_filename": r.original_filename,
            "row_count": r.row_count,
            "is_selected": r.is_selected,
            "uploaded_by": r.uploaded_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def get_selected_standard(session: Session) -> ClassificationStandard | None:
    return session.scalars(
        select(ClassificationStandard).where(
            ClassificationStandard.is_selected.is_(True)
        )
    ).first()


def select_standard(session: Session, standard_id: int) -> None:
    session.execute(
        update(ClassificationStandard).values(is_selected=False)
    )
    session.execute(
        update(ClassificationStandard)
        .where(ClassificationStandard.id == standard_id)
        .values(is_selected=True)
    )
    session.flush()


def delete_standard(session: Session, standard_id: int) -> bool:
    row = session.get(ClassificationStandard, standard_id)
    if not row:
        return False
    session.delete(row)
    session.flush()
    return True


def upsert_nco_alias(
    session: Session,
    *,
    normalized_value: str,
    level: str,
    code: str,
    title: Optional[str] = None,
    source: str = "steward",
) -> None:
    existing = session.get(NcoValueAlias, normalized_value)
    if existing is None:
        session.add(
            NcoValueAlias(
                normalized_value=normalized_value,
                level=level,
                code=code,
                title=title,
                source=source,
            )
        )
    else:
        existing.level = level
        existing.code = code
        existing.title = title
        existing.source = source
    session.flush()


def lookup_nco_code(session: Session, nco_code: str) -> dict[str, Any] | None:
    row = session.get(Nco2015Code, nco_code)
    if not row:
        return None
    return {
        "nco_code": row.nco_code,
        "occupation_title": row.occupation_title,
        "division_code": row.division_code,
        "division_title": row.division_title,
        "subdivision_code": row.subdivision_code,
        "subdivision_title": row.subdivision_title,
        "group_code": row.group_code,
        "group_title": row.group_title,
        "family_code": row.family_code,
        "family_title": row.family_title,
        "qp_nos_reference": row.qp_nos_reference,
    }


def count_standard_codes(session: Session, standard_id: int) -> int:
    return int(
        session.execute(
            text(
                "SELECT COUNT(*)::int FROM classification_standard_codes "
                "WHERE standard_id = :sid"
            ),
            {"sid": standard_id},
        ).scalar_one()
    )
