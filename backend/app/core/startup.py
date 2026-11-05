"""Process startup checks for required configuration."""
from __future__ import annotations

import logging
import os

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def ensure_runtime_config() -> None:
    """Fail fast when secrets/connection settings required for auth are missing.

    Set ``DHARA_SKIP_STARTUP_CHECKS=1`` only for narrow unit tests that never
    issue JWTs or open the database.
    """
    if _truthy("DHARA_SKIP_STARTUP_CHECKS"):
        logger.warning("Skipping runtime config checks (DHARA_SKIP_STARTUP_CHECKS)")
        return

    settings = get_settings()
    missing: list[str] = []
    if not (settings.jwt_secret or "").strip():
        missing.append("JWT_SECRET")
    if not (settings.database_url or "").strip():
        missing.append("DATABASE_URL")

    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
            + ". Copy backend/.env.example to backend/.env and set them before starting."
        )

    logger.info("Runtime config OK (JWT_SECRET and DATABASE_URL present)")
