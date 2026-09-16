"""KYDS (Know Your Dataset) form routes."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from catalogue import catalogue as _cat
from core.deps import require_user

router = APIRouter(tags=["KYDS"])


@router.post("/api/kyds")
async def save_kyds(request: Request, user_email: str = Depends(require_user)):
    """Store a KYDS (Know Your Dataset) form submission in Postgres, always
    attributed to the authenticated caller (never a client-supplied email)."""
    data = await request.json()
    responses = data.get("responses")
    if not isinstance(responses, dict):
        raise HTTPException(400, "responses must be an object")

    def _run():
        conn = _cat.get_connection()
        _cat.init_schema(conn)
        user_row = _cat.get_user_by_email(conn, user_email) or {}
        entry_id = _cat.save_kyds_entry(conn, responses, {
            "email": user_email,
            "name": user_row.get("name"),
            "dept": user_row.get("dept"),
        })
        conn.close()
        return entry_id

    try:
        entry_id = await asyncio.to_thread(_run)
    except Exception as e:
        raise HTTPException(500, f"KYDS save error: {e}")
    return {"id": entry_id, "status": "saved"}


@router.get("/api/kyds/mine")
async def get_my_kyds(user_email: str = Depends(require_user)):
    """Returns the authenticated caller's own most recent KYDS entry (or
    None), so the console can show it and offer an edit option."""
    def _run():
        conn = _cat.get_connection()
        _cat.init_schema(conn)
        entry = _cat.get_own_latest_kyds_entry(conn, user_email)
        conn.close()
        return entry

    try:
        entry = await asyncio.to_thread(_run)
    except Exception as e:
        raise HTTPException(500, f"KYDS fetch error: {e}")
    if entry and entry.get("created_at"):
        entry["created_at"] = entry["created_at"].isoformat()
    return {"entry": entry}
