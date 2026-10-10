"""Compatibility re-export — handlers live in ``app.api.routes.kyds``."""
from app.api.routes.kyds import router  # noqa: F401

__all__ = ["router"]
