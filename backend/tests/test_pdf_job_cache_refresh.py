"""API process must adopt worker progress written to Postgres."""
from __future__ import annotations

from unittest.mock import patch

from app.workers import extraction_jobs as jobs


def test_get_pdf_job_refreshes_stale_queued_cache_from_db():
    """Separate worker finishes in DB while API memory still says queued."""
    job_id = "stale-queued-job"
    cached = {
        "job_id": job_id,
        "status": "queued",
        "stage": "queued",
        "percent": 0,
        "message": "Queued",
        "filename": "6.pdf",
        "user_email": "u@example.org",
        "parent_batch_id": None,
        "dataset_id_config": {"prefix": "x"},
    }
    fresh = {
        "job_id": job_id,
        "status": "done",
        "stage": "done",
        "percent": 100,
        "message": "Complete",
        "filename": "6.pdf",
        "user_email": "u@example.org",
        "result": {"1": []},
    }
    with jobs._pdf_jobs_lock:
        jobs._pdf_jobs[job_id] = dict(cached)
    try:
        with patch.object(jobs, "_load_pdf_job", return_value=fresh) as load:
            out = jobs._get_pdf_job(job_id)
            load.assert_called_once_with(job_id)
        assert out is not None
        assert out["status"] == "done"
        assert out["percent"] == 100
        assert out["dataset_id_config"] == {"prefix": "x"}
        assert jobs._pdf_jobs[job_id]["status"] == "done"
    finally:
        with jobs._pdf_jobs_lock:
            jobs._pdf_jobs.pop(job_id, None)


def test_get_pdf_job_adopts_worker_progress_while_running():
    job_id = "running-progress-job"
    cached = {
        "job_id": job_id,
        "status": "queued",
        "stage": "queued",
        "percent": 0,
        "message": "Queued",
    }
    fresh = {
        "job_id": job_id,
        "status": "running",
        "stage": "extract",
        "percent": 30,
        "message": "Extracting",
    }
    with jobs._pdf_jobs_lock:
        jobs._pdf_jobs[job_id] = dict(cached)
    try:
        with patch.object(jobs, "_load_pdf_job", return_value=fresh):
            out = jobs._get_pdf_job(job_id)
        assert out["stage"] == "extract"
        assert out["percent"] == 30
    finally:
        with jobs._pdf_jobs_lock:
            jobs._pdf_jobs.pop(job_id, None)


def test_get_pdf_job_keeps_ahead_inline_memory():
    """Inline runner memory can be ahead of the last DB flush — don't regress."""
    job_id = "inline-ahead-job"
    cached = {
        "job_id": job_id,
        "status": "running",
        "stage": "extract",
        "percent": 45,
        "message": "Extracting",
    }
    stale_db = {
        "job_id": job_id,
        "status": "running",
        "stage": "extract",
        "percent": 30,
        "message": "Extracting",
    }
    with jobs._pdf_jobs_lock:
        jobs._pdf_jobs[job_id] = dict(cached)
    try:
        with patch.object(jobs, "_load_pdf_job", return_value=stale_db) as load:
            out = jobs._get_pdf_job(job_id)
            load.assert_called_once()
        assert out["percent"] == 45
        assert jobs._pdf_jobs[job_id]["percent"] == 45
    finally:
        with jobs._pdf_jobs_lock:
            jobs._pdf_jobs.pop(job_id, None)


def test_should_replace_cached_job_terminal_over_inflight():
    assert jobs._should_replace_cached_job(
        {"status": "queued", "percent": 0, "stage": "queued"},
        {"status": "done", "percent": 100, "stage": "done"},
    )
    assert not jobs._should_replace_cached_job(
        {"status": "running", "percent": 50, "stage": "extract"},
        {"status": "running", "percent": 40, "stage": "extract"},
    )
