"""KYDS (Know Your Dataset) form routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser, require_user
from app.db.repositories import kyds as kyds_repo
from app.db.repositories import users as user_repo
from app.db.session import get_db
from app.schemas.kyds import (
    KydsMineResponse,
    KydsPatchResponse,
    KydsSaveRequest,
    KydsSaveResponse,
)

router = APIRouter(tags=["KYDS"])


def _serialize_entry(entry) -> dict:
    data = {
        "id": entry.id,
        "responses": entry.responses,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
    }
    return data


@router.post("/api/kyds", response_model=KydsSaveResponse)
async def save_kyds(
    body: KydsSaveRequest,
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    responses = body.responses
    if not isinstance(responses, dict):
        raise HTTPException(400, "responses must be an object")
    user_row = user_repo.get_by_email(db, user.email)
    entry = kyds_repo.save_entry(
        db,
        responses=responses,
        user_email=user.email,
        user_name=(user_row.name if user_row else None) or user.name,
        user_dept=(user_row.dept if user_row else None) or user.dept,
        organisation_id=user.organisation_id,
    )
    return {"id": entry.id, "status": "saved"}


@router.get("/api/kyds/mine", response_model=KydsMineResponse)
async def get_my_kyds(
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    entry = kyds_repo.get_latest_for_user(
        db, user.email, organisation_id=user.organisation_id
    )
    return {"entry": _serialize_entry(entry) if entry else None}


@router.patch("/api/kyds/{entry_id}", response_model=KydsPatchResponse)
async def patch_kyds(
    entry_id: int,
    body: KydsSaveRequest,
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    responses = body.responses
    if not isinstance(responses, dict):
        raise HTTPException(400, "responses must be an object")
    entry = kyds_repo.update_entry(
        db,
        entry_id,
        user.email,
        responses,
        organisation_id=user.organisation_id,
    )
    if not entry:
        raise HTTPException(404, "KYDS entry not found")
    return {"entry": _serialize_entry(entry), "status": "updated"}
