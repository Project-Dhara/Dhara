"""Liveness and readiness probes (no JWT, no secrets)."""
from fastapi import APIRouter, Response, status

from app.db import psycopg as _cat

router = APIRouter(tags=["Health"])


def _readiness_payload(response: Response) -> dict:
    """Postgres SELECT 1 for readiness; report pgvector without failing on it.

    Schema init / migrations must never run here — probes are read-only.
    """
    checks: dict = {"postgres": False, "pgvector": False}
    try:
        from app.storage import vectors as _vs

        conn = _cat.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            checks["postgres"] = True
            checks["pgvector"] = _vs.vector_extension_ready(conn)
            checks["embedding_dim"] = _vs.embedding_dim()
        finally:
            conn.close()
    except Exception as exc:
        checks["error"] = type(exc).__name__
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "checks": checks}

    if not checks["postgres"]:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "checks": checks}
    return {"status": "ready", "checks": checks}


@router.get("/api/live", summary="Liveness")
async def live():
    """Process is up. No dependency checks."""
    return {"status": "ok"}


@router.get("/api/ready", summary="Readiness")
async def ready(response: Response):
    """Ready for traffic when Postgres answers SELECT 1. Returns 503 otherwise."""
    return _readiness_payload(response)


@router.get("/api/health", summary="Health (readiness alias)")
async def health(response: Response):
    """Alias of `/api/ready` for existing docs and curl habits."""
    return _readiness_payload(response)
