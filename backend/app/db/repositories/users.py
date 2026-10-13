"""User persistence."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.user import User


def get_by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == email.lower().strip()))


def get_by_id(session: Session, user_id: uuid.UUID) -> User | None:
    return session.scalar(select(User).where(User.id == user_id))


def create_user(
    session: Session,
    email: str,
    password_hash: str,
    name: str | None = None,
    dept: str | None = None,
) -> User:
    email = email.lower().strip()
    existing = get_by_email(session, email)
    if existing:
        existing.password_hash = password_hash
        if name is not None:
            existing.name = name
        if dept is not None:
            existing.dept = dept
        session.flush()
        return existing
    user = User(
        email=email,
        id=uuid.uuid4(),
        password_hash=password_hash,
        name=name,
        dept=dept,
    )
    session.add(user)
    session.flush()
    return user
