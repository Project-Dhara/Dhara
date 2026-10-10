"""FastAPI dependencies for authentication and authorization.

Re-exports live helpers from ``backend/core/deps.py`` so new route modules
can depend on ``app.api.dependencies`` without duplicating JWT/LLM logic.
Phase 4 will add organisation membership and role checks here.
"""
from core.deps import (  # noqa: F401
    LLM_KEY_HEADER,
    LLM_PROVIDER_HEADER,
    _extractor_for,
    bearer_scheme,
    require_user,
    resolve_llm_credentials,
)

__all__ = [
    "LLM_KEY_HEADER",
    "LLM_PROVIDER_HEADER",
    "bearer_scheme",
    "require_user",
    "resolve_llm_credentials",
    "_extractor_for",
]
