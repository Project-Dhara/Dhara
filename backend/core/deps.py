"""Shared FastAPI dependencies and small helpers used across route modules."""
from typing import Optional, Tuple

import jwt
from fastapi import Depends, HTTPException, Request, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core import auth as _auth
from catalogue.extract.extractor import TableExtractor

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


def resolve_llm_credentials(
    request: Request, user_email: str
) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(api_key, provider)`` for LLM-backed work.

    ``X-Llm-Api-Key`` / ``X-Llm-Provider`` override a single request. When the
    key header is absent, load the caller's row from ``llm_api_keys``. Never
    logs the key. There is no server OPENAI_API_KEY / ANTHROPIC_API_KEY
    fallback.
    """
    header_key = request.headers.get(LLM_KEY_HEADER, "").strip() or None
    header_provider = request.headers.get(LLM_PROVIDER_HEADER, "").strip().lower() or None
    if header_provider not in _KNOWN_LLM_PROVIDERS:
        header_provider = None

    if header_key:
        return header_key, header_provider

    try:
        from catalogue import catalogue as _cat

        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            row = _cat.get_llm_api_key(conn, user_email)
        finally:
            conn.close()
    except Exception:
        return None, None

    if not row:
        return None, None
    stored_key = (row.get("api_key") or "").strip() or None
    stored_provider = (row.get("provider") or "").strip().lower() or None
    if stored_provider not in _KNOWN_LLM_PROVIDERS:
        stored_provider = None
    return stored_key, stored_provider


def _extractor_for(request: Request, user_email: str) -> TableExtractor:
    """Build a TableExtractor from the caller's LLM key (header or stored).

    No key means no LLM calls — there is no server env-key fallback.
    """
    key, provider = resolve_llm_credentials(request, user_email)
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
