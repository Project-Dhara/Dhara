"""NCO match child process — loads embedder once, runs jobs until idle exit.

Parent sends job dicts on ``in_q``; child replies with ``{job_id, ok, result|error}``.
Sentinel ``None`` asks the child to exit cleanly.
"""
from __future__ import annotations

import logging
import traceback
from typing import Any

logger = logging.getLogger("dhara.nco_child")


def run_child_loop(in_q: Any, out_q: Any) -> None:
    """Entry point for multiprocessing.Process(target=run_child_loop, …)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [nco-child] %(message)s",
    )
    from app.core.startup import ensure_runtime_config

    ensure_runtime_config()
    logger.info("NCO child started")

    while True:
        try:
            job = in_q.get()
        except Exception:
            break
        if job is None:
            logger.info("NCO child exit requested")
            break
        job_id = str(job.get("id") or job.get("job_id") or "")
        try:
            from app.services.classification.nco_match_jobs import run_nco_match_payload

            result, timings = run_nco_match_payload(job)
            for key, val in (timings or {}).items():
                logger.info("NCO job %s timing %s=%s", job_id, key, val)
            out_q.put(
                {
                    "job_id": job_id,
                    "ok": True,
                    "result": result,
                    "timings": timings,
                }
            )
        except Exception as e:
            logger.exception("NCO child job %s failed", job_id)
            out_q.put(
                {
                    "job_id": job_id,
                    "ok": False,
                    "error": str(e).strip() or e.__class__.__name__,
                    "traceback": traceback.format_exc(),
                }
            )
    logger.info("NCO child exiting")
