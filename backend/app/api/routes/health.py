"""Liveness and readiness probes (no JWT, no secrets)."""
from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.db.session import ping_database, session_scope

router = APIRouter(tags=["Health"])


def _readiness_payload(response: Response) -> dict:
    """Postgres SELECT 1 for readiness; report pgvector without failing on it.

    Schema init / migrations must never run here — probes are read-only.
    """
    checks: dict = {"postgres": False, "pgvector": False}
    try:
        from app.storage import vectors as _vs

        checks["postgres"] = ping_database()
        if checks["postgres"]:
            with session_scope() as session:
                row = session.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
                    )
                ).scalar()
                checks["pgvector"] = bool(row)
            checks["embedding_dim"] = _vs.embedding_dim()
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
