"""Dashboard readiness (catalogue groups + in-flight PDF jobs) and pipeline
step tracking routes."""
import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
import psycopg2.extras

from catalogue import catalogue as _cat
from core.deps import require_user
from pdf.pdf_jobs import _get_pdf_job, _hydrate_user_pdf_jobs, _pdf_job_public, _pdf_jobs, _pdf_jobs_lock

router = APIRouter()


def _pdf_dashboard_row(
    job: Dict[str, Any],
    grouping_status: Optional[str] = None,
    pipeline_step: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Map a PDF extraction job into a Dashboard readiness row.

    Console steps: 1 Files → 2 Preview → 3 Grouping → 4 Metadata → 5 Classify → 6 Publish.
    Returns None when the job should be represented by catalogue rows instead
    (metadata already pushed / classify+).
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

    # After Metadata push the catalogue rows are the accurate readiness view.
    if step >= 5:
        return None

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
async def pdf_set_pipeline_step(job_id: str, request: Request, user_email: str = Depends(require_user)):
    """Persist console pipeline step for dashboard readiness (steps 3–6)."""
    from pdf import pdf_store

    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be a JSON object")
    try:
        step = int(body.get("step"))
    except (TypeError, ValueError):
        raise HTTPException(400, "step must be an integer 1–6")
    if step < 1 or step > 6:
        raise HTTPException(400, "step must be an integer 1–6")

    def _run():
        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            pdf_store.init_pdf_schema(conn)
            job_row = pdf_store.get_job(conn, job_id)
            if not job_row or job_row.get("user_email") != user_email:
                with _pdf_jobs_lock:
                    mem = _get_pdf_job(job_id)
                if not mem or mem.get("user_email") != user_email:
                    return None
                pdf_store.upsert_job(
                    conn,
                    job_id=job_id,
                    user_email=user_email,
                    filename=mem.get("filename"),
                    status=mem.get("status") or "done",
                )
            pdf_store.set_pipeline_step(conn, job_id, step)
            return pdf_store.get_pipeline_step(conn, job_id)
        finally:
            conn.close()

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
async def get_dashboard(user_email: str = Depends(require_user)):
    """Dataset readiness for the Dashboard: catalogue groups + in-flight PDF jobs."""
    from pdf import pdf_store

    def _run():
        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            pdf_store.init_pdf_schema(conn)
            base = _cat.list_dashboard(conn, user_email)
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT job_id, filename, status, grouping_status, pipeline_step,
                           created_at, updated_at
                    FROM pdf_jobs
                    WHERE user_email = %s
                    ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
                    """,
                    (user_email,),
                )
                pdf_db = {r["job_id"]: dict(r) for r in cur.fetchall()}
        finally:
            conn.close()
        return base, pdf_db

    base, pdf_db = await asyncio.to_thread(_run)

    with _pdf_jobs_lock:
        _hydrate_user_pdf_jobs(user_email)
        json_jobs = [
            _pdf_job_public(j)
            for j in _pdf_jobs.values()
            if j.get("user_email") == user_email
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

    awaiting_extra = sum(
        1 for r in pdf_rows
        if r.get("status_key") not in ("failed", "published")
    )

    rows = list(pdf_rows) + list(base.get("rows") or [])
    stats = dict(base.get("stats") or {})
    stats["awaiting_review"] = int(stats.get("awaiting_review") or 0) + awaiting_extra
    stats["datasets"] = int(stats.get("datasets") or 0) + len(pdf_rows)

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
