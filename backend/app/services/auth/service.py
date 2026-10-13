"""Authentication and session workflows."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.core.exceptions import AppError, ConflictError, ForbiddenError, UnauthorizedError
from app.db.repositories import organisations as org_repo
from app.db.repositories import users as user_repo


@dataclass
class AuthResult:
    token: str
    email: str
    name: str | None
    dept: str | None
    user_id: uuid.UUID
    organisation_id: uuid.UUID
    role: str


def signup(
    session: Session,
    *,
    email: str,
    password: str,
    name: str | None = None,
    dept: str | None = None,
) -> AuthResult:
    settings = get_settings()
    if not settings.enable_signup:
        raise ForbiddenError(
            "Signup is disabled — ask an admin to create your account"
        )
    email = (email or "").strip().lower()
    if not security.is_valid_org_email(email):
        raise AppError("Email must be in name@organization.domain format")
    if len(password or "") < 8:
        raise AppError("Password must be at least 8 characters")
    if user_repo.get_by_email(session, email):
        raise ConflictError("An account with that email already exists")

    user = user_repo.create_user(
        session, email, security.hash_password(password), name, dept
    )
    membership = org_repo.ensure_membership(session, user)
    token = security.create_token(user.id, email=user.email)
    return AuthResult(
        token=token,
        email=user.email,
        name=user.name,
        dept=user.dept,
        user_id=user.id,
        organisation_id=membership.organisation_id,
        role=membership.role,
    )


def login(session: Session, *, email: str, password: str) -> AuthResult:
    email = (email or "").strip().lower()
    if not security.is_valid_org_email(email):
        raise AppError("Email must be in name@organization.domain format")
    if not password:
        raise AppError("Password is required")
    user = user_repo.get_by_email(session, email)
    if not user or not security.verify_password(password, user.password_hash):
        raise UnauthorizedError("Invalid email or password")
    membership = org_repo.ensure_membership(session, user)
    token = security.create_token(user.id, email=user.email)
    return AuthResult(
        token=token,
        email=user.email,
        name=user.name,
        dept=user.dept,
        user_id=user.id,
        organisation_id=membership.organisation_id,
        role=membership.role,
    )


def me(session: Session, user_id: uuid.UUID) -> AuthResult:
    user = user_repo.get_by_id(session, user_id)
    if not user:
        raise UnauthorizedError("Account not found — please sign in again")
    membership = org_repo.ensure_membership(session, user)
    return AuthResult(
        token="",
        email=user.email,
        name=user.name or user.email,
        dept=user.dept or "",
        user_id=user.id,
        organisation_id=membership.organisation_id,
        role=membership.role,
    )
