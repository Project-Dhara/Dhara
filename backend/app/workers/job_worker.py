"""Postgres-backed extraction + NCO match worker process.

Run::

    python -m app.workers.job_worker

Claims ``queued`` PDF jobs and NCO match jobs. NCO matching runs in a warm
child process (idle TTL, killed before PDF claim / on max runtime).
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import os
import signal
import threading
import time
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

from app.core.startup import ensure_runtime_config  # noqa: E402
from app.db.repositories import pdf_jobs as pdf_jobs_repo  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.services.classification.nco_match_jobs import (  # noqa: E402
    child_idle_sec,
    claim_next_nco_job,
    cleanup_old_jobs,
    finish_job,
    maintenance,
    update_job_progress,
    worker_max_runtime_sec,
    write_worker_status,
)
from app.workers.extraction_jobs import (  # noqa: E402
    _get_pdf_bytes,
    _get_pdf_job,
    _pdf_jobs,
    _pdf_jobs_lock,
    _run_extraction_job,
)
from app.workers.nco_match_child import run_child_loop  # noqa: E402
from app.workers.upload_batches import run_upload_batch  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [job-worker] %(message)s",
)
logger = logging.getLogger("dhara.job_worker")

_stop = False
_status_state = "idle"
_status_detail = ""
_status_lock = threading.Lock()

# Warm NCO child
_nco_proc: Optional[mp.Process] = None
_nco_in: Any = None
_nco_out: Any = None
_nco_busy = False
_nco_last_idle_at = 0.0
_nco_job_started_at = 0.0
_nco_current_job_id: Any = None


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


def _set_status(state: str, detail: str = "") -> None:
    global _status_state, _status_detail
    with _status_lock:
        _status_state = state
        _status_detail = detail


def _status_heartbeat_loop() -> None:
    while not _stop:
        with _status_lock:
            state, detail = _status_state, _status_detail
        try:
            write_worker_status(state, detail=detail)
        except Exception:
            logger.debug("status heartbeat failed", exc_info=True)
        time.sleep(2.0)


def _hydrate_claimed(job: dict) -> None:
    job_id = job["job_id"]
    with _pdf_jobs_lock:
        _pdf_jobs[job_id] = job


def _process_claimed(job: dict) -> None:
    job_id = str(job["job_id"])
    source_type = str(job.get("source_type") or "pdf")
    _hydrate_claimed(job)

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


def _nco_child_alive() -> bool:
    return _nco_proc is not None and _nco_proc.is_alive()


def _ensure_nco_child() -> None:
    global _nco_proc, _nco_in, _nco_out, _nco_last_idle_at
    if _nco_child_alive():
        return
    ctx = mp.get_context("spawn")
    _nco_in = ctx.Queue()
    _nco_out = ctx.Queue()
    _nco_proc = ctx.Process(
        target=run_child_loop,
        args=(_nco_in, _nco_out),
        name="nco-match-child",
        daemon=True,
    )
    _nco_proc.start()
    _nco_last_idle_at = time.monotonic()
    logger.info("Started NCO child pid=%s", _nco_proc.pid)


def _terminate_nco_child(*, reason: str) -> None:
    global _nco_proc, _nco_in, _nco_out, _nco_busy, _nco_current_job_id
    if not _nco_proc:
        return
    logger.info("Terminating NCO child (%s) pid=%s", reason, _nco_proc.pid)
    try:
        if _nco_in is not None and _nco_child_alive() and not _nco_busy:
            try:
                _nco_in.put_nowait(None)
            except Exception:
                pass
        if _nco_proc.is_alive():
            _nco_proc.terminate()
            _nco_proc.join(timeout=15)
        if _nco_proc.is_alive():
            _nco_proc.kill()
            _nco_proc.join(timeout=5)
    except Exception:
        logger.exception("Error terminating NCO child")
    _nco_proc = None
    _nco_in = None
    _nco_out = None
    _nco_busy = False
    _nco_current_job_id = None


def _maybe_idle_exit_nco_child() -> None:
    global _nco_last_idle_at
    if _nco_busy or not _nco_child_alive():
        return
    if _nco_last_idle_at <= 0:
        _nco_last_idle_at = time.monotonic()
        return
    if time.monotonic() - _nco_last_idle_at >= child_idle_sec():
        _terminate_nco_child(reason="idle TTL")


def _poll_nco_child_result() -> bool:
    """If child finished a job, persist outcome. Returns True if a job completed."""
    global _nco_busy, _nco_last_idle_at, _nco_current_job_id
    if not _nco_busy or _nco_out is None:
        return False
    try:
        msg = _nco_out.get_nowait()
    except Exception:
        # Check max runtime / dead child
        if _nco_job_started_at and (
            time.monotonic() - _nco_job_started_at > worker_max_runtime_sec()
        ):
            jid = _nco_current_job_id
            _terminate_nco_child(reason="max runtime")
            if jid is not None:
                with session_scope() as session:
                    finish_job(
                        session,
                        jid,
                        status="error",
                        error="worker max runtime exceeded",
                    )
            _set_status("idle")
            return True
        if not _nco_child_alive():
            jid = _nco_current_job_id
            _nco_busy = False
            _nco_current_job_id = None
            if jid is not None:
                with session_scope() as session:
                    finish_job(
                        session,
                        jid,
                        status="error",
                        error="NCO child exited unexpectedly",
                    )
            _set_status("idle")
            return True
        # Heartbeat while busy
        if _nco_current_job_id is not None:
            try:
                with session_scope() as session:
                    update_job_progress(session, _nco_current_job_id, heartbeat=True)
            except Exception:
                pass
        return False

    jid = msg.get("job_id") or _nco_current_job_id
    _nco_busy = False
    _nco_current_job_id = None
    _nco_last_idle_at = time.monotonic()
    try:
        with session_scope() as session:
            if msg.get("ok"):
                finish_job(session, jid, status="done", result=msg.get("result"))
                logger.info("NCO job %s done via child", jid)
            else:
                finish_job(
                    session,
                    jid,
                    status="error",
                    error=str(msg.get("error") or "NCO child error"),
                )
    finally:
        _set_status("idle")
    return True


def _start_nco_job_on_child(job: dict) -> None:
    global _nco_busy, _nco_job_started_at, _nco_current_job_id, _nco_last_idle_at
    _ensure_nco_child()
    assert _nco_in is not None
    # Serialize UUID / datetime for the child
    payload = dict(job)
    for key in ("id",):
        if key in payload:
            payload[key] = str(payload[key])
    for key in ("created_at", "claimed_at", "updated_at", "last_polled_at", "finished_at"):
        if payload.get(key) is not None:
            payload[key] = str(payload[key])
    _nco_in.put(payload)
    _nco_busy = True
    _nco_job_started_at = time.monotonic()
    _nco_current_job_id = job["id"]
    _set_status("busy:nco", detail=str(job["id"]))
    with session_scope() as session:
        update_job_progress(session, job["id"], stage="loading_model")


def claim_and_run_one() -> bool:
    """Claim at most one PDF job and run it. Returns True if work was done."""
    claimed: Optional[dict] = None
    with session_scope() as session:
        claimed = pdf_jobs_repo.claim_next_queued_job(session)
    if not claimed:
        return False

    # Free ~1.5–2 GB from warm idle NCO child before PDF RAM gate.
    if not _nco_busy and _nco_child_alive():
        _terminate_nco_child(reason="PDF claim preempts idle NCO child")
        time.sleep(0.5)

    _set_status("busy:pdf", detail=str(claimed.get("job_id") or ""))
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
    finally:
        _set_status("idle")
    return True


def run_forever() -> None:
    ensure_runtime_config()
    try:
        mp.set_start_method("spawn", force=True)
    except RuntimeError:
        pass

    with session_scope() as session:
        maintenance(session)

    hb = threading.Thread(target=_status_heartbeat_loop, name="worker-status-hb", daemon=True)
    hb.start()
    _set_status("idle")
    write_worker_status("idle")

    poll = _poll_seconds()
    logger.info(
        "Job worker started (poll=%ss). Waiting for queued pdf_jobs / nco_match…",
        poll,
    )
    tick = 0
    while not _stop:
        worked = False
        try:
            # Finish in-flight child results first.
            if _poll_nco_child_result():
                worked = True

            if not _nco_busy:
                with session_scope() as session:
                    nco_job = claim_next_nco_job(session)
                if nco_job:
                    _start_nco_job_on_child(nco_job)
                    worked = True
                else:
                    # Prefer NCO when idle; otherwise PDF.
                    worked = claim_and_run_one() or worked

            _maybe_idle_exit_nco_child()
            tick += 1
            if tick % 40 == 0:
                cleanup_old_jobs()
        except Exception:
            logger.exception("claim/run loop error")
        if not worked and not _nco_busy:
            time.sleep(poll)
        elif _nco_busy:
            time.sleep(min(0.5, poll))

    _terminate_nco_child(reason="worker stop")


def main() -> None:
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
    run_forever()


if __name__ == "__main__":
    main()
