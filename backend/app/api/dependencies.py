"""FastAPI dependencies for authentication and authorization."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional, Tuple

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core import security
from app.db.repositories import organisations as org_repo
from app.db.repositories import users as user_repo
from app.db.session import get_db
from catalogue.extract.extractor import TableExtractor

LLM_KEY_HEADER = "x-llm-api-key"
LLM_PROVIDER_HEADER = "x-llm-provider"
_KNOWN_LLM_PROVIDERS = {"anthropic", "openai"}

bearer_scheme = HTTPBearer(
    auto_error=False, bearerFormat="JWT", scheme_name="BearerAuth"
)


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    organisation_id: uuid.UUID
    role: str
    name: str | None = None
    dept: str | None = None


def require_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """Verify bearer JWT (``sub`` = user UUID) and load org membership."""
    token = (credentials.credentials if credentials else "") or ""
    if not token.strip():
        raise HTTPException(401, "Missing bearer token")
    try:
        user_id = security.decode_token(token.strip())
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"Invalid or expired token: {e}") from e

    user = user_repo.get_by_id(db, user_id)
    if not user:
        raise HTTPException(401, "Account not found — please sign in again")
    membership = org_repo.ensure_membership(db, user)
    return CurrentUser(
        id=user.id,
        email=user.email,
        organisation_id=membership.organisation_id,
        role=membership.role,
        name=user.name,
        dept=user.dept,
    )


def require_user_email(
    user: CurrentUser = Depends(require_user),
) -> str:
    """Compatibility dependency: return email string for legacy routes."""
    return user.email


def resolve_llm_credentials(
    request: Request, user_email: str
) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(api_key, provider)``. Header overrides stored ``llm_api_keys``."""
    header_key = request.headers.get(LLM_KEY_HEADER, "").strip() or None
    header_provider = (
        request.headers.get(LLM_PROVIDER_HEADER, "").strip().lower() or None
    )
    if header_provider not in _KNOWN_LLM_PROVIDERS:
        header_provider = None

    if header_key:
        return header_key, header_provider

    try:
        from catalogue import catalogue as _cat

        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            row = _cat.get_llm_api_key(conn, user_email)
        finally:
            conn.close()
    except Exception:
        return None, None

    if not row:
        return None, None
    stored_key = (row.get("api_key") or "").strip() or None
    stored_provider = (row.get("provider") or "").strip().lower() or None
    if stored_provider not in _KNOWN_LLM_PROVIDERS:
        stored_provider = None
    return stored_key, stored_provider


def _extractor_for(request: Request, user_email: str) -> TableExtractor:
    key, provider = resolve_llm_credentials(request, user_email)
    return TableExtractor(api_key=key, skip_llm=not key, provider=provider)


__all__ = [
    "CurrentUser",
    "LLM_KEY_HEADER",
    "LLM_PROVIDER_HEADER",
    "bearer_scheme",
    "require_user",
    "require_user_email",
    "resolve_llm_credentials",
    "_extractor_for",
    "get_db",
]
