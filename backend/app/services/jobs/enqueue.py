"""Enqueue extraction / batch jobs for the background worker.

By default jobs are persisted as ``queued`` and a separate worker process
claims them (``DHARA_INLINE_JOBS`` unset/false). Set ``DHARA_INLINE_JOBS=1``
to also run them in-process (API-only local runs without a worker).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _inline_jobs_enabled() -> bool:
    return (os.environ.get("DHARA_INLINE_JOBS") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def dispatch_extraction(
    *,
    job_id: str,
    filename: str,
    user_email: str,
    source_type: str,
    file_bytes: bytes,
    organisation_id: Optional[str] = None,
    user_id: Optional[str] = None,
    dataset_id_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Persist a queued job; optionally run inline. Returns public job ids."""
    from app.workers.extraction_jobs import queue_extraction_job
    from app.workers.runner import submit_extraction_job

    queue_extraction_job(
        job_id=job_id,
        filename=filename,
        user_email=user_email,
        source_type=source_type,
        file_bytes=file_bytes,
        organisation_id=organisation_id,
        user_id=user_id,
        dataset_id_config=dataset_id_config,
    )
    if _inline_jobs_enabled():
        logger.info("DHARA_INLINE_JOBS=1 — running job %s in API process", job_id)
        submit_extraction_job(job_id, file_bytes, source_type)
    else:
        logger.info("Queued extraction job %s for background worker", job_id)
    return {"job_id": job_id, "source_type": source_type}


def dispatch_upload_batch(
    *,
    batch_id: str,
    user_email: str,
    organisation_id: Optional[str],
    user_id: Optional[str],
    files: List[Tuple[str, str, bytes]],
    dataset_id_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Persist a queued batch; optionally run inline."""
    from app.workers.runner import submit_upload_batch
    from app.workers.upload_batches import queue_upload_batch

    queue_upload_batch(
        batch_id=batch_id,
        user_email=user_email,
        organisation_id=organisation_id,
        user_id=user_id,
        files=files,
        dataset_id_config=dataset_id_config,
    )
    if _inline_jobs_enabled():
        logger.info("DHARA_INLINE_JOBS=1 — running batch %s in API process", batch_id)
        submit_upload_batch(batch_id)
    else:
        logger.info("Queued upload batch %s for background worker", batch_id)
    return {
        "batch_id": batch_id,
        "job_id": batch_id,
        "file_count": len(files),
    }


def dispatch_batch_resume(batch_id: str) -> None:
    """Re-queue an existing batch (append/retry) for the worker or run inline."""
    from app.workers.extraction_jobs import _get_pdf_job, _pdf_jobs_lock, _save_pdf_job
    from app.workers.runner import submit_upload_batch

    with _pdf_jobs_lock:
        batch = _get_pdf_job(batch_id)
        if batch is not None and batch.get("status") not in (
            "queued",
            "running",
        ):
            batch.update(
                status="queued",
                stage="queued",
                message="Queued",
            )
            _save_pdf_job(batch)

    if _inline_jobs_enabled():
        submit_upload_batch(batch_id)
    else:
        logger.info("Re-queued batch %s for background worker", batch_id)
