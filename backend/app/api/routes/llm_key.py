"""GET/POST the authenticated caller's stored LLM API key (metadata only)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser, require_user
from app.core.crypto import CredentialCryptoError
from app.core.permissions import MUTATING_ROLES, require_roles
from app.db.repositories import llm_keys as llm_repo
from app.db.session import get_db

router = APIRouter(tags=["Settings"])


@router.get("/api/llm-key", summary="Get LLM credential status")
async def get_llm_key(
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    status = llm_repo.get_status(db, user.email)
    return {
        "configured": status.configured,
        "provider": status.provider,
        "updated_at": status.updated_at,
    }


@router.post("/api/llm-key", summary="Save or clear stored LLM API key")
async def save_llm_key(
    request: Request,
    user: CurrentUser = Depends(require_roles(*MUTATING_ROLES)),
    db: Session = Depends(get_db),
):
    data = await request.json()
    api_key = (data.get("api_key") or "").strip()
    provider = (data.get("provider") or "").strip() or None
    if provider:
        provider = provider.lower()
        if provider in ("meity-empanelled llm", "self-hosted"):
            provider = "openai" if provider.startswith("meity") else provider
    if not api_key:
        llm_repo.delete_key(db, user.email)
        return {"status": "cleared", "configured": False, "provider": None}
    try:
        llm_repo.upsert(db, user.email, api_key, provider)
    except CredentialCryptoError as e:
        raise HTTPException(500, str(e)) from e
    status = llm_repo.get_status(db, user.email)
    return {
        "status": "saved",
        "configured": status.configured,
        "provider": status.provider,
        "updated_at": status.updated_at,
    }
