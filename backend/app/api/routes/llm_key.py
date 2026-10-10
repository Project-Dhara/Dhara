"""GET/POST the authenticated caller's stored LLM API key."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser, require_user
from app.db.repositories import llm_keys as llm_repo
from app.db.session import get_db

router = APIRouter(tags=["Settings"])


@router.get("/api/llm-key", summary="Get stored LLM API key")
async def get_llm_key(
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    row = llm_repo.get(db, user.email)
    if not row:
        return {"provider": None, "api_key": None, "updated_at": None}
    return {
        "provider": row.provider,
        "api_key": row.api_key,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.post("/api/llm-key", summary="Save or clear stored LLM API key")
async def save_llm_key(
    request: Request,
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    data = await request.json()
    api_key = (data.get("api_key") or "").strip()
    provider = (data.get("provider") or "").strip() or None
    if not api_key:
        llm_repo.delete_key(db, user.email)
        return {"status": "cleared", "provider": None, "api_key": None}
    llm_repo.upsert(db, user.email, api_key, provider)
    return {"status": "saved", "provider": provider, "api_key": api_key}
