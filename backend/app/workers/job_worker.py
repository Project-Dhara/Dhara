"""Postgres-backed extraction worker process.

Run::

    python -m app.workers.job_worker

Claims ``queued`` top-level jobs (PDF / Excel / CSV / batch), runs them, and
updates durable status in ``pdf_jobs``. Safe to run multiple replicas
(``FOR UPDATE SKIP LOCKED``).
"""
from __future__ import annotations

import logging
import os
import signal
import time
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

from app.core.startup import ensure_runtime_config  # noqa: E402
from app.db.repositories import pdf_jobs as pdf_jobs_repo  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.workers.extraction_jobs import (  # noqa: E402
    _get_pdf_bytes,
    _get_pdf_job,
    _pdf_jobs,
    _pdf_jobs_lock,
    _run_extraction_job,
)
from app.workers.upload_batches import run_upload_batch  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [job-worker] %(message)s",
)
logger = logging.getLogger("dhara.job_worker")

_stop = False


def _handle_stop(signum: int, _frame: Any) -> None:
    global _stop
    logger.info("Received signal %s — stopping after current job", signum)
    _stop = True


def _poll_seconds() -> float:
    raw = (os.environ.get("DHARA_WORKER_POLL_SECONDS") or "1.5").strip()
    try:
        return max(0.2, float(raw))
    except ValueError:
        return 1.5


def _hydrate_claimed(job: dict) -> None:
    job_id = job["job_id"]
    with _pdf_jobs_lock:
        _pdf_jobs[job_id] = job


def _process_claimed(job: dict) -> None:
    job_id = str(job["job_id"])
    source_type = str(job.get("source_type") or "pdf")
    _hydrate_claimed(job)

    # User may have cancelled between claim and run.
    live = _get_pdf_job(job_id) or job
    if str(live.get("status") or "") == "cancelled":
        logger.info("Skipping cancelled job %s", job_id)
        return

    if source_type == "batch":
        logger.info("Running batch job %s", job_id)
        run_upload_batch(job_id)
        return

    file_bytes = _get_pdf_bytes(job_id)
    if not file_bytes:
        logger.error("Job %s has no stored file bytes — marking error", job_id)
        live = _get_pdf_job(job_id) or job
        live.update(
            status="error",
            message="Failed: missing source file bytes",
            error="missing source file bytes",
        )
        with session_scope() as session:
            pdf_jobs_repo.save_working_job(session, live, clear_pdf_bytes=True)
        return

    logger.info("Running %s job %s (%s bytes)", source_type, job_id, len(file_bytes))
    _run_extraction_job(job_id, file_bytes, source_type)


def claim_and_run_one() -> bool:
    """Claim at most one job and run it. Returns True if work was done."""
    claimed: Optional[dict] = None
    with session_scope() as session:
        claimed = pdf_jobs_repo.claim_next_queued_job(session)
    if not claimed:
        return False
    try:
        _process_claimed(claimed)
    except Exception:
        logger.exception("Job %s failed in worker", claimed.get("job_id"))
        try:
            job_id = str(claimed.get("job_id") or "")
            live = _get_pdf_job(job_id) or dict(claimed)
            live.update(
                status="error",
                message="Failed in worker",
                error="worker exception",
            )
            with session_scope() as session:
                pdf_jobs_repo.save_working_job(session, live)
        except Exception:
            logger.exception("Could not persist failure for %s", claimed.get("job_id"))
    return True


def run_forever() -> None:
    ensure_runtime_config()
    poll = _poll_seconds()
    logger.info(
        "Job worker started (poll=%ss). Waiting for queued pdf_jobs…",
        poll,
    )
    while not _stop:
        worked = False
        try:
            worked = claim_and_run_one()
        except Exception:
            logger.exception("claim/run loop error")
        if not worked:
            time.sleep(poll)


def main() -> None:
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
    run_forever()


if __name__ == "__main__":
    main()
