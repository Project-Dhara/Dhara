"""Dedicated background job runner for extraction / upload batches.

HTTP routes enqueue work here instead of spawning ad-hoc event-loop tasks.
Jobs still run in-process today (same container as the API); the runner keeps
strong references, bounds concurrency, and logs failures so uploads are not
silently dropped.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_MAX_WORKERS = max(1, int(os.environ.get("DHARA_JOB_WORKERS", "2") or "2"))
_executor: Optional[ThreadPoolExecutor] = None
_inflight: set[Future[Any]] = set()


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=_MAX_WORKERS,
            thread_name_prefix="dhara-job",
        )
        logger.info("Started background job pool (workers=%s)", _MAX_WORKERS)
    return _executor


def _on_done(fut: Future[Any]) -> None:
    _inflight.discard(fut)
    try:
        fut.result()
    except Exception:
        logger.exception("Background job failed")


def submit_job(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future[Any]:
    """Run ``fn(*args, **kwargs)`` on the job thread pool. Returns immediately."""
    fut = _get_executor().submit(fn, *args, **kwargs)
    _inflight.add(fut)
    fut.add_done_callback(_on_done)
    return fut


def submit_extraction_job(
    job_id: str,
    file_bytes: bytes,
    source_type: str,
    api_key: Optional[str] = None,
) -> Future[Any]:
    """Enqueue a single-file extraction job (PDF / Excel / CSV)."""
    from app.workers.extraction_jobs import _run_extraction_job

    return submit_job(_run_extraction_job, job_id, file_bytes, source_type, api_key)


def submit_upload_batch(batch_id: str) -> Future[Any]:
    """Enqueue (or resume) a multi-file upload batch."""
    from app.workers.upload_batches import run_upload_batch

    return submit_job(run_upload_batch, batch_id)


def shutdown_job_runner(*, wait: bool = False) -> None:
    """Release the pool on process shutdown."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=wait, cancel_futures=False)
        _executor = None
    _inflight.clear()
