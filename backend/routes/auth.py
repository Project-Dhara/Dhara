"""Compatibility re-export — handlers live in ``app.api.routes.auth``."""
from app.api.routes.auth import router  # noqa: F401

__all__ = ["router"]
