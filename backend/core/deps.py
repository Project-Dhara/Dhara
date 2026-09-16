"""Shared FastAPI dependencies and small helpers used across route modules."""
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core import auth as _auth
from extraction.extractor import TableExtractor

LLM_KEY_HEADER = "x-llm-api-key"
LLM_PROVIDER_HEADER = "x-llm-provider"
_KNOWN_LLM_PROVIDERS = {"anthropic", "openai"}

# Registers the Bearer JWT scheme in OpenAPI so /docs shows Authorize.
# auto_error=False keeps a missing token as HTTP 401 (same as before) instead
# of FastAPI's default 403 from the security scheme.
bearer_scheme = HTTPBearer(auto_error=False, bearerFormat="JWT", scheme_name="BearerAuth")


def require_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> str:
    """FastAPI dependency: verifies the bearer token and returns the email
    it carries. Every write-path route below depends on this so data is
    always stored under the authenticated caller, never a client-supplied
    value."""
    token = (credentials.credentials if credentials else "") or ""
    if not token.strip():
        raise HTTPException(401, "Missing bearer token")
    try:
        return _auth.decode_token(token.strip())
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"Invalid or expired token: {e}")


def _extractor_for(request: Request) -> TableExtractor:
    """Build a TableExtractor from the caller's own LLM API key (and chosen
    provider), sent on every LLM-backed request from the frontend's Settings
    screen. No key on the request means no LLM calls -- this replaces the old
    .env-based ANTHROPIC_API_KEY / SKIP_LLM toggle, which is no longer read."""
    key = request.headers.get(LLM_KEY_HEADER, "").strip() or None
    provider = request.headers.get(LLM_PROVIDER_HEADER, "").strip().lower() or None
    if provider not in _KNOWN_LLM_PROVIDERS:
        provider = None  # e.g. "self-hosted" or unset -- let extractor.py auto-detect
    return TableExtractor(api_key=key, skip_llm=not key, provider=provider)


def _read_file(file: UploadFile) -> bytes:
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Only .xlsx / .xls files are supported")
    if file.filename.lower().endswith(".xls"):
        raise HTTPException(
            400,
            "Legacy .xls format is not supported. Re-save the file as .xlsx in Excel.",
        )
    return None  # signal to caller to await
