"""Multi-file upload batches — one review job, per-file extraction children."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

from app.services.ingestion.review_tables import attach_batch_meta, merge_file_result_into_batch
from app.workers.extraction_jobs import (
    _get_pdf_job,
    _pdf_jobs,
    _pdf_jobs_lock,
    _run_extraction_job,
    _save_pdf_job,
    queue_extraction_job,
)

logger = logging.getLogger(__name__)

MAX_BATCH_FILE_CONCURRENCY = 2


def _batch_file_entry(
    *,
    file_job_id: str,
    filename: str,
    source_type: str,
    status: str = "queued",
    error: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "file_job_id": file_job_id,
        "filename": filename,
        "source_type": source_type,
        "status": status,
        "error": error,
    }


def _aggregate_batch_status(files: List[Dict[str, Any]]) -> Tuple[str, int, str]:
    if not files:
        return "failed", 0, "No files in batch"
    statuses = [f.get("status") for f in files]
    if any(s == "running" for s in statuses) or any(s == "queued" for s in statuses):
        done = sum(1 for s in statuses if s in ("done", "error"))
        pct = int(round(100 * done / len(files)))
        return "running", pct, f"Processing {done}/{len(files)} files"
    errors = [f for f in files if f.get("status") == "error"]
    ok = [f for f in files if f.get("status") == "done"]
    if ok and errors:
        return "completed_with_errors", 100, f"{len(ok)} succeeded, {len(errors)} failed"
    if ok:
        return "done", 100, "Complete"
    return "failed", 100, errors[0].get("error") if errors else "All files failed"


def queue_upload_batch(
    *,
    batch_id: str,
    user_email: str,
    organisation_id: Optional[str],
    user_id: Optional[str],
    files: List[Tuple[str, str, bytes]],
) -> None:
    """Register parent batch job and child file jobs. Caller starts ``run_upload_batch``."""
    batch_files = []
    for filename, source_type, content in files:
        file_job_id = uuid.uuid4().hex
        batch_files.append(_batch_file_entry(file_job_id=file_job_id, filename=filename, source_type=source_type))
        queue_extraction_job(
            job_id=file_job_id,
            filename=filename,
            user_email=user_email,
            source_type=source_type,
            file_bytes=content,
            organisation_id=organisation_id,
            user_id=user_id,
            persist_file_bytes=True,
            parent_batch_id=batch_id,
        )

    label = files[0][0] if len(files) == 1 else f"{len(files)} files"
    with _pdf_jobs_lock:
        _pdf_jobs[batch_id] = {
            "job_id": batch_id,
            "status": "queued",
            "stage": "queued",
            "percent": 0,
            "message": "Queued",
            "filename": label,
            "user_email": user_email,
            "organisation_id": organisation_id,
            "user_id": user_id,
            "source_type": "batch",
            "created_at": time.time(),
            "result": attach_batch_meta({}, {"batch_files": batch_files}),
            "error": None,
            "reviews": {},
            "deleted_table_ids": [],
            "batch_files": batch_files,
        }
        _save_pdf_job(_pdf_jobs[batch_id])


def _load_file_bytes(file_job_id: str) -> Optional[bytes]:
    from app.workers.extraction_jobs import _get_pdf_bytes

    return _get_pdf_bytes(file_job_id)


def _refresh_batch_merge(batch_id: str) -> None:
    with _pdf_jobs_lock:
        batch = _pdf_jobs.get(batch_id)
        if not batch:
            batch = _get_pdf_job(batch_id)
            if batch:
                _pdf_jobs[batch_id] = batch
        if not batch:
            return
        meta = (batch.get("result") or {}).get("__batch_meta__") or {}
        files = meta.get("batch_files") or batch.get("batch_files") or []
        merged: Dict[Any, Any] = {}
        for i, f in enumerate(files):
            if f.get("status") != "done":
                continue
            child = _get_pdf_job(f["file_job_id"])
            if not child or not child.get("result"):
                continue
            merge_file_result_into_batch(
                merged,
                i,
                child["result"],
                source_filename=f.get("filename") or "",
                source_file_id=f["file_job_id"],
                source_type=f.get("source_type") or "pdf",
            )
        batch["result"] = attach_batch_meta(merged, {"batch_files": files})
        batch["batch_files"] = files
        status, pct, message = _aggregate_batch_status(files)
        if status in ("done", "completed_with_errors"):
            batch.update(status=status, stage="done", percent=pct, message=message)
        elif status == "failed":
            batch.update(status="failed", stage="failed", percent=pct, message=message, error=message)
        else:
            batch.update(status=status, stage="extract", percent=pct, message=message)
        _save_pdf_job(batch)


def run_upload_batch(batch_id: str) -> None:
    """Process all queued/running files in a batch with bounded concurrency."""
    batch = _get_pdf_job(batch_id)
    if not batch:
        logger.warning("upload batch %s not found", batch_id)
        return

    meta = (batch.get("result") or {}).get("__batch_meta__") or {}
    files: List[Dict[str, Any]] = list(meta.get("batch_files") or batch.get("batch_files") or [])

    def process_one(file_entry: Dict[str, Any], file_index: int) -> None:
        fid = file_entry["file_job_id"]
        if file_entry.get("status") == "done":
            return
        content = _load_file_bytes(fid)
        if not content:
            with _pdf_jobs_lock:
                file_entry["status"] = "error"
                file_entry["error"] = "File data missing — re-upload this file"
            return
        with _pdf_jobs_lock:
            file_entry["status"] = "running"
        try:
            _run_extraction_job(fid, content, file_entry["source_type"])
            child = _get_pdf_job(fid)
            if child and child.get("status") == "done":
                with _pdf_jobs_lock:
                    file_entry["status"] = "done"
                    file_entry["error"] = None
            else:
                with _pdf_jobs_lock:
                    file_entry["status"] = "error"
                    file_entry["error"] = (child or {}).get("error") or "Extraction failed"
        except Exception as e:
            logger.exception("batch file %s failed", fid)
            with _pdf_jobs_lock:
                file_entry["status"] = "error"
                file_entry["error"] = str(e)
        _refresh_batch_merge(batch_id)

    with _pdf_jobs_lock:
        batch["status"] = "running"
        batch["message"] = "Starting extraction"
        _save_pdf_job(batch)

    pending = [(i, f) for i, f in enumerate(files) if f.get("status") not in ("done",)]
    with ThreadPoolExecutor(max_workers=MAX_BATCH_FILE_CONCURRENCY) as pool:
        futures = [pool.submit(process_one, f, i) for i, f in pending]
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                logger.warning("batch worker future failed: %s", e)

    with _pdf_jobs_lock:
        batch = _pdf_jobs.get(batch_id) or _get_pdf_job(batch_id)
        if batch:
            meta = (batch.get("result") or {}).get("__batch_meta__") or {}
            files = meta.get("batch_files") or files
            status, pct, message = _aggregate_batch_status(files)
            batch["batch_files"] = files
            batch["result"] = attach_batch_meta(
                {k: v for k, v in (batch.get("result") or {}).items() if k != "__batch_meta__"},
                {"batch_files": files},
            )
            batch.update(status=status, stage="done" if status != "running" else "extract", percent=pct, message=message)
            if status == "failed":
                batch["error"] = message
            _save_pdf_job(batch)


def retry_batch_file(batch_id: str, file_job_id: str) -> None:
    """Re-run one failed file without reprocessing successful siblings."""
    batch = _get_pdf_job(batch_id)
    if not batch:
        raise ValueError("Batch not found")
    meta = (batch.get("result") or {}).get("__batch_meta__") or {}
    files: List[Dict[str, Any]] = list(meta.get("batch_files") or [])
    target = next((f for f in files if f.get("file_job_id") == file_job_id), None)
    if not target:
        raise ValueError("File not in batch")
    target["status"] = "queued"
    target["error"] = None
    with _pdf_jobs_lock:
        batch["batch_files"] = files
        batch["result"] = attach_batch_meta(
            {k: v for k, v in (batch.get("result") or {}).items() if k != "__batch_meta__"},
            {"batch_files": files},
        )
        batch["status"] = "running"
        _save_pdf_job(batch)

    t = threading.Thread(target=_retry_one, args=(batch_id, target), daemon=True)
    t.start()


def _retry_one(batch_id: str, file_entry: Dict[str, Any]) -> None:
    fid = file_entry["file_job_id"]
    content = _load_file_bytes(fid)
    if not content:
        file_entry["status"] = "error"
        file_entry["error"] = "File data missing"
        _refresh_batch_merge(batch_id)
        return
    file_entry["status"] = "running"
    _run_extraction_job(fid, content, file_entry["source_type"])
    child = _get_pdf_job(fid)
    if child and child.get("status") == "done":
        file_entry["status"] = "done"
        file_entry["error"] = None
    else:
        file_entry["status"] = "error"
        file_entry["error"] = (child or {}).get("error") or "Extraction failed"
    _refresh_batch_merge(batch_id)
