"""PDF review → persist → grouping workflows (shared by HTTP routes)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.exceptions import AppError, NotFoundError
from app.db.repositories import pdf_jobs as pdf_jobs_repo
from app.db.session import session_scope
from app.services.grouping import pdf_grouping
from app.workers.extraction_jobs import (
    _get_pdf_job,
    _pdf_jobs_lock,
    _pdf_tables_from_job,
    _save_pdf_job,
    job_extraction_complete,
)


def persist_approved_and_group(
    *,
    job_id: str,
    user_email: str,
    api_key: Optional[str] = None,
    tables_overlay: Optional[List[Dict[str, Any]]] = None,
    approved_table_ids: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """Write approved Preview tables and propose/apply grouping.

    Same behaviour as the former inline route handler.
    """
    with _pdf_jobs_lock:
        job = _get_pdf_job(job_id)
        if not job or job.get("user_email") != user_email:
            raise NotFoundError("Job not found")
        if not job_extraction_complete(job.get("status")):
            raise AppError(
                f"Job not finished yet (status={job.get('status')})",
                status_code=409,
            )
        tables = _pdf_tables_from_job(job)
        filename = job.get("filename")

        if isinstance(tables_overlay, list) and tables_overlay:
            by_id = {
                str(t.get("table_id")): t
                for t in tables_overlay
                if isinstance(t, dict) and t.get("table_id")
            }
            overlay_keys = (
                "title",
                "rows",
                "columns",
                "classification",
                "human_review_needed",
                "human_review_reason",
                "semantic_status",
            )
            reviews = dict(job.get("reviews") or {})
            for t in tables:
                tid = str(t.get("table_id") or "")
                override = by_id.get(tid)
                if not override:
                    continue
                patch = {k: override[k] for k in overlay_keys if k in override}
                t.update(patch)
                reviews[tid] = {**reviews.get(tid, {}), **patch}
            job["reviews"] = reviews
            _save_pdf_job(job)

        if isinstance(approved_table_ids, list) and approved_table_ids:
            allowed = {str(tid) for tid in approved_table_ids if tid}
            tables = [t for t in tables if str(t.get("table_id") or "") in allowed]
            if not tables:
                raise AppError("No approved tables matched this job", status_code=400)

    with session_scope() as session:
        persisted = pdf_jobs_repo.persist_approved_tables(
            session,
            job_id=job_id,
            user_email=user_email,
            filename=filename,
            tables=tables,
        )
        proposal = pdf_grouping.propose_groups(
            session, job_id, api_key=api_key, reindex=True
        )
        grouping = pdf_grouping.apply_proposal_to_db(session, job_id, proposal)
        return {
            "ok": True,
            "job_id": job_id,
            "table_count": len(persisted),
            "grouping": grouping,
        }
