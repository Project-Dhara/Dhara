"""Compatibility re-export — handlers live in ``app.api.routes.llm_key``."""
from app.api.routes.llm_key import router  # noqa: F401

__all__ = ["router"]
