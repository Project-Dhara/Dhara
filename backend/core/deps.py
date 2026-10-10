"""Shared FastAPI dependencies — compatibility layer over ``app.api.dependencies``.

Legacy routes expect ``require_user`` to return an **email string**. New code
should import ``CurrentUser`` / ``require_user`` from ``app.api.dependencies``.
"""
from typing import Optional

from fastapi import Depends, HTTPException, Request, UploadFile

from app.api.dependencies import (  # noqa: F401
    LLM_KEY_HEADER,
    LLM_PROVIDER_HEADER,
    CurrentUser,
    _extractor_for,
    bearer_scheme,
    resolve_llm_credentials,
)
from app.api.dependencies import require_user as require_current_user


def require_user(user: CurrentUser = Depends(require_current_user)) -> str:
    """Return authenticated user email (legacy contract for unmigrated routes)."""
    return user.email


def require_current_user_dep(
    user: CurrentUser = Depends(require_current_user),
) -> CurrentUser:
    return user


def _read_file(file: UploadFile) -> bytes:
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Only .xlsx / .xls files are supported")
    if file.filename.lower().endswith(".xls"):
        raise HTTPException(
            400,
            "Legacy .xls format is not supported. Re-save the file as .xlsx in Excel.",
        )
    return None  # signal to caller to await
