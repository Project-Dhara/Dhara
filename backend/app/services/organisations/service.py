"""Organisation membership workflows."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.db.models.organisation import OrganisationMembership
from app.db.models.user import User
from app.db.repositories import organisations as org_repo


def ensure_membership(session: Session, user: User) -> OrganisationMembership:
    return org_repo.ensure_membership(session, user)


def get_membership(
    session: Session, user_id: uuid.UUID
) -> OrganisationMembership | None:
    return org_repo.get_membership(session, user_id)


def ensure_default_organisation(session: Session):
    return org_repo.ensure_default_organisation(session)
