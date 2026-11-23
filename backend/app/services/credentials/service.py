"""Server-side LLM credential resolution (never expose raw keys over HTTP)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.repositories import llm_keys as llm_repo
from app.services.llm_client import env_llm_base_url, env_llm_model

_KNOWN_LLM_PROVIDERS = frozenset({"anthropic", "openai", "mock", "self-hosted"})


@dataclass(frozen=True)
class LlmCredentials:
    api_key: Optional[str]
    provider: Optional[str]
    base_url: Optional[str] = None
    model: Optional[str] = None

    def __iter__(self):
        """Allow ``key, provider = resolve_for_user(...)`` for legacy call sites."""
        yield self.api_key
        yield self.provider

    def __getitem__(self, index: int):
        """Allow ``resolve_for_user(...)[0]`` for api_key."""
        return (self.api_key, self.provider, self.base_url, self.model)[index]


def resolve_for_user(session: Session, user_email: str) -> LlmCredentials:
    """Return credentials for provider calls (key, provider, base_url, model)."""
    override = get_settings().dhara_llm_provider
    if override == "mock":
        return LlmCredentials("mock-key", "mock")

    key, provider, base_url, model = llm_repo.get_decrypted(session, user_email)
    if provider and provider not in _KNOWN_LLM_PROVIDERS:
        provider = None
    # Keep provider as self-hosted for model resolution; client still uses OpenAI SDK.
    if provider == "mock" or (key and key.startswith("mock")):
        return LlmCredentials(key or "mock-key", "mock")

    # Env fallbacks for desktop Compose (LLM_BASE_URL / LLM_MODEL).
    if not base_url:
        base_url = env_llm_base_url()
    if not model:
        model = env_llm_model()
    if base_url and not provider:
        provider = "self-hosted"
    return LlmCredentials(key, provider, base_url, model)
