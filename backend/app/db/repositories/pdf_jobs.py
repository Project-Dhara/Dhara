"""PDF job / table / grouping repository (SQLAlchemy)."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.orm import Session

from app.db.models.pdf import PdfJob, PdfTable, PdfTableGroup, PdfTableGroupMember

CLASSIFICATION_FIELDS = (
    "domain",
    "subject",
    "entity",
    "table_type",
    "geography",
    "time_period",
    "frequency",
    "unit",
)


def _class_value(field: Any) -> Optional[str]:
    if field is None:
        return None
    if isinstance(field, dict):
        v = field.get("value")
        return str(v).strip() if v is not None and str(v).strip() else None
    s = str(field).strip()
    return s or None


def classification_dict(table: dict) -> dict:
    out: dict[str, Any] = {}
    for key in CLASSIFICATION_FIELDS:
        if key in table:
            out[key] = table[key]
    if isinstance(table.get("classification"), dict):
        out = {**table["classification"], **out}
    return out


def flatten_classification_text(classification: dict) -> dict:
    flat = {}
    for key in CLASSIFICATION_FIELDS:
        flat[key] = _class_value(classification.get(key))
    return flat


def _json_obj(value: Any, default: Any) -> Any:
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


def _row_to_working_job(job: PdfJob) -> dict:
    epoch = job.created_at_epoch
    if epoch is None and job.created_at is not None:
        try:
            epoch = float(job.created_at.timestamp())
        except Exception:
            epoch = time.time()
    elif epoch is not None:
        epoch = float(epoch)
    else:
        epoch = time.time()
    return {
        "job_id": job.job_id,
        "status": job.status or "queued",
        "stage": job.stage or job.status or "queued",
        "percent": int(job.percent or 0),
        "message": job.message or "",
        "filename": job.filename,
        "user_email": job.user_email,
        "created_at": epoch,
        "result": _json_obj(job.result, None),
        "error": job.error,
        "reviews": _json_obj(job.reviews, {}) or {},
        "deleted_table_ids": _json_obj(job.deleted_table_ids, []) or [],
        "grouping_status": job.grouping_status,
        "pipeline_step": int(job.pipeline_step)
        if job.pipeline_step is not None
        else None,
        "source_type": job.source_type or "pdf",
        "organisation_id": str(job.organisation_id) if job.organisation_id else None,
    }


def _row_to_table(row: PdfTable) -> dict:
    classification = row.classification or {}
    if isinstance(classification, str):
        classification = json.loads(classification)
    flat = flatten_classification_text(classification)
    return {
        "id": str(row.id),
        "job_id": row.job_id,
        "table_id": row.table_id,
        "page": row.page,
        "title": row.title or "",
        "columns": row.columns or [],
        "rows": row.source_rows or [],
        "classification": classification,
        "domain": flat.get("domain"),
        "subject": flat.get("subject"),
        "entity": flat.get("entity"),
        "table_type": flat.get("table_type"),
        "geography": flat.get("geography"),
        "time_period": flat.get("time_period"),
        "frequency": flat.get("frequency"),
        "unit": flat.get("unit"),
        "human_review_needed": row.human_review_needed,
        "human_review_reason": row.human_review_reason,
        "semantic_status": row.semantic_status,
    }


def get_for_user(
    session: Session,
    job_id: str,
    *,
    user_email: str,
    organisation_id: uuid.UUID | None = None,
) -> PdfJob | None:
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


def upsert_job(
    session: Session,
    *,
    job_id: str,
    user_email: str,
    filename: Optional[str],
    status: str = "done",
) -> None:
    existing = session.get(PdfJob, job_id)
    if existing is None:
        session.add(
            PdfJob(
                job_id=job_id,
                user_email=user_email,
                filename=filename,
                status=status,
            )
        )
    else:
        existing.user_email = user_email
        if filename:
            existing.filename = filename
        existing.status = status
        existing.updated_at = datetime.now(timezone.utc)
    session.flush()


def save_working_job(
    session: Session,
    job: dict,
    *,
    pdf_bytes: Optional[bytes] = None,
    clear_pdf_bytes: bool = False,
) -> None:
    job_id = job["job_id"]
    created_epoch = float(job.get("created_at") or time.time())
    reviews = job.get("reviews") if isinstance(job.get("reviews"), dict) else {}
    deleted = (
        job.get("deleted_table_ids")
        if isinstance(job.get("deleted_table_ids"), list)
        else []
    )
    result = job.get("result")
    org_raw = job.get("organisation_id")
    org_id = uuid.UUID(str(org_raw)) if org_raw else None

    existing = session.get(PdfJob, job_id)
    if existing is None:
        existing = PdfJob(job_id=job_id, user_email=job.get("user_email") or "")
        session.add(existing)

    existing.user_email = job.get("user_email") or existing.user_email
    if job.get("filename"):
        existing.filename = job.get("filename")
    existing.status = job.get("status") or "queued"
    existing.stage = job.get("stage")
    existing.percent = int(job.get("percent") or 0)
    existing.message = job.get("message")
    existing.error = job.get("error")
    existing.result = result
    existing.reviews = reviews
    existing.deleted_table_ids = deleted
    existing.source_type = job.get("source_type") or existing.source_type or "pdf"
    if org_id is not None:
        existing.organisation_id = existing.organisation_id or org_id
    if existing.created_at_epoch is None:
        existing.created_at_epoch = created_epoch
    if pdf_bytes is not None or clear_pdf_bytes:
        existing.pdf_bytes = None if clear_pdf_bytes else pdf_bytes
    existing.updated_at = datetime.now(timezone.utc)
    session.flush()


def load_working_job(session: Session, job_id: str) -> Optional[dict]:
    job = session.get(PdfJob, job_id)
    return _row_to_working_job(job) if job else None


def list_working_jobs(session: Session, user_email: str) -> list[dict]:
    stmt = (
        select(PdfJob)
        .where(PdfJob.user_email == user_email)
        .order_by(
            func.coalesce(
                PdfJob.created_at_epoch,
                func.extract("epoch", PdfJob.created_at),
            ).desc().nullslast()
        )
    )
    return [_row_to_working_job(j) for j in session.scalars(stmt).all()]


def get_pdf_bytes(session: Session, job_id: str) -> Optional[bytes]:
    job = session.get(PdfJob, job_id)
    if not job or job.pdf_bytes is None:
        return None
    return bytes(job.pdf_bytes)


def set_pipeline_step(session: Session, job_id: str, step: int) -> None:
    step_i = max(1, min(6, int(step)))
    session.execute(
        text(
            """
            UPDATE pdf_jobs
               SET pipeline_step = GREATEST(COALESCE(pipeline_step, 0), :step),
                   updated_at = NOW()
             WHERE job_id = :job_id
            """
        ),
        {"step": step_i, "job_id": job_id},
    )
    session.flush()


def get_pipeline_step(session: Session, job_id: str) -> Optional[int]:
    job = session.get(PdfJob, job_id)
    if not job or job.pipeline_step is None:
        return None
    return int(job.pipeline_step)


def persist_approved_tables(
    session: Session,
    *,
    job_id: str,
    user_email: str,
    filename: Optional[str],
    tables: list[dict],
) -> list[dict]:
    upsert_job(
        session,
        job_id=job_id,
        user_email=user_email,
        filename=filename,
        status="done",
    )
    kept_ids: list[uuid.UUID] = []
    persisted: list[dict] = []
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

        existing = session.scalars(
            select(PdfTable).where(
                PdfTable.job_id == job_id, PdfTable.table_id == table_id
            )
        ).first()
        if existing is None:
            existing = PdfTable(
                id=uuid.uuid4(),
                job_id=job_id,
                table_id=table_id,
            )
            session.add(existing)
        existing.page = page_i
        existing.title = t.get("title")
        existing.source_rows = t.get("rows") or t.get("source_rows") or []
        existing.columns = t.get("columns") or []
        existing.classification = classification
        existing.human_review_needed = bool(t.get("human_review_needed"))
        existing.human_review_reason = t.get("human_review_reason")
        existing.semantic_status = t.get("semantic_status")
        existing.deleted_at = None
        existing.updated_at = datetime.now(timezone.utc)
        session.flush()
        kept_ids.append(existing.id)
        persisted.append(_row_to_table(existing))

    if kept_ids:
        session.execute(
            update(PdfTable)
            .where(
                PdfTable.job_id == job_id,
                PdfTable.deleted_at.is_(None),
                PdfTable.id.not_in(kept_ids),
            )
            .values(deleted_at=func.now(), updated_at=func.now())
        )
    else:
        session.execute(
            update(PdfTable)
            .where(PdfTable.job_id == job_id, PdfTable.deleted_at.is_(None))
            .values(deleted_at=func.now(), updated_at=func.now())
        )
    session.execute(
        text(
            """
            UPDATE pdf_jobs
               SET grouping_status = 'pending',
                   pipeline_step = GREATEST(COALESCE(pipeline_step, 0), 3),
                   updated_at = NOW()
             WHERE job_id = :job_id
            """
        ),
        {"job_id": job_id},
    )
    session.flush()
    return persisted


def list_active_tables(session: Session, job_id: str) -> list[dict]:
    stmt = (
        select(PdfTable)
        .where(PdfTable.job_id == job_id, PdfTable.deleted_at.is_(None))
        .order_by(PdfTable.page.nullslast(), PdfTable.table_id)
    )
    return [_row_to_table(r) for r in session.scalars(stmt).all()]


def get_job(session: Session, job_id: str) -> Optional[dict]:
    job = session.get(PdfJob, job_id)
    if not job:
        return None
    return {
        "job_id": job.job_id,
        "user_email": job.user_email,
        "filename": job.filename,
        "status": job.status,
        "grouping_status": job.grouping_status,
        "organisation_id": str(job.organisation_id) if job.organisation_id else None,
        "pipeline_step": job.pipeline_step,
        "source_type": job.source_type,
    }


def save_grouping(
    session: Session,
    *,
    job_id: str,
    groups: list[dict],
) -> None:
    session.execute(
        delete(PdfTableGroup).where(PdfTableGroup.job_id == job_id)
    )
    for i, g in enumerate(groups):
        gid = uuid.uuid4()
        name = (g.get("name") or f"Group {i + 1}").strip() or f"Group {i + 1}"
        session.add(
            PdfTableGroup(
                group_id=gid, job_id=job_id, name=name, sort_order=i
            )
        )
        session.flush()
        for pk in g.get("table_pks") or []:
            session.add(
                PdfTableGroupMember(
                    group_id=gid, table_pk=uuid.UUID(str(pk))
                )
            )
    session.execute(
        text(
            """
            UPDATE pdf_jobs
               SET grouping_status = 'saved',
                   pipeline_step = GREATEST(COALESCE(pipeline_step, 0), 4),
                   updated_at = NOW()
             WHERE job_id = :job_id
            """
        ),
        {"job_id": job_id},
    )
    session.flush()


def load_grouping(session: Session, job_id: str) -> dict:
    tables = {t["id"]: t for t in list_active_tables(session, job_id)}
    assigned: set[str] = set()
    groups_out: list[dict] = []
    group_rows = session.scalars(
        select(PdfTableGroup)
        .where(PdfTableGroup.job_id == job_id)
        .order_by(PdfTableGroup.sort_order, PdfTableGroup.name)
    ).all()
    for gr in group_rows:
        member_pks = session.scalars(
            select(PdfTableGroupMember.table_pk).where(
                PdfTableGroupMember.group_id == gr.group_id
            )
        ).all()
        members = []
        for pk in member_pks:
            pk_s = str(pk)
            if pk_s in tables:
                members.append(tables[pk_s])
                assigned.add(pk_s)
        groups_out.append(
            {
                "group_id": str(gr.group_id),
                "name": gr.name,
                "tables": members,
            }
        )
    unmatched = [t for tid, t in tables.items() if tid not in assigned]
    return {"groups": groups_out, "unmatched_tables": unmatched}
