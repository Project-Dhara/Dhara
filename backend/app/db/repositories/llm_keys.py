"""Per-user LLM API key storage (encrypted at rest)."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.core.crypto import (
    CredentialCryptoError,
    decrypt_secret,
    encrypt_secret,
    is_fernet_token,
)
from app.db.models.catalogue import LlmApiKey


@dataclass(frozen=True)
class LlmKeyStatus:
    configured: bool
    provider: str | None
    updated_at: str | None


def get(session: Session, user_email: str) -> LlmApiKey | None:
    return session.scalar(select(LlmApiKey).where(LlmApiKey.user_email == user_email))


def get_status(session: Session, user_email: str) -> LlmKeyStatus:
    row = get(session, user_email)
    if not row or not (row.api_key or "").strip():
        return LlmKeyStatus(configured=False, provider=None, updated_at=None)
    return LlmKeyStatus(
        configured=True,
        provider=row.provider,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


def get_decrypted(
    session: Session, user_email: str
) -> tuple[str | None, str | None]:
    """Return ``(api_key, provider)`` for server-side provider calls only."""
    row = get(session, user_email)
    if not row:
        return None, None
    raw = (row.api_key or "").strip()
    if not raw:
        return None, None
    provider = (row.provider or "").strip().lower() or None
    if is_fernet_token(raw):
        try:
            return decrypt_secret(raw), provider
        except CredentialCryptoError:
            return None, None
    # Legacy plaintext row — still usable until re-saved encrypted.
    return raw, provider


def upsert(
    session: Session, user_email: str, api_key: str, provider: str | None = None
) -> LlmApiKey:
    ciphertext = encrypt_secret(api_key.strip())
    row = get(session, user_email)
    if row:
        row.api_key = ciphertext
        row.provider = provider
        row.updated_at = func.now()
        session.flush()
        return row
    row = LlmApiKey(user_email=user_email, api_key=ciphertext, provider=provider)
    session.add(row)
    session.flush()
    return row


def delete_key(session: Session, user_email: str) -> bool:
    result = session.execute(
        delete(LlmApiKey).where(LlmApiKey.user_email == user_email)
    )
    session.flush()
    return (result.rowcount or 0) > 0
