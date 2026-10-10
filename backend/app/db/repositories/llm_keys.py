"""Per-user LLM API key storage."""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.db.models.catalogue import LlmApiKey


def get(session: Session, user_email: str) -> LlmApiKey | None:
    return session.scalar(select(LlmApiKey).where(LlmApiKey.user_email == user_email))


def upsert(
    session: Session, user_email: str, api_key: str, provider: str | None = None
) -> LlmApiKey:
    row = get(session, user_email)
    if row:
        row.api_key = api_key
        row.provider = provider
        row.updated_at = func.now()
        session.flush()
        return row
    row = LlmApiKey(user_email=user_email, api_key=api_key, provider=provider)
    session.add(row)
    session.flush()
    return row


def delete_key(session: Session, user_email: str) -> bool:
    result = session.execute(
        delete(LlmApiKey).where(LlmApiKey.user_email == user_email)
    )
    session.flush()
    return (result.rowcount or 0) > 0
