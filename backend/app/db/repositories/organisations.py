"""Organisation and membership persistence."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.organisation import (
    ROLE_ADMINISTRATOR,
    ROLE_DATA_STEWARD,
    Organisation,
    OrganisationMembership,
)
from app.db.models.user import User


def get_by_slug(session: Session, slug: str) -> Organisation | None:
    return session.scalar(select(Organisation).where(Organisation.slug == slug))


def get_by_id(session: Session, org_id: uuid.UUID) -> Organisation | None:
    return session.get(Organisation, org_id)


def ensure_default_organisation(session: Session) -> Organisation:
    settings = get_settings()
    org = get_by_slug(session, settings.default_organisation_slug)
    if org:
        return org
    org = Organisation(
        id=uuid.uuid4(),
        name=settings.default_organisation_name,
        slug=settings.default_organisation_slug,
    )
    session.add(org)
    session.flush()
    return org


def get_membership(
    session: Session, user_id: uuid.UUID, organisation_id: uuid.UUID | None = None
) -> OrganisationMembership | None:
    stmt = select(OrganisationMembership).where(OrganisationMembership.user_id == user_id)
    if organisation_id is not None:
        stmt = stmt.where(OrganisationMembership.organisation_id == organisation_id)
    return session.scalars(stmt).first()


def ensure_membership(
    session: Session,
    user: User,
    organisation: Organisation | None = None,
    *,
    role: str | None = None,
) -> OrganisationMembership:
    org = organisation or ensure_default_organisation(session)
    existing = get_membership(session, user.id, org.id)
    if existing:
        return existing
    settings = get_settings()
    if role is None:
        if settings.bootstrap_admin_email and user.email == settings.bootstrap_admin_email:
            role = ROLE_ADMINISTRATOR
        else:
            # First membership in org becomes administrator if none exist.
            any_member = session.scalars(
                select(OrganisationMembership).where(
                    OrganisationMembership.organisation_id == org.id
                ).limit(1)
            ).first()
            role = ROLE_ADMINISTRATOR if not any_member else ROLE_DATA_STEWARD
    membership = OrganisationMembership(
        organisation_id=org.id,
        user_id=user.id,
        role=role,
    )
    session.add(membership)
    session.flush()
    return membership
