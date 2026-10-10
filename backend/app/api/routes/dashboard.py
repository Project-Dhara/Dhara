"""Dashboard readiness (uploaded files + catalogue Excel/SQL) and pipeline
step tracking routes."""
import asyncio
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import CurrentUser, require_user
from app.db.repositories import pdf_jobs as pdf_jobs_repo
from app.db.session import session_scope
from app.services.catalogue.dashboard import list_dashboard
from app.workers.extraction_jobs import _get_pdf_job, _hydrate_user_pdf_jobs, _pdf_job_public, _pdf_jobs, _pdf_jobs_lock

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
        "source": "PDF",
        "product": "—",
        "job_id": job_id,
        "updated_at": job.get("created_at") or job.get("updated_at"),
    }

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
    if status == "error":
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
            "href": f"/console/grouping/{job_id}",
            "pipeline_step": 5,
        }
    if step >= 4:
        return {
            **base,
            "readiness_pct": 67,
            "status": "Metadata review",
            "status_key": "metadata_review",
            "action": "Review",
            "href": f"/console/grouping/{job_id}",
            "pipeline_step": 4,
        }
    if step >= 3:
        return {
            **base,
            "readiness_pct": 50,
            "status": "Harmonisation",
            "status_key": "harmonisation",
            "action": "Review",
            "href": f"/console/grouping/{job_id}",
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
        "href": f"/console/review/{job_id}",
        "pipeline_step": 2,
    }


@router.patch("/api/pdf/jobs/{job_id}/pipeline", tags=["PDF"])
async def pdf_set_pipeline_step(
    job_id: str, request: Request, user: CurrentUser = Depends(require_user)
):
    """Persist console pipeline step for dashboard readiness (steps 3–6)."""
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be a JSON object")
    try:
        step = int(body.get("step"))
    except (TypeError, ValueError):
        raise HTTPException(400, "step must be an integer 1–6")
    if step < 1 or step > 6:
        raise HTTPException(400, "step must be an integer 1–6")

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
    """
    user_email = user.email
    org_id = str(user.organisation_id)
    org_uuid = uuid.UUID(org_id)

    def _run():
        with session_scope() as session:
            base = list_dashboard(session, user_email)
            jobs = pdf_jobs_repo.list_for_user(
                session, user_email=user_email, organisation_id=org_uuid
            )
            pdf_db = {
                j.job_id: {
                    "job_id": j.job_id,
                    "filename": j.filename,
                    "status": j.status,
                    "grouping_status": j.grouping_status,
                    "pipeline_step": j.pipeline_step,
                    "created_at": j.created_at,
                    "updated_at": j.updated_at,
                    "organisation_id": j.organisation_id,
                }
                for j in jobs
            }
        return base, pdf_db

    base, pdf_db = await asyncio.to_thread(_run)

    with _pdf_jobs_lock:
        _hydrate_user_pdf_jobs(user_email)
        json_jobs = [
            _pdf_job_public(j)
            for j in _pdf_jobs.values()
            if _job_visible_to_org(j, user_email, org_id)
        ]

    seen = set()
    pdf_rows = []
    for job in json_jobs:
        jid = job.get("job_id")
        if not jid:
            continue
        seen.add(jid)
        db = pdf_db.get(jid) or {}
        step = db.get("pipeline_step")
        if step is None:
            step = job.get("pipeline_step")
        row = _pdf_dashboard_row(job, db.get("grouping_status"), step)
        if row:
            pdf_rows.append(row)

    for jid, db in pdf_db.items():
        if jid in seen:
            continue
        row = _pdf_dashboard_row({
            "job_id": jid,
            "filename": db.get("filename"),
            "status": db.get("status") or "done",
            "percent": 100,
            "created_at": db.get("updated_at") or db.get("created_at"),
            "needs_review_count": 0,
            "pipeline_step": db.get("pipeline_step"),
        }, db.get("grouping_status"), db.get("pipeline_step"))
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
