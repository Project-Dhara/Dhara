"""GET/POST the authenticated caller's stored LLM API key."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser, require_user
from app.core.crypto import CredentialCryptoError
from app.core.permissions import MUTATING_ROLES, require_roles
from app.db.repositories import llm_keys as llm_repo
from app.db.session import get_db
from app.schemas.llm_key import LlmKeySaveRequest, LlmKeyStatusResponse

router = APIRouter(tags=["Settings"])


def _status_payload(status: llm_repo.LlmKeyStatus, *, extra: dict | None = None) -> dict:
    body = {
        "configured": status.configured,
        "provider": status.provider,
        "updated_at": status.updated_at,
        "api_key": status.api_key if status.configured else None,
        "base_url": status.base_url,
        "model": status.model,
        "crypto_error": status.crypto_error,
    }
    if extra:
        body.update(extra)
    return body


@router.get(
    "/api/llm-key",
    summary="Get LLM credential (decrypted for owner)",
    response_model=LlmKeyStatusResponse,
)
async def get_llm_key(
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    status = llm_repo.get_status(db, user.email)
    return _status_payload(status)


@router.post(
    "/api/llm-key",
    summary="Save or clear stored LLM API key",
    response_model=LlmKeyStatusResponse,
)
async def save_llm_key(
    body: LlmKeySaveRequest,
    user: CurrentUser = Depends(require_roles(*MUTATING_ROLES)),
    db: Session = Depends(get_db),
):
    api_key = (body.api_key or "").strip()
    provider = (body.provider or "").strip() or None
    base_url = (body.base_url or "").strip() or None
    model = (body.model or "").strip() or None
    if provider:
        provider = provider.lower()
        if provider in ("meity-empanelled llm",):
            provider = "openai"
        # Keep "self-hosted" as-is (OpenAI-compatible local endpoint).
    if not api_key:
        llm_repo.delete_key(db, user.email)
        return {
            "status": "cleared",
            "configured": False,
            "provider": None,
            "api_key": None,
            "base_url": None,
            "model": None,
            "crypto_error": False,
            "updated_at": None,
        }
    try:
        llm_repo.upsert(
            db,
            user.email,
            api_key,
            provider,
            base_url=base_url,
            model=model,
        )
    except CredentialCryptoError as e:
        raise HTTPException(500, str(e)) from e
    status = llm_repo.get_status(db, user.email)
    return _status_payload(status, extra={"status": "saved"})
