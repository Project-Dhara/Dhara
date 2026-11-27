"""Postgres-backed Suggest NCO jobs (desktop async poll; Docker stays sync).

Jobs live in ``nco_match_jobs`` + ``nco_match_job_attach_tokens``. The worker
claims via ``UPDATE … RETURNING``; the API enqueues/attaches with a partial
unique index on ``(owner, fingerprint)`` for active rows.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Client poll budget (returned as max_wait_sec); worker max must be higher.
_DEFAULT_CLIENT_WAIT_SEC = 600.0
_DEFAULT_WORKER_MAX_SEC = 720.0
_QUEUED_SKIP_SEC = 30.0
_QUEUED_CANCEL_SEC = 600.0  # 10 min
_DONE_REUSE_SEC = 120.0  # fingerprint attach reuse
_DONE_FETCH_SEC = 900.0  # 15 min hard DELETE of done
_ERROR_RETENTION_SEC = 300.0  # 5 min
_HEARTBEAT_STALE_SEC = 120.0
_PIPELINE_VERSION = "nco-match-v2"


def client_max_wait_sec() -> float:
    raw = (os.environ.get("DHARA_NCO_MATCH_TIMEOUT_SEC") or "").strip()
    try:
        return max(60.0, float(raw or _DEFAULT_CLIENT_WAIT_SEC))
    except ValueError:
        return _DEFAULT_CLIENT_WAIT_SEC


def worker_max_runtime_sec() -> float:
    raw = (os.environ.get("DHARA_NCO_WORKER_MAX_SEC") or "").strip()
    try:
        return max(client_max_wait_sec() + 30.0, float(raw or _DEFAULT_WORKER_MAX_SEC))
    except ValueError:
        return max(client_max_wait_sec() + 30.0, _DEFAULT_WORKER_MAX_SEC)


def child_idle_sec() -> float:
    raw = (os.environ.get("DHARA_NCO_CHILD_IDLE_SEC") or "").strip()
    try:
        return max(30.0, float(raw or "240"))
    except ValueError:
        return 240.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _status_path() -> Path:
    root = (os.environ.get("DHARA_DATA_DIR") or "").strip() or str(Path.cwd() / "data")
    path = Path(root) / "worker_status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_worker_status(state: str, *, detail: str = "") -> None:
    """Short-lived liveness file for the UI (idle | busy:pdf | busy:nco)."""
    payload = {
        "state": state,
        "updated_at": time.time(),
        "detail": detail or "",
    }
    path = _status_path()
    tmp = path.with_suffix(".tmp")
    for attempt in range(5):
        try:
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
        except Exception:
            logger.debug("worker status write failed", exc_info=True)
            return


def read_worker_status(*, max_age_sec: float = 8.0) -> dict:
    path = _status_path()
    if not path.is_file():
        return {"state": "down", "fresh": False, "detail": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - float(data.get("updated_at") or 0)
        fresh = age <= max_age_sec
        return {
            "state": str(data.get("state") or "unknown"),
            "fresh": fresh,
            "age_sec": age,
            "detail": str(data.get("detail") or ""),
        }
    except Exception:
        return {"state": "down", "fresh": False, "detail": ""}


def _crosswalk_hash() -> str:
    try:
        from app.services.classification.nco_matching import _crosswalk_csv_path

        path = _crosswalk_csv_path()
        if path and Path(path).is_file():
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return h.hexdigest()[:16]
    except Exception:
        pass
    return ""


def steward_alias_counter(session: Session) -> int:
    row = session.execute(
        text("SELECT counter FROM nco_steward_alias_counter WHERE id = 1")
    ).fetchone()
    if not row:
        session.execute(
            text(
                "INSERT INTO nco_steward_alias_counter (id, counter) VALUES (1, 0) "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
        return 0
    return int(row[0] or 0)


def bump_steward_alias_counter(session: Session) -> int:
    session.execute(
        text(
            "INSERT INTO nco_steward_alias_counter (id, counter, updated_at) "
            "VALUES (1, 1, now()) "
            "ON CONFLICT (id) DO UPDATE SET counter = nco_steward_alias_counter.counter + 1, "
            "updated_at = now()"
        )
    )
    return steward_alias_counter(session)


def compute_fingerprint(
    *,
    owner: str,
    values: List[str],
    context: Optional[Dict[str, Any]],
    standard_id: Any,
    alias_counter: int,
    llm_on: bool,
) -> str:
    labels = sorted({str(v).strip() for v in values if v is not None and str(v).strip()})
    ctx = context if isinstance(context, dict) else {}
    ctx_bits = {
        "column": ctx.get("column") or ctx.get("column_name") or "",
        "heading": ctx.get("table_heading") or ctx.get("heading") or "",
        "title": ctx.get("table_title") or ctx.get("title") or "",
    }
    payload = {
        "owner": str(owner or ""),
        "labels": labels,
        "standard_id": standard_id,
        "context": ctx_bits,
        "alias_counter": int(alias_counter),
        "pipeline": _PIPELINE_VERSION,
        "llm": bool(llm_on),
        "embedding_family": (os.environ.get("NCO_EMBEDDING_FAMILY") or "").strip(),
        "embedding_revision": (os.environ.get("NCO_EMBEDDING_REVISION") or "").strip(),
        "crosswalk": _crosswalk_hash(),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _row_to_dict(row: Any) -> dict:
    if row is None:
        return {}
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return dict(row)


def job_public(job: dict, *, include_result: bool = True) -> dict:
    out = {
        "job_id": str(job.get("id") or job.get("job_id") or ""),
        "status": str(job.get("status") or ""),
        "stage": job.get("stage") or "",
        "progress": {
            "done": job.get("progress_done"),
            "total": job.get("progress_total"),
        },
        "fingerprint": job.get("fingerprint") or "",
        "created_at": job.get("created_at").isoformat() if job.get("created_at") else None,
        "claimed_at": job.get("claimed_at").isoformat() if job.get("claimed_at") else None,
        "updated_at": job.get("updated_at").isoformat() if job.get("updated_at") else None,
        "finished_at": job.get("finished_at").isoformat() if job.get("finished_at") else None,
        "max_wait_sec": client_max_wait_sec(),
        "error": job.get("error"),
    }
    if include_result and str(job.get("status") or "") == "done":
        result = job.get("result") or {}
        out["matches"] = result.get("matches") or {}
        out["llm_used"] = bool(result.get("llm_used"))
        out["retrieval_mode"] = result.get("retrieval_mode") or "keyword-only"
        out["retrieval_reason"] = result.get("retrieval_reason") or ""
    return out


def _is_keyword_only_result(result: Optional[dict]) -> bool:
    if not isinstance(result, dict):
        return True
    return str(result.get("retrieval_mode") or "") == "keyword-only"


def _heartbeat_stale(updated_at: Optional[datetime]) -> bool:
    if updated_at is None:
        return True
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return (_utcnow() - updated_at).total_seconds() > _HEARTBEAT_STALE_SEC


def enqueue_or_attach(
    session: Session,
    *,
    owner: str,
    values: List[str],
    context: Optional[Dict[str, Any]] = None,
    llm: Optional[Dict[str, Any]] = None,
    standard_id: Any = None,
    llm_on: bool = False,
) -> dict:
    """Create or attach to an active/recent job. Returns public payload + attach_token."""
    owner = str(owner or "").strip()
    if not owner:
        raise ValueError("owner required")
    alias_counter = steward_alias_counter(session)
    fingerprint = compute_fingerprint(
        owner=owner,
        values=values,
        context=context,
        standard_id=standard_id,
        alias_counter=alias_counter,
        llm_on=llm_on,
    )
    request = {
        "values": list(values),
        "context": context,
        "llm": llm or {},
        "standard_id": standard_id,
        "alias_counter": alias_counter,
    }

    for _attempt in range(4):
        # Reuse recent semantic done within TTL (never keyword-only).
        done = session.execute(
            text(
                """
                SELECT * FROM nco_match_jobs
                WHERE owner = :owner AND fingerprint = :fp AND status = 'done'
                  AND finished_at > now() - (:ttl * INTERVAL '1 second')
                ORDER BY finished_at DESC
                LIMIT 1
                FOR UPDATE
                """
            ),
            {"owner": owner, "fp": fingerprint, "ttl": _DONE_REUSE_SEC},
        ).mappings().first()
        if done and not _is_keyword_only_result(done.get("result")):
            token = uuid.uuid4()
            session.execute(
                text(
                    "INSERT INTO nco_match_job_attach_tokens (token, job_id) "
                    "VALUES (:token, :job_id)"
                ),
                {"token": token, "job_id": done["id"]},
            )
            session.execute(
                text(
                    "UPDATE nco_match_jobs SET last_polled_at = now() WHERE id = :id"
                ),
                {"id": done["id"]},
            )
            pub = job_public(dict(done))
            pub["attach_token"] = str(token)
            return pub

        active = session.execute(
            text(
                """
                SELECT * FROM nco_match_jobs
                WHERE owner = :owner AND fingerprint = :fp
                  AND status IN ('queued', 'running')
                LIMIT 1
                FOR UPDATE
                """
            ),
            {"owner": owner, "fp": fingerprint},
        ).mappings().first()

        if active:
            if str(active["status"]) == "running" and _heartbeat_stale(active.get("updated_at")):
                session.execute(
                    text(
                        """
                        UPDATE nco_match_jobs
                        SET status = 'error',
                            error = 'worker stopped',
                            finished_at = now(),
                            updated_at = now()
                        WHERE id = :id
                        """
                    ),
                    {"id": active["id"]},
                )
                session.flush()
                continue

            token = uuid.uuid4()
            session.execute(
                text(
                    "INSERT INTO nco_match_job_attach_tokens (token, job_id) "
                    "VALUES (:token, :job_id)"
                ),
                {"token": token, "job_id": active["id"]},
            )
            session.execute(
                text(
                    "UPDATE nco_match_jobs SET last_polled_at = now() WHERE id = :id"
                ),
                {"id": active["id"]},
            )
            pub = job_public(dict(active))
            pub["attach_token"] = str(token)
            return pub

        job_id = uuid.uuid4()
        inserted = session.execute(
            text(
                """
                INSERT INTO nco_match_jobs (
                    id, fingerprint, owner, status, stage, request,
                    created_at, updated_at, last_polled_at
                )
                VALUES (
                    :id, :fp, :owner, 'queued', 'queued', CAST(:request AS jsonb),
                    now(), now(), now()
                )
                ON CONFLICT (owner, fingerprint) WHERE status IN ('queued', 'running')
                DO NOTHING
                RETURNING *
                """
            ),
            {
                "id": job_id,
                "fp": fingerprint,
                "owner": owner,
                "request": json.dumps(request),
            },
        ).mappings().first()

        if inserted:
            token = uuid.uuid4()
            session.execute(
                text(
                    "INSERT INTO nco_match_job_attach_tokens (token, job_id) "
                    "VALUES (:token, :job_id)"
                ),
                {"token": token, "job_id": inserted["id"]},
            )
            pub = job_public(dict(inserted))
            pub["attach_token"] = str(token)
            return pub

        # Conflict loser: attach on next loop iteration.
        session.flush()

    raise RuntimeError("Could not enqueue or attach NCO match job")


def get_job_for_owner(
    session: Session, *, job_id: str, owner: str, touch_poll: bool = True
) -> Optional[dict]:
    try:
        jid = uuid.UUID(str(job_id))
    except ValueError:
        return None
    row = session.execute(
        text("SELECT * FROM nco_match_jobs WHERE id = :id"),
        {"id": jid},
    ).mappings().first()
    if not row:
        return None
    if str(row["owner"] or "") != str(owner or ""):
        return None
    if touch_poll:
        session.execute(
            text("UPDATE nco_match_jobs SET last_polled_at = now() WHERE id = :id"),
            {"id": jid},
        )
        row = dict(row)
        row["last_polled_at"] = _utcnow()
    return dict(row)


def detach_token(
    session: Session, *, job_id: str, owner: str, attach_token: str
) -> bool:
    """Remove one attach token (idempotent). Returns True if job existed for owner."""
    try:
        jid = uuid.UUID(str(job_id))
        token = uuid.UUID(str(attach_token))
    except ValueError:
        return False
    row = session.execute(
        text("SELECT id, owner FROM nco_match_jobs WHERE id = :id"),
        {"id": jid},
    ).mappings().first()
    if not row:
        return False
    if str(row["owner"] or "") != str(owner or ""):
        return False
    session.execute(
        text(
            "DELETE FROM nco_match_job_attach_tokens "
            "WHERE job_id = :job_id AND token = :token"
        ),
        {"job_id": jid, "token": token},
    )
    return True


def claim_next_nco_job(session: Session) -> Optional[dict]:
    """Claim oldest recently-polled queued job."""
    row = session.execute(
        text(
            """
            UPDATE nco_match_jobs
            SET status = 'running',
                claimed_at = now(),
                updated_at = now(),
                stage = 'loading_model'
            WHERE id = (
                SELECT id FROM nco_match_jobs
                WHERE status = 'queued'
                  AND last_polled_at > now() - (:skip * INTERVAL '1 second')
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING *
            """
        ),
        {"skip": _QUEUED_SKIP_SEC},
    ).mappings().first()
    return dict(row) if row else None


def update_job_progress(
    session: Session,
    job_id: Any,
    *,
    stage: Optional[str] = None,
    progress_done: Optional[int] = None,
    progress_total: Optional[int] = None,
    heartbeat: bool = True,
) -> None:
    sets = ["updated_at = now()"] if heartbeat else []
    params: Dict[str, Any] = {"id": job_id}
    if stage is not None:
        sets.append("stage = :stage")
        params["stage"] = stage
    if progress_done is not None:
        sets.append("progress_done = :pd")
        params["pd"] = progress_done
    if progress_total is not None:
        sets.append("progress_total = :pt")
        params["pt"] = progress_total
    if not sets:
        return
    session.execute(
        text(f"UPDATE nco_match_jobs SET {', '.join(sets)} WHERE id = :id"),
        params,
    )


def finish_job(
    session: Session,
    job_id: Any,
    *,
    status: str,
    result: Optional[dict] = None,
    error: Optional[str] = None,
) -> None:
    session.execute(
        text(
            """
            UPDATE nco_match_jobs
            SET status = :status,
                result = CAST(:result AS jsonb),
                error = :error,
                finished_at = now(),
                updated_at = now(),
                stage = :stage
            WHERE id = :id
            """
        ),
        {
            "id": job_id,
            "status": status,
            "result": json.dumps(result) if result is not None else None,
            "error": error,
            "stage": status,
        },
    )


def cancel_stale_queued(session: Session) -> int:
    res = session.execute(
        text(
            """
            UPDATE nco_match_jobs
            SET status = 'cancelled',
                finished_at = now(),
                updated_at = now(),
                stage = 'cancelled',
                error = 'abandoned — no client polls'
            WHERE status = 'queued'
              AND last_polled_at < now() - (:ttl * INTERVAL '1 second')
            """
        ),
        {"ttl": _QUEUED_CANCEL_SEC},
    )
    return int(res.rowcount or 0)


def fail_stale_running(session: Session) -> int:
    res = session.execute(
        text(
            """
            UPDATE nco_match_jobs
            SET status = 'error',
                finished_at = now(),
                updated_at = now(),
                stage = 'error',
                error = 'worker stopped'
            WHERE status = 'running'
              AND updated_at < now() - (:ttl * INTERVAL '1 second')
            """
        ),
        {"ttl": _HEARTBEAT_STALE_SEC},
    )
    return int(res.rowcount or 0)


def sweep_terminal_jobs(session: Session) -> int:
    """Age-based DELETE of terminal jobs (cascades attach tokens)."""
    res = session.execute(
        text(
            """
            DELETE FROM nco_match_jobs
            WHERE (
                status = 'done'
                AND finished_at < now() - (:done_ttl * INTERVAL '1 second')
            ) OR (
                status IN ('error', 'cancelled')
                AND finished_at < now() - (:err_ttl * INTERVAL '1 second')
            )
            """
        ),
        {"done_ttl": _DONE_FETCH_SEC, "err_ttl": _ERROR_RETENTION_SEC},
    )
    return int(res.rowcount or 0)


def maintenance(session: Session) -> None:
    fail_stale_running(session)
    cancel_stale_queued(session)
    sweep_terminal_jobs(session)


def run_nco_match_payload(job: dict) -> Tuple[dict, dict]:
    """Execute matching for a claimed job dict. Returns (result, timings)."""
    from app.db.session import dbapi_connection, session_scope
    from app.services.classification import nco_matching as _nco
    from app.services.classification.nco_embedder import load_embedder, retrieval_status
    from app.services.ingestion.wizard.extractor import TableExtractor
    from app.services.standards.classification_standards import (
        ensure_selected_loaded as ensure_classification_standard_loaded,
    )

    timings: Dict[str, float] = {}
    job_id = job.get("id") or job.get("job_id")
    request = job.get("request") or {}
    if isinstance(request, str):
        request = json.loads(request)
    llm = request.get("llm") or {}
    api_key = (llm.get("api_key") or "").strip()
    nco_llm_on = (os.environ.get("DHARA_NCO_LLM") or "off").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    extractor = None
    if nco_llm_on and api_key:
        extractor = TableExtractor(
            api_key=api_key,
            skip_llm=False,
            provider=llm.get("provider"),
            base_url=llm.get("base_url"),
            model=llm.get("model"),
        )
    values = [
        str(v)
        for v in (request.get("values") or [])
        if v is not None and str(v).strip()
    ]
    context = request.get("context") if isinstance(request.get("context"), dict) else None

    def _stage(stage: str, *, done: Optional[int] = None, total: Optional[int] = None) -> None:
        if job_id is None:
            return
        try:
            with session_scope() as session:
                update_job_progress(
                    session,
                    job_id,
                    stage=stage,
                    progress_done=done,
                    progress_total=total,
                )
        except Exception:
            logger.debug("stage update failed", exc_info=True)

    t_model = time.perf_counter()
    _stage("loading_model")
    load_embedder()
    timings["model_load_sec"] = round(time.perf_counter() - t_model, 3)
    logger.info("NCO stage model_load took %.3fs", timings["model_load_sec"])

    t0 = time.perf_counter()
    _stage("preparing_index", done=0, total=len(values))
    with session_scope() as session:
        conn = dbapi_connection(session)
        ensure_classification_standard_loaded(conn)
        timings["index_prepare_sec"] = round(time.perf_counter() - t0, 3)
        logger.info("NCO stage index_prepare took %.3fs", timings["index_prepare_sec"])
        _stage("matching", done=0, total=len(values))
        t_match = time.perf_counter()
        matches = _nco.match_occupations(
            conn,
            values,
            extractor=extractor,
            context=context,
        )
        timings["match_occupations_sec"] = round(time.perf_counter() - t_match, 3)
        timings["label_count"] = float(len(values))
        logger.info(
            "NCO stage match_occupations took %.3fs (%s labels)",
            timings["match_occupations_sec"],
            len(values),
        )
        _stage("matching", done=len(values), total=len(values))
    timings["match_total_sec"] = round(time.perf_counter() - t0, 3)
    status = retrieval_status()
    result = {
        "matches": matches,
        "llm_used": bool(
            extractor is not None and not getattr(extractor, "skip_llm", True)
        ),
        "retrieval_mode": status.get("retrieval_mode") or "keyword-only",
        "retrieval_reason": status.get("retrieval_reason") or "",
        "timings": timings,
    }
    return result, timings


# ---------------------------------------------------------------------------
# Worker helpers: claim + run in-process (child process entry uses these)
# ---------------------------------------------------------------------------

def claim_and_run_one_nco_job() -> bool:
    """Claim one NCO job and run matching in-process. Returns True if work done.

    The warm-child wrapper in ``job_worker`` prefers this for the child, or
    calls ``claim_next_nco_job`` + ``run_nco_match_payload`` itself.
    """
    from app.db.session import session_scope

    with session_scope() as session:
        claimed = claim_next_nco_job(session)
        if not claimed:
            return False
        job_id = claimed["id"]

    write_worker_status("busy:nco", detail=str(job_id))
    t_start = time.monotonic()
    try:
        with session_scope() as session:
            update_job_progress(session, job_id, stage="loading_model")

        result, timings = run_nco_match_payload(claimed)
        for key, val in timings.items():
            logger.info("NCO job %s timing %s=%.3fs", job_id, key, float(val))

        elapsed = time.monotonic() - t_start
        if elapsed > worker_max_runtime_sec():
            with session_scope() as session:
                finish_job(
                    session,
                    job_id,
                    status="error",
                    error="worker max runtime exceeded",
                )
        else:
            with session_scope() as session:
                update_job_progress(session, job_id, stage="matching")
                finish_job(session, job_id, status="done", result=result)
            logger.info(
                "NCO match job %s done (mode=%s, %.1fs)",
                job_id,
                result.get("retrieval_mode"),
                elapsed,
            )
    except Exception as e:
        logger.exception("NCO match job %s failed", job_id)
        with session_scope() as session:
            finish_job(
                session,
                job_id,
                status="error",
                error=str(e).strip() or e.__class__.__name__,
            )
    finally:
        write_worker_status("idle")
    return True


def cleanup_old_jobs() -> None:
    """Backward-compatible name used by job_worker — runs maintenance sweep."""
    from app.db.session import session_scope

    with session_scope() as session:
        maintenance(session)
