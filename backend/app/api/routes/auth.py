"""Signup / login / session-check routes."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser, require_user
from app.db.session import get_db
from app.schemas.auth import AuthResponse, LoginRequest, MeResponse, SignupRequest
from app.services.auth import service as auth_service

router = APIRouter(tags=["Auth"])


@router.get("/api/me", summary="Current session", response_model=MeResponse)
async def me(
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    profile = auth_service.me(db, user.id)
    return MeResponse(
        email=profile.email,
        name=profile.name,
        dept=profile.dept,
        user_id=str(profile.user_id),
        organisation_id=str(profile.organisation_id),
        role=profile.role,
    )


@router.post("/api/signup", summary="Sign up", response_model=AuthResponse)
async def signup(body: SignupRequest, db: Session = Depends(get_db)):
    result = auth_service.signup(
        db,
        email=body.email or "",
        password=body.password or "",
        name=(body.name or "").strip() or None,
        dept=(body.dept or "").strip() or None,
    )
    return AuthResponse(
        token=result.token,
        email=result.email,
        name=result.name,
        dept=result.dept,
        user_id=str(result.user_id),
        organisation_id=str(result.organisation_id),
        role=result.role,
    )


@router.post("/api/login", summary="Sign in", response_model=AuthResponse)
async def login(body: LoginRequest, db: Session = Depends(get_db)):
    result = auth_service.login(
        db,
        email=body.email or "",
        password=body.password or "",
    )
    return AuthResponse(
        token=result.token,
        email=result.email,
        name=result.name,
        dept=result.dept,
        user_id=str(result.user_id),
        organisation_id=str(result.organisation_id),
        role=result.role,
    )
