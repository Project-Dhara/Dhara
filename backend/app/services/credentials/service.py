"""Server-side LLM credential resolution (never expose raw keys over HTTP)."""
from __future__ import annotations

from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.repositories import llm_keys as llm_repo

_KNOWN_LLM_PROVIDERS = frozenset({"anthropic", "openai", "mock", "self-hosted"})


def resolve_for_user(
    session: Session, user_email: str
) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(api_key, provider)`` decrypted for provider calls."""
    override = get_settings().dhara_llm_provider
    if override == "mock":
        return "mock-key", "mock"

    key, provider = llm_repo.get_decrypted(session, user_email)
    if provider and provider not in _KNOWN_LLM_PROVIDERS:
        provider = None
    if provider == "self-hosted":
        provider = "openai"
    if provider == "mock" or (key and key.startswith("mock")):
        return key or "mock-key", "mock"
    return key, provider
