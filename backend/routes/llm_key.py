"""GET/POST the authenticated caller's stored LLM API key."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from catalogue import catalogue as _cat
from core.deps import require_user

router = APIRouter(tags=["Settings"])


@router.get("/api/llm-key", summary="Get stored LLM API key")
async def get_llm_key(user_email: str = Depends(require_user)):
    """Return this user's stored key/provider, or nulls when unset.

    Only the authenticated caller can read their own row. Never log the key.
    """

    def _run():
        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            return _cat.get_llm_api_key(conn, user_email)
        finally:
            conn.close()

    try:
        row = await asyncio.to_thread(_run)
    except Exception as e:
        raise HTTPException(500, f"LLM key fetch error: {e}") from e

    if not row:
        return {"provider": None, "api_key": None, "updated_at": None}

    updated = row.get("updated_at")
    return {
        "provider": row.get("provider"),
        "api_key": row.get("api_key"),
        "updated_at": updated.isoformat() if updated else None,
    }


@router.post("/api/llm-key", summary="Save or clear stored LLM API key")
async def save_llm_key(request: Request, user_email: str = Depends(require_user)):
    """Upsert ``{ api_key, provider }`` for the caller.

    An empty ``api_key`` deletes the row so Settings can clear the key.
    ``user_email`` always comes from the JWT.
    """
    data = await request.json()
    api_key = (data.get("api_key") or "").strip()
    provider = (data.get("provider") or "").strip() or None

    def _run():
        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            if not api_key:
                _cat.delete_llm_api_key(conn, user_email)
                return {"status": "cleared", "provider": None, "api_key": None}
            _cat.upsert_llm_api_key(conn, user_email, api_key, provider)
            return {"status": "saved", "provider": provider, "api_key": api_key}
        finally:
            conn.close()

    try:
        result = await asyncio.to_thread(_run)
    except Exception as e:
        raise HTTPException(500, f"LLM key save error: {e}") from e
    return result
