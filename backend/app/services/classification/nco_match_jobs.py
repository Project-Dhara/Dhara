"""Desktop file-queue for Suggest NCO — runs in the job worker, not the API.

API writes a request JSON under ``DHARA_DATA_DIR/nco_match_jobs/``, the worker
claims it, runs ``match_occupations``, and writes the response. The API polls
until done (same sync shape for Classify.jsx).
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_JOB_DIR_NAME = "nco_match_jobs"
_DEFAULT_TIMEOUT_SEC = 180.0


def _jobs_dir() -> Path:
    root = (os.environ.get("DHARA_DATA_DIR") or "").strip()
    if not root:
        root = str(Path.cwd() / "data")
    path = Path(root) / _JOB_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _atomic_write(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, default=str), encoding="utf-8")
    tmp.replace(path)


def enqueue_nco_match(
    *,
    values: List[str],
    context: Optional[Dict[str, Any]] = None,
    llm: Optional[Dict[str, Any]] = None,
) -> str:
    job_id = uuid.uuid4().hex
    path = _jobs_dir() / f"{job_id}.json"
    _atomic_write(
        path,
        {
            "job_id": job_id,
            "status": "queued",
            "created_at": time.time(),
            "values": list(values),
            "context": context,
            "llm": llm or {},
            "result": None,
            "error": None,
        },
    )
    return job_id


def read_job(job_id: str) -> Optional[dict]:
    path = _jobs_dir() / f"{job_id}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def wait_nco_match(job_id: str, *, timeout_sec: float = _DEFAULT_TIMEOUT_SEC) -> dict:
    deadline = time.monotonic() + max(5.0, float(timeout_sec))
    while time.monotonic() < deadline:
        job = read_job(job_id)
        if not job:
            time.sleep(0.15)
            continue
        status = str(job.get("status") or "")
        if status in ("done", "error"):
            return job
        time.sleep(0.2)
    return {
        "job_id": job_id,
        "status": "error",
        "error": "Timed out waiting for NCO match worker",
        "result": None,
    }


def claim_and_run_one_nco_job() -> bool:
    """Claim the oldest queued NCO job and run it. Returns True if work was done."""
    jobs_dir = _jobs_dir()
    queued = sorted(
        (
            p
            for p in jobs_dir.glob("*.json")
            if p.is_file() and not p.name.endswith(".tmp")
        ),
        key=lambda p: p.stat().st_mtime,
    )
    claimed_path = None
    claimed = None
    for path in queued:
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(job.get("status") or "") != "queued":
            continue
        job["status"] = "running"
        job["started_at"] = time.time()
        try:
            _atomic_write(path, job)
        except Exception:
            continue
        claimed_path = path
        claimed = job
        break
    if not claimed or not claimed_path:
        return False

    job_id = str(claimed.get("job_id") or claimed_path.stem)
    try:
        from app.db.session import dbapi_connection, session_scope
        from app.services.classification import nco_matching as _nco
        from app.services.classification.nco_embedder import retrieval_status
        from app.services.ingestion.wizard.extractor import TableExtractor
        from app.services.standards.classification_standards import (
            ensure_selected_loaded as ensure_classification_standard_loaded,
        )

        llm = claimed.get("llm") or {}
        api_key = (llm.get("api_key") or "").strip()
        extractor = TableExtractor(
            api_key=api_key or "unused",
            skip_llm=not api_key,
            provider=llm.get("provider"),
            base_url=llm.get("base_url"),
            model=llm.get("model"),
        )
        values = [str(v) for v in (claimed.get("values") or []) if v is not None and str(v).strip()]
        context = claimed.get("context") if isinstance(claimed.get("context"), dict) else None

        with session_scope() as session:
            conn = dbapi_connection(session)
            ensure_classification_standard_loaded(conn)
            matches = _nco.match_occupations(
                conn,
                values,
                extractor=extractor,
                context=context,
            )

        status = retrieval_status()
        claimed.update(
            status="done",
            finished_at=time.time(),
            result={
                "matches": matches,
                "llm_used": not extractor.skip_llm,
                "retrieval_mode": status.get("retrieval_mode") or "keyword-only",
                "retrieval_reason": status.get("retrieval_reason") or "",
            },
            error=None,
        )
        _atomic_write(claimed_path, claimed)
        logger.info(
            "NCO match job %s done (%s values, mode=%s)",
            job_id,
            len(values),
            status.get("retrieval_mode"),
        )
    except Exception as e:
        logger.exception("NCO match job %s failed", job_id)
        claimed.update(
            status="error",
            finished_at=time.time(),
            error=str(e).strip() or e.__class__.__name__,
            result=None,
        )
        try:
            _atomic_write(claimed_path, claimed)
        except Exception:
            logger.exception("Could not persist NCO job failure for %s", job_id)
    return True


def cleanup_old_jobs(*, max_age_sec: float = 3600.0) -> None:
    cutoff = time.time() - max_age_sec
    for path in _jobs_dir().glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except Exception:
            continue
