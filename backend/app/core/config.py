"""Centralized application settings (environment-driven).

Operational secrets and connection settings live here. LLM prompt templates
remain in ``backend/config.py``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus, urlparse, urlunparse


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return int(raw)


def normalize_database_url(url: str) -> str:
    """Return a SQLAlchemy-compatible Postgres URL (psycopg2 driver).

    Accepts plain ``postgresql://`` / ``postgres://`` and upgrades them to
    ``postgresql+psycopg2://``. Inside Docker, rewrite localhost → postgres.
    """
    if not url:
        raise RuntimeError("DATABASE_URL is not set")

    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+psycopg2"
    elif scheme == "postgresql+psycopg":
        # Prefer psycopg2 for this codebase until legacy call sites migrate.
        scheme = "postgresql+psycopg2"
    elif scheme not in ("postgresql+psycopg2",):
        # Leave other schemes alone (e.g. sqlite for limited tests).
        pass

    if Path("/.dockerenv").exists():
        host = (parsed.hostname or "").lower()
        if host in ("localhost", "127.0.0.1", "::1", "host.docker.internal"):
            userinfo = ""
            if parsed.username is not None:
                userinfo = quote_plus(parsed.username)
                if parsed.password is not None:
                    userinfo += ":" + quote_plus(parsed.password)
                userinfo += "@"
            port = parsed.port or 5432
            parsed = parsed._replace(
                scheme=scheme,
                netloc=f"{userinfo}postgres:{port}",
            )
            return urlunparse(parsed)

    return urlunparse(parsed._replace(scheme=scheme))


def psycopg2_dsn(url: str | None = None) -> str:
    """DSN suitable for ``psycopg2.connect`` (no SQLAlchemy driver suffix)."""
    sa_url = normalize_database_url(url or os.environ["DATABASE_URL"])
    return sa_url.replace("postgresql+psycopg2://", "postgresql://", 1)


@dataclass(frozen=True)
class Settings:
    database_url: str
    database_pool_size: int
    database_max_overflow: int
    database_pool_timeout: int
    database_sslmode: str | None
    jwt_secret: str
    jwt_exp_seconds: int
    default_organisation_slug: str
    default_organisation_name: str
    bootstrap_admin_email: str | None
    disable_request_time_ddl: bool
    enable_signup: bool


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    raw_db = os.environ.get("DATABASE_URL", "")
    jwt_secret = os.environ.get("JWT_SECRET", "")
    return Settings(
        database_url=normalize_database_url(raw_db) if raw_db else "",
        database_pool_size=_env_int("DATABASE_POOL_SIZE", 10),
        database_max_overflow=_env_int("DATABASE_MAX_OVERFLOW", 20),
        database_pool_timeout=_env_int("DATABASE_POOL_TIMEOUT", 30),
        database_sslmode=(os.environ.get("DATABASE_SSLMODE") or "").strip() or None,
        jwt_secret=jwt_secret,
        jwt_exp_seconds=_env_int("JWT_EXP_SECONDS", 60 * 60 * 12),
        default_organisation_slug=(
            os.environ.get("DEFAULT_ORGANISATION_SLUG") or "default"
        ).strip(),
        default_organisation_name=(
            os.environ.get("DEFAULT_ORGANISATION_NAME") or "Default Organisation"
        ).strip(),
        bootstrap_admin_email=(
            (os.environ.get("BOOTSTRAP_ADMIN_EMAIL") or "").strip().lower() or None
        ),
        disable_request_time_ddl=_env_bool("DISABLE_REQUEST_TIME_DDL", False),
        enable_signup=_env_bool("ENABLE_SIGNUP", True),
    )


def clear_settings_cache() -> None:
    get_settings.cache_clear()
