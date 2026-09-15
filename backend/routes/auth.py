"""Signup / login / session-check routes."""
import asyncio
import os

from fastapi import APIRouter, Depends, HTTPException, Request

from core import auth as _auth
from catalogue import catalogue as _cat
from core.deps import require_user

router = APIRouter(tags=["Auth"])


@router.get("/api/me", summary="Current session")
async def me(user_email: str = Depends(require_user)):
    """Validate the current session and return the signed-in profile.
    Used on app boot so a stale localStorage token after a backend restart
    clears the client session and returns the user to login."""
    def _run():
        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            return _cat.get_user_by_email(conn, user_email)
        finally:
            conn.close()

    user = await asyncio.to_thread(_run)
    if not user:
        raise HTTPException(401, "Account not found — please sign in again")
    return {
        "email": user["email"],
        "name": user.get("name") or user["email"],
        "dept": user.get("dept") or "",
    }

@router.post("/api/signup", summary="Sign up")
async def signup(request: Request):
    """Self-serve account creation. Enabled by default for dev — set
    ENABLE_SIGNUP=false to lock this down to admin-provisioned accounts
    only (see create_user.py) once this stops being a dev deployment."""
    if os.getenv("ENABLE_SIGNUP", "true").strip().lower() not in ("1", "true", "yes"):
        raise HTTPException(403, "Signup is disabled — ask an admin to create your account")

    data = await request.json()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    name = (data.get("name") or "").strip() or None
    dept = (data.get("dept") or "").strip() or None

    if not _auth.is_valid_org_email(email):
        raise HTTPException(400, "Email must be in name@organization.domain format")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")

    def _run():
        conn = _cat.get_connection()
        _cat.init_schema(conn)
        if _cat.get_user_by_email(conn, email):
            conn.close()
            return False
        _cat.create_user(conn, email, _auth.hash_password(password), name, dept)
        conn.close()
        return True

    try:
        created = await asyncio.to_thread(_run)
    except Exception as e:
        raise HTTPException(500, f"Signup error: {e}")

    if not created:
        raise HTTPException(409, "An account with that email already exists")

    token = _auth.create_token(email)
    return {"token": token, "email": email, "name": name, "dept": dept}


@router.post("/api/login", summary="Sign in")
async def login(request: Request):
    """Accounts are admin-provisioned only (see create_user.py) — this just
    verifies email/password and issues a bearer token."""
    data = await request.json()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not _auth.is_valid_org_email(email):
        raise HTTPException(400, "Email must be in name@organization.domain format")
    if not password:
        raise HTTPException(400, "Password is required")

    def _run():
        conn = _cat.get_connection()
        _cat.init_schema(conn)
        user = _cat.get_user_by_email(conn, email)
        conn.close()
        return user

    try:
        user = await asyncio.to_thread(_run)
    except Exception as e:
        raise HTTPException(500, f"Login error: {e}")

    if not user or not _auth.verify_password(password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")

    token = _auth.create_token(email)
    return {"token": token, "email": email, "name": user.get("name"), "dept": user.get("dept")}
