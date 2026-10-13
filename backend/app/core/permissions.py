"""Role and membership checks for authenticated users."""
from __future__ import annotations

from typing import Iterable

from fastapi import Depends

from app.core.exceptions import ForbiddenError
from app.db.models.organisation import (
    ROLE_ADMINISTRATOR,
    ROLE_DATA_STEWARD,
    ROLE_DATA_USER,
)

# Roles that may ingest, review, group, and publish.
MUTATING_ROLES = frozenset({ROLE_ADMINISTRATOR, ROLE_DATA_STEWARD})
# Roles that may read organisation catalogue and dashboard.
READ_ROLES = frozenset({ROLE_ADMINISTRATOR, ROLE_DATA_STEWARD, ROLE_DATA_USER})


def role_display(role: str) -> str:
    """Map server role tokens to UI labels."""
    return {
        ROLE_ADMINISTRATOR: "Administrator",
        ROLE_DATA_STEWARD: "Data Steward",
        ROLE_DATA_USER: "Data User",
    }.get((role or "").strip().lower(), role or "")


def role_from_display(label: str) -> str | None:
    """Map UI labels (or raw tokens) to server role tokens."""
    raw = (label or "").strip().lower().replace(" ", "_")
    aliases = {
        "administrator": ROLE_ADMINISTRATOR,
        "admin": ROLE_ADMINISTRATOR,
        "data_steward": ROLE_DATA_STEWARD,
        "data-steward": ROLE_DATA_STEWARD,
        "data_user": ROLE_DATA_USER,
        "data-user": ROLE_DATA_USER,
    }
    return aliases.get(raw)


def require_roles(*allowed: str):
    """FastAPI dependency factory: user must hold one of ``allowed`` roles."""
    from app.api.dependencies import CurrentUser, require_user

    allowed_set = frozenset(a.strip().lower() for a in allowed)

    def _dep(user: CurrentUser = Depends(require_user)) -> CurrentUser:
        if (user.role or "").strip().lower() not in allowed_set:
            raise ForbiddenError("Insufficient permissions for this action")
        return user

    return _dep


def assert_org_access(
    resource_org_id,
    user_org_id,
    *,
    allow_null_legacy: bool = False,
) -> None:
    """Raise NotFoundError if the resource is outside the caller's organisation."""
    from app.core.exceptions import NotFoundError

    if resource_org_id is None:
        if allow_null_legacy:
            return
        raise NotFoundError("Not found")
    if str(resource_org_id) != str(user_org_id):
        raise NotFoundError("Not found")


def can_mutate(role: str) -> bool:
    return (role or "").strip().lower() in MUTATING_ROLES


def can_read(role: str) -> bool:
    return (role or "").strip().lower() in READ_ROLES


def ensure_role_in(role: str, allowed: Iterable[str], message: str = "Forbidden") -> None:
    from app.core.exceptions import ForbiddenError

    if (role or "").strip().lower() not in {a.strip().lower() for a in allowed}:
        raise ForbiddenError(message)


__all__ = [
    "MUTATING_ROLES",
    "READ_ROLES",
    "ROLE_ADMINISTRATOR",
    "ROLE_DATA_STEWARD",
    "ROLE_DATA_USER",
    "assert_org_access",
    "can_mutate",
    "can_read",
    "ensure_role_in",
    "require_roles",
    "role_display",
    "role_from_display",
]
