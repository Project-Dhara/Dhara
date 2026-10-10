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
from app.services.credentials import service as credentials_service

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
    request: Request,
    user_email: str,
    db: Session | None = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(api_key, provider)`` from encrypted storage.

    ``request`` is accepted for call-site compatibility; header overrides are
    no longer honoured so keys never travel in browser storage or request
    headers.
    """
    del request  # unused — kept for signature compatibility during migration
    if db is not None:
        return credentials_service.resolve_for_user(db, user_email)

    from app.db.session import get_session_factory

    session = get_session_factory()()
    try:
        return credentials_service.resolve_for_user(session, user_email)
    finally:
        session.close()


def _extractor_for(request: Request, user_email: str):
    from app.services.ingestion.wizard.extractor import TableExtractor

    key, provider = resolve_llm_credentials(request, user_email)
    return TableExtractor(api_key=key, skip_llm=not key, provider=provider)


__all__ = [
    "CurrentUser",
    "bearer_scheme",
    "require_user",
    "require_user_email",
    "resolve_llm_credentials",
    "_extractor_for",
    "get_db",
]
