"""PDF extraction/classification pipeline job bookkeeping (upload -> background
job -> review).

Unlike the xlsx batch-extract flow, this can take several minutes (pymupdf
extraction + batched OpenAI reconstruction/classification -- see
extraction.pdf_extraction), far longer than a synchronous request should
block for. Jobs are cached in memory here for live progress and persisted to
Postgres (pdf_store) -- never under backend/data/. Pipeline runs use ephemeral
temp files that are deleted when extraction finishes.

`_pdf_jobs` / `_pdf_jobs_lock` are shared, in-process state -- imported by
both routes_pdf.py and routes_dashboard.py, so there is exactly one copy.
"""
import pathlib
import re
import tempfile
import threading
from typing import Any, Dict, List, Optional, Tuple

from catalogue import catalogue as _cat
from data_ingestion import resolve_source_type, run_upload_pipeline
from pdf import pdf_store as _pdf_store

_pdf_jobs: Dict[str, Dict[str, Any]] = {}
_pdf_jobs_lock = threading.Lock()


def _pdf_db_conn():
    conn = _cat.get_connection()
    _cat.init_schema(conn)
    _pdf_store.init_pdf_schema(conn)
    return conn


def _save_pdf_job(
    job: Dict[str, Any],
    *,
    pdf_bytes: Optional[bytes] = None,
    clear_pdf_bytes: bool = False,
) -> None:
    """Persist working job state to Postgres (best-effort)."""
    try:
        conn = _pdf_db_conn()
        try:
            _pdf_store.save_working_job(
                conn, job, pdf_bytes=pdf_bytes, clear_pdf_bytes=clear_pdf_bytes,
            )
        finally:
            conn.close()
    except Exception as e:
        print(f"Warning: could not persist PDF job {job.get('job_id')}: {e}", flush=True)


def _load_pdf_job(job_id: str) -> Optional[Dict[str, Any]]:
    try:
        conn = _pdf_db_conn()
        try:
            return _pdf_store.load_working_job(conn, job_id)
        finally:
            conn.close()
    except Exception as e:
        print(f"Warning: could not load PDF job {job_id}: {e}", flush=True)
        return None


def _list_pdf_jobs_for_user(user_email: str) -> List[Dict[str, Any]]:
    try:
        conn = _pdf_db_conn()
        try:
            return _pdf_store.list_working_jobs(conn, user_email)
        finally:
            conn.close()
    except Exception as e:
        print(f"Warning: could not list PDF jobs: {e}", flush=True)
        return []


def _get_pdf_bytes(job_id: str) -> Optional[bytes]:
    try:
        conn = _pdf_db_conn()
        try:
            return _pdf_store.get_pdf_bytes(conn, job_id)
        finally:
            conn.close()
    except Exception as e:
        print(f"Warning: could not load PDF bytes for {job_id}: {e}", flush=True)
        return None


def _get_pdf_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Prefer in-memory job; fall back to Postgres after a process restart."""
    job = _pdf_jobs.get(job_id)
    if job is not None:
        return job
    job = _load_pdf_job(job_id)
    if job is not None:
        _pdf_jobs[job_id] = job
    return job


def _hydrate_user_pdf_jobs(user_email: str) -> None:
    """Ensure this user's Postgres jobs are present in the in-memory cache."""
    for job in _list_pdf_jobs_for_user(user_email):
        jid = job.get("job_id")
        if not jid:
            continue
        # Prefer live in-memory progress over a stale DB snapshot.
        if jid not in _pdf_jobs:
            _pdf_jobs[jid] = job


def _pdf_job_public(job: Dict[str, Any]) -> Dict[str, Any]:
    """Status view of a job -- everything except the (potentially large)
    result payload, which has its own endpoint."""
    public = {
        k: v for k, v in job.items()
        if k not in ("result", "reviews", "deleted_table_ids", "pdf_bytes")
    }
    if job.get("status") == "done" and job.get("result") is not None:
        deleted = set(job.get("deleted_table_ids") or [])
        tables = []
        for page_num, page in job["result"].items():
            for idx, t in enumerate(page.get("tables", [])):
                table_id = f"{page_num}-{idx}"
                if table_id not in deleted:
                    tables.append(t)
        public["table_count"] = len(tables)
        public["needs_review_count"] = sum(1 for t in tables if t.get("human_review_needed"))
    return public


_SUFFIX_BY_TYPE = {"pdf": ".pdf", "excel": ".xlsx", "csv": ".csv"}


def queue_extraction_job(
    *,
    job_id: str,
    filename: str,
    user_email: str,
    source_type: str,
    file_bytes: bytes,
) -> None:
    """Register an in-memory job and persist initial state (caller starts the worker)."""
    with _pdf_jobs_lock:
        _pdf_jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "stage": "queued",
            "percent": 0,
            "message": "Queued",
            "filename": filename,
            "user_email": user_email,
            "source_type": source_type,
            "created_at": time.time(),
            "result": None,
            "error": None,
            "reviews": {},
            "deleted_table_ids": [],
        }
        store_bytes = file_bytes if source_type == "pdf" else None
        _save_pdf_job(_pdf_jobs[job_id], pdf_bytes=store_bytes)


def _run_extraction_job(
    job_id: str,
    file_bytes: bytes,
    source_type: str,
    api_key: Optional[str],
) -> None:
    """Background worker: type-specific ingest → shared confidence + LLM validation."""
    last_flush = {"stage": None, "bucket": -1}

    def on_progress(stage: str, percent: int, message: str) -> None:
        with _pdf_jobs_lock:
            job = _pdf_jobs.get(job_id)
            if job is not None:
                job.update(status="running", stage=stage, percent=percent, message=message)
                bucket = int(percent) // 10
                if stage != last_flush["stage"] or bucket != last_flush["bucket"]:
                    last_flush["stage"] = stage
                    last_flush["bucket"] = bucket
                    _save_pdf_job(job)

    suffix = _SUFFIX_BY_TYPE.get(source_type, ".bin")
    tmp_path: Optional[pathlib.Path] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = pathlib.Path(tmp.name)
        result = run_upload_pipeline(
            tmp_path,
            source_type,
            api_key=api_key,
            on_progress=on_progress,
        )
        with _pdf_jobs_lock:
            job = _pdf_jobs.get(job_id)
            if job is not None:
                job.update(
                    status="done",
                    stage="done",
                    percent=100,
                    message="Complete",
                    result=result,
                )
                pdf_store_bytes = file_bytes if source_type == "pdf" else None
                _save_pdf_job(job, pdf_bytes=pdf_store_bytes)
    except Exception as e:
        print(f"Extraction job {job_id} ({source_type}) failed: {e}")
        with _pdf_jobs_lock:
            job = _pdf_jobs.get(job_id)
            if job is not None:
                job.update(status="error", message=f"Failed: {e}", error=str(e))
                _save_pdf_job(job, clear_pdf_bytes=True)
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass


def _run_pdf_job(job_id: str, pdf_bytes: bytes, api_key: Optional[str]) -> None:
    """Backward-compatible entry for legacy PDF upload route."""
    _run_extraction_job(job_id, pdf_bytes, "pdf", api_key)


def _normalize_pdf_header_name(name: Any) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip().lower())


def _pdf_table_header_key(table: Dict[str, Any]) -> str:
    """Stable fingerprint of column headers for cross-page merge eligibility."""
    names: List[str] = []
    for col in table.get("columns") or []:
        if isinstance(col, dict):
            names.append(_normalize_pdf_header_name(col.get("name")))
        else:
            names.append(_normalize_pdf_header_name(col))
    return "|".join(names)


def _parse_pdf_table_id(table_id: str) -> Tuple[str, int]:
    parts = str(table_id).rsplit("-", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        raise ValueError(f"Invalid table_id: {table_id}")
    return parts[0], int(parts[1])


def _pdf_table_sort_key(table_id: str) -> Tuple[Any, int]:
    page_s, idx = _parse_pdf_table_id(table_id)
    page_key: Any = int(page_s) if page_s.isdigit() else page_s
    return page_key, idx


def _pdf_tables_from_job(job: Dict[str, Any]) -> list:
    """Flatten JSON job result + reviews into the approved table list."""
    reviews = dict(job.get("reviews") or {})
    deleted = set(job.get("deleted_table_ids") or [])
    result = job.get("result") or {}
    tables = []
    for page_num in sorted(result.keys(), key=lambda k: int(k) if str(k).isdigit() else str(k)):
        for idx, t in enumerate(result[page_num].get("tables", [])):
            table_id = f"{page_num}-{idx}"
            if table_id in deleted:
                continue
            merged = {**t, **reviews.get(table_id, {}), "table_id": table_id, "page": t.get("page", page_num)}
            tables.append(merged)
    return tables


def _pdf_merged_tables_for_job(job: Dict[str, Any]) -> list:
    """Approved (non-deleted) tables with review patches applied."""
    return _pdf_tables_from_job(job)
