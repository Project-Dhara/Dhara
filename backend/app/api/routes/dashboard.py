"""Dashboard readiness (uploaded files + catalogue Excel/SQL) and pipeline
step tracking routes."""
import asyncio
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import CurrentUser, require_user
from app.db.repositories import pdf_jobs as pdf_jobs_repo
from app.db.session import session_scope
from app.schemas.jobs import PipelineStepRequest
from app.services.catalogue.dashboard import _infer_source_label, list_dashboard
from app.workers.extraction_jobs import (
    _IN_FLIGHT_STATUSES,
    _TERMINAL_STATUSES,
    _get_pdf_job,
    _pdf_jobs,
    _pdf_jobs_lock,
)

router = APIRouter()


def _job_visible_to_org(job: dict, user_email: str, org_id: str) -> bool:
    if job.get("user_email") != user_email:
        return False
    job_org = job.get("organisation_id")
    if job_org and str(job_org) != org_id:
        return False
    return True


def _pdf_dashboard_row(
    job: Dict[str, Any],
    grouping_status: Optional[str] = None,
    pipeline_step: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Map a PDF upload job into a Dashboard readiness row (one row per file).

    Console steps: 1 Files → 2 Preview → 3 Grouping → 4 Metadata → 5 Classify → 6 Publish.
    Jobs stay visible through classify/publish so stewards can resume from the
    uploaded file rather than from each catalogue table/group.
    """
    job_id = job.get("job_id") or ""
    name = (job.get("filename") or "PDF upload").rsplit("/", 1)[-1]
    status = str(job.get("status") or "")
    percent = int(job.get("percent") or 0)
    needs_review = int(job.get("needs_review_count") or 0)
    table_count = int(job.get("table_count") or 0)
    gs = (grouping_status or "").strip().lower()
    step = pipeline_step if pipeline_step is not None else job.get("pipeline_step")
    try:
        step = int(step) if step is not None else None
    except (TypeError, ValueError):
        step = None

    base = {
        "id": f"pdf:{job_id}",
        "kind": "pdf_job",
        "name": name,
        "source": _infer_source_label(name, fallback="PDF"),
        "product": "—",
        "job_id": job_id,
        "updated_at": job.get("created_at") or job.get("updated_at"),
    }
    # Non-published finished jobs reopen at Preview so stewards can always
    # inspect stored PDF/Excel/CSV tables; later stages stay reachable via the
    # Console stage rail.
    preview_href = f"/console/review/{job_id}"

    if status in ("queued", "running"):
        # Step 1 — extraction in progress (cap below Preview).
        return {
            **base,
            "readiness_pct": max(5, min(int(round(percent * 0.2)), 20)),
            "status": "Processing",
            "status_key": "processing",
            "action": "View",
            "href": f"/console/processing/{job_id}",
            "pipeline_step": 1,
        }
    if status == "cancelled":
        # Abandoned via Start over — keep out of the Dashboard list.
        return None
    if status in ("error", "failed"):
        return {
            **base,
            "readiness_pct": max(5, min(percent, 20)),
            "status": "Failed",
            "status_key": "failed",
            "action": "View",
            "href": f"/console/processing/{job_id}",
            "pipeline_step": 1,
        }

    # Infer step when not explicitly stored (older jobs).
    if step is None:
        if gs == "saved":
            step = 4  # grouping finished → Metadata
        elif grouping_status is not None:
            step = 3  # persisted tables, grouping in progress
        else:
            step = 2  # extraction done, Preview
    elif gs == "saved" and step < 4:
        # Grouping Continue always advances into Metadata.
        step = 4

    if step >= 6:
        return {
            **base,
            "readiness_pct": 100,
            "status": "Published",
            "status_key": "published",
            "action": "View",
            "href": "/catalogue",
            "pipeline_step": 6,
        }
    if step >= 5:
        return {
            **base,
            "readiness_pct": 85,
            "status": "Classification review",
            "status_key": "classification_review",
            "action": "Review",
            "href": preview_href,
            "pipeline_step": 5,
        }
    if step >= 4:
        return {
            **base,
            "readiness_pct": 67,
            "status": "Metadata review",
            "status_key": "metadata_review",
            "action": "Review",
            "href": preview_href,
            "pipeline_step": 4,
        }
    if step >= 3:
        return {
            **base,
            "readiness_pct": 50,
            "status": "Harmonisation",
            "status_key": "harmonisation",
            "action": "Review",
            "href": preview_href,
            "pipeline_step": 3,
        }

    # Step 2 — Preview / table review
    if table_count > 0:
        cleared = max(0, table_count - needs_review)
        pct = int(round(25 + (cleared / table_count) * 10))  # 25–35%
    else:
        pct = 30
    label = "Table review" if needs_review > 0 else "Preview"
    return {
        **base,
        "readiness_pct": pct,
        "status": label,
        "status_key": "table_review",
        "action": "Review",
        "href": preview_href,
        "pipeline_step": 2,
    }


@router.patch("/api/pdf/jobs/{job_id}/pipeline", tags=["PDF"])
async def pdf_set_pipeline_step(
    job_id: str,
    body: PipelineStepRequest,
    user: CurrentUser = Depends(require_user),
):
    """Persist console pipeline step for dashboard readiness (steps 3–6)."""
    step = body.step

    user_email = user.email
    org_id = str(user.organisation_id)

    def _run():
        with session_scope() as session:
            job_row = pdf_jobs_repo.get_job(session, job_id)
            if not job_row or job_row.get("user_email") != user_email:
                with _pdf_jobs_lock:
                    mem = _get_pdf_job(job_id)
                if not mem or mem.get("user_email") != user_email:
                    return None
                job_org = mem.get("organisation_id")
                if job_org and str(job_org) != org_id:
                    return None
                pdf_jobs_repo.upsert_job(
                    session,
                    job_id=job_id,
                    user_email=user_email,
                    filename=mem.get("filename"),
                    status=mem.get("status") or "done",
                )
            else:
                job_org = job_row.get("organisation_id")
                if job_org and str(job_org) != org_id:
                    return None
            pdf_jobs_repo.set_pipeline_step(session, job_id, step)
            return pdf_jobs_repo.get_pipeline_step(session, job_id)

    try:
        saved = await asyncio.to_thread(_run)
    except Exception as e:
        raise HTTPException(500, f"Could not save pipeline step: {e}")
    if saved is None:
        raise HTTPException(404, "Job not found")

    with _pdf_jobs_lock:
        job = _get_pdf_job(job_id)
        if job is not None:
            job["pipeline_step"] = saved

    return {"ok": True, "job_id": job_id, "pipeline_step": saved}


@router.get("/api/dashboard", tags=["Dashboard"])
async def get_dashboard(user: CurrentUser = Depends(require_user)):
    """Upload readiness for the Dashboard: one row per uploaded file.

    PDF jobs are always listed (filename + resume link). Catalogue groups are
    included only for Excel/SQL (or when the user has no PDF uploads), so a
    single PDF is not exploded into many table/group rows.

    Uses summary job rows (no full ``result`` JSON hydrate). Live in-memory
    jobs overlay status/percent for in-flight uploads; Console/Review still
    load full payloads on demand.
    """
    user_email = user.email
    org_id = str(user.organisation_id)
    org_uuid = uuid.UUID(org_id)

    def _run():
        with session_scope() as session:
            base = list_dashboard(session, user_email)
            summaries = pdf_jobs_repo.list_dashboard_job_summaries(
                session, user_email=user_email, organisation_id=org_uuid
            )
        return base, summaries

    base, summaries = await asyncio.to_thread(_run)
    pdf_db = {s["job_id"]: s for s in summaries if s.get("job_id")}

    # Overlay live in-memory progress without hydrating every Postgres result.
    # Never let a stale API-process "queued"/"running" cache override a terminal
    # DB row written by the background worker.
    with _pdf_jobs_lock:
        for job in _pdf_jobs.values():
            if not _job_visible_to_org(job, user_email, org_id):
                continue
            jid = job.get("job_id")
            if not jid:
                continue
            existing = pdf_db.get(jid) or {}
            mem_status = str(job.get("status") or "")
            db_status = str(existing.get("status") or "")
            if db_status in _TERMINAL_STATUSES and mem_status in _IN_FLIGHT_STATUSES:
                continue
            if mem_status in _IN_FLIGHT_STATUSES and db_status in _IN_FLIGHT_STATUSES:
                mem_pct = int(job.get("percent") or 0)
                db_pct = int(existing.get("percent") or 0)
                use_mem = mem_pct >= db_pct
            else:
                use_mem = bool(mem_status)
            if not use_mem and existing:
                continue
            pdf_db[jid] = {
                **existing,
                "job_id": jid,
                "filename": job.get("filename") or existing.get("filename"),
                "status": (mem_status if use_mem else db_status) or "queued",
                "percent": int(
                    job.get("percent")
                    if use_mem and job.get("percent") is not None
                    else existing.get("percent")
                    or 0
                ),
                "grouping_status": existing.get("grouping_status")
                if existing.get("grouping_status") is not None
                else job.get("grouping_status"),
                "pipeline_step": existing.get("pipeline_step")
                if existing.get("pipeline_step") is not None
                else job.get("pipeline_step"),
                "created_at": existing.get("created_at") or job.get("created_at"),
                "updated_at": existing.get("updated_at") or job.get("created_at"),
                "organisation_id": existing.get("organisation_id")
                or job.get("organisation_id"),
                "table_count": int(
                    existing.get("table_count")
                    if existing.get("table_count") is not None
                    else job.get("table_count")
                    or 0
                ),
                "needs_review_count": int(
                    existing.get("needs_review_count")
                    if existing.get("needs_review_count") is not None
                    else job.get("needs_review_count")
                    or 0
                ),
            }

    pdf_rows = []
    for jid, db in pdf_db.items():
        if str(db.get("status") or "") == "cancelled":
            continue
        row = _pdf_dashboard_row(
            {
                "job_id": jid,
                "filename": db.get("filename"),
                "status": db.get("status") or "done",
                "percent": int(db.get("percent") or 0),
                "created_at": db.get("updated_at") or db.get("created_at"),
                "table_count": int(db.get("table_count") or 0),
                "needs_review_count": int(db.get("needs_review_count") or 0),
                "pipeline_step": db.get("pipeline_step"),
            },
            db.get("grouping_status"),
            db.get("pipeline_step"),
        )
        if row:
            pdf_rows.append(row)
    catalogue_rows = list(base.get("rows") or [])
    if pdf_rows:
        # PDF uploads already cover that file end-to-end. Keep catalogue rows
        # only when they clearly came from Excel/SQL so mixed workspaces still
        # show non-PDF uploads.
        catalogue_rows = [
            r for r in catalogue_rows
            if str(r.get("source") or "").upper() in ("XLSX", "CSV", "SQL")
        ]

    awaiting_pdf = sum(
        1 for r in pdf_rows
        if r.get("status_key") not in ("failed", "published")
    )
    published_pdf = sum(1 for r in pdf_rows if r.get("status_key") == "published")
    awaiting_cat = sum(
        1 for r in catalogue_rows
        if r.get("status_key") not in ("failed", "published")
    )
    published_cat = sum(1 for r in catalogue_rows if r.get("status_key") == "published")

    rows = list(pdf_rows) + catalogue_rows
    stats = dict(base.get("stats") or {})
    # One "dataset" on the dashboard = one uploaded file (or Excel/SQL group).
    stats["datasets"] = len(rows)
    stats["awaiting_review"] = awaiting_pdf + awaiting_cat
    stats["published"] = published_pdf + published_cat

    def _sort_key(r):
        u = r.get("updated_at")
        if isinstance(u, (int, float)):
            return float(u)
        if hasattr(u, "timestamp"):
            try:
                return float(u.timestamp())
            except Exception:
                return 0.0
        if isinstance(u, str):
            try:
                from datetime import datetime
                return datetime.fromisoformat(u.replace("Z", "+00:00")).timestamp()
            except Exception:
                return 0.0
        return 0.0

    rows.sort(key=_sort_key, reverse=True)
    return {"stats": stats, "rows": rows}
