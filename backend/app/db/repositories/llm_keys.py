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
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    crypto_error: bool = False


def get(session: Session, user_email: str) -> LlmApiKey | None:
    return session.scalar(select(LlmApiKey).where(LlmApiKey.user_email == user_email))


def get_status(session: Session, user_email: str) -> LlmKeyStatus:
    """Status for the key owner: ``configured`` only when decrypt succeeds."""
    row = get(session, user_email)
    if not row or not (row.api_key or "").strip():
        return LlmKeyStatus(configured=False, provider=None, updated_at=None)
    updated_at = row.updated_at.isoformat() if row.updated_at else None
    provider = (row.provider or "").strip().lower() or None
    raw_base = getattr(row, "base_url", None)
    raw_model = getattr(row, "model", None)
    base_url = raw_base.strip() or None if isinstance(raw_base, str) else None
    model = raw_model.strip() or None if isinstance(raw_model, str) else None
    raw = (row.api_key or "").strip()
    if is_fernet_token(raw):
        try:
            plaintext = decrypt_secret(raw)
        except CredentialCryptoError:
            return LlmKeyStatus(
                configured=False,
                provider=provider,
                updated_at=updated_at,
                base_url=base_url,
                model=model,
                crypto_error=True,
            )
        return LlmKeyStatus(
            configured=True,
            provider=provider,
            updated_at=updated_at,
            api_key=plaintext,
            base_url=base_url,
            model=model,
        )
    # Legacy plaintext row — still usable until re-saved encrypted.
    return LlmKeyStatus(
        configured=True,
        provider=provider,
        updated_at=updated_at,
        api_key=raw,
        base_url=base_url,
        model=model,
    )


def get_decrypted(
    session: Session, user_email: str
) -> tuple[str | None, str | None, str | None, str | None]:
    """Return ``(api_key, provider, base_url, model)`` for server-side calls only."""
    status = get_status(session, user_email)
    if not status.configured or not status.api_key:
        return None, None, None, None
    return status.api_key, status.provider, status.base_url, status.model


def upsert(
    session: Session,
    user_email: str,
    api_key: str,
    provider: str | None = None,
    *,
    base_url: str | None = None,
    model: str | None = None,
) -> LlmApiKey:
    ciphertext = encrypt_secret(api_key.strip())
    prov = (provider or "").strip().lower() or None
    # Only self-hosted stores an OpenAI-compatible endpoint; cloud saves must
    # clear leftover localhost URLs from a prior Ollama configuration.
    if prov == "self-hosted":
        stored_base = (base_url or "").strip() or None
        stored_model = (model or "").strip() or None
    else:
        stored_base = None
        stored_model = None
    row = get(session, user_email)
    if row:
        row.api_key = ciphertext
        row.provider = provider
        row.base_url = stored_base
        row.model = stored_model
        row.updated_at = func.now()
        session.flush()
        return row
    row = LlmApiKey(
        user_email=user_email,
        api_key=ciphertext,
        provider=provider,
        base_url=stored_base,
        model=stored_model,
    )
    session.add(row)
    session.flush()
    return row


def delete_key(session: Session, user_email: str) -> bool:
    result = session.execute(
        delete(LlmApiKey).where(LlmApiKey.user_email == user_email)
    )
    session.flush()
    return (result.rowcount or 0) > 0
