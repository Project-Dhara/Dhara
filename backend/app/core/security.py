"""Password hashing and JWT create/decode (UUID ``sub``)."""
from __future__ import annotations

import re
import time
import uuid
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
JWT_ALG = "HS256"


def is_valid_org_email(email: str) -> bool:
    return bool(EMAIL_RE.match((email or "").strip()))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, AttributeError):
        return False


def _secret() -> str:
    settings = get_settings()
    if not settings.jwt_secret:
        raise RuntimeError("JWT_SECRET environment variable is not set")
    return settings.jwt_secret


def create_token(user_id: uuid.UUID | str, *, email: str | None = None) -> str:
    """Issue a JWT with ``sub`` = stable user UUID (not email)."""
    settings = get_settings()
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "exp": int(time.time()) + settings.jwt_exp_seconds,
    }
    if email:
        payload["email"] = email
    return jwt.encode(payload, _secret(), algorithm=JWT_ALG)


def decode_token(token: str) -> uuid.UUID:
    """Return the user UUID carried in ``sub``."""
    payload = jwt.decode(token, _secret(), algorithms=[JWT_ALG])
    sub = payload.get("sub")
    if not sub:
        raise jwt.InvalidTokenError("Session ended — please sign in again")
    try:
        return uuid.UUID(str(sub))
    except (ValueError, TypeError) as exc:
        raise jwt.InvalidTokenError(
            "Invalid session — please sign in again"
        ) from exc


def decode_token_payload(token: str) -> dict[str, Any]:
    return jwt.decode(token, _secret(), algorithms=[JWT_ALG])
