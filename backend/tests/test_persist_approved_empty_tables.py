"""Continue → Grouping must stop when a job has no extracted tables."""

from __future__ import annotations

import pytest

from app.core.exceptions import AppError
from app.services.jobs import pdf_review as pdf_review_mod


def test_persist_approved_rejects_empty_extraction(monkeypatch):
    job = {
        "job_id": "job-empty",
        "user_email": "steward@example.com",
        "status": "done",
        "filename": "empty.xlsx",
        "result": {},
        "reviews": {},
        "deleted_table_ids": [],
    }

    monkeypatch.setattr(pdf_review_mod, "_get_pdf_job", lambda _job_id: job)
    monkeypatch.setattr(pdf_review_mod, "_pdf_tables_from_job", lambda _job: [])
    monkeypatch.setattr(
        pdf_review_mod, "job_extraction_complete", lambda status: status == "done"
    )

    with pytest.raises(AppError) as exc:
        pdf_review_mod.persist_approved_and_group(
            job_id="job-empty",
            user_email="steward@example.com",
        )

    assert exc.value.status_code == 400
    assert "No tables were extracted" in exc.value.message
