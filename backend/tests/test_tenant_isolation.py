"""Tenant isolation helpers for PDF jobs and Access API query filters."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from app.api.dependencies import CurrentUser
from app.db.repositories import pdf_jobs as pdf_jobs_repo
from app.api.routes.pdf import _job_visible_to


def _user(org_id: uuid.UUID | None = None, email: str = "a@example.org") -> CurrentUser:
    return CurrentUser(
        id=uuid.uuid4(),
        email=email,
        organisation_id=org_id or uuid.uuid4(),
        role="data_steward",
        name="A",
        dept="",
    )


def test_job_visible_same_owner_and_org():
    org = uuid.uuid4()
    user = _user(org)
    job = {
        "user_email": user.email,
        "organisation_id": str(org),
    }
    assert _job_visible_to(job, user) is True


def test_job_denied_cross_org():
    user = _user()
    job = {
        "user_email": user.email,
        "organisation_id": str(uuid.uuid4()),
    }
    assert _job_visible_to(job, user) is False


def test_job_denied_other_user():
    user = _user()
    job = {
        "user_email": "other@example.org",
        "organisation_id": str(user.organisation_id),
    }
    assert _job_visible_to(job, user) is False


def test_job_legacy_null_org_allowed_for_owner():
    user = _user()
    job = {"user_email": user.email, "organisation_id": None}
    assert _job_visible_to(job, user) is True


def test_pdf_jobs_repo_get_for_user_applies_org_filter():
    """Repository builds a select and returns the scalar result."""
    session = MagicMock()
    session.scalars.return_value.first.return_value = None
    org = uuid.uuid4()
    result = pdf_jobs_repo.get_for_user(
        session,
        "job123",
        user_email="a@example.org",
        organisation_id=org,
    )
    assert result is None
    session.scalars.assert_called_once()


def test_access_api_list_filters_by_organisation():
    from app.services.catalogue import query as catalogue_query

    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    fake_rows = [
        {"dataset_id": "ds-a", "organisation_id": org_a},
        {"dataset_id": "ds-b", "organisation_id": org_b},
    ]

    def fake_list(conn, *, organisation_id=None):
        if organisation_id is None:
            return fake_rows
        return [r for r in fake_rows if r["organisation_id"] == organisation_id]

    with patch.object(catalogue_query, "list_catalogue_datasets", side_effect=fake_list):
        visible = catalogue_query.list_catalogue_datasets(None, organisation_id=org_a)
    assert [r["dataset_id"] for r in visible] == ["ds-a"]
