"""Signup / login / session-check routes."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser, require_user
from app.db.session import get_db
from app.services.auth import service as auth_service

router = APIRouter(tags=["Auth"])


@router.get("/api/me", summary="Current session")
async def me(
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    profile = auth_service.me(db, user.id)
    return {
        "email": profile.email,
        "name": profile.name,
        "dept": profile.dept,
        "user_id": str(profile.user_id),
        "organisation_id": str(profile.organisation_id),
        "role": profile.role,
    }


@router.post("/api/signup", summary="Sign up")
async def signup(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    try:
        result = auth_service.signup(
            db,
            email=data.get("email") or "",
            password=data.get("password") or "",
            name=(data.get("name") or "").strip() or None,
            dept=(data.get("dept") or "").strip() or None,
        )
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e
    return {
        "token": result.token,
        "email": result.email,
        "name": result.name,
        "dept": result.dept,
        "user_id": str(result.user_id),
        "organisation_id": str(result.organisation_id),
        "role": result.role,
    }


@router.post("/api/login", summary="Sign in")
async def login(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    try:
        result = auth_service.login(
            db,
            email=data.get("email") or "",
            password=data.get("password") or "",
        )
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e
    return {
        "token": result.token,
        "email": result.email,
        "name": result.name,
        "dept": result.dept,
        "user_id": str(result.user_id),
        "organisation_id": str(result.organisation_id),
        "role": result.role,
    }
