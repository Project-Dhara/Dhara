"""Worker claim helper and enqueue dispatch mode."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.db.repositories import pdf_jobs as pdf_jobs_repo
from app.services.jobs import enqueue as enqueue_mod


def test_claim_next_queued_job_skips_batch_children():
    parent = SimpleNamespace(
        job_id="parent",
        status="queued",
        stage="queued",
        percent=0,
        message="Queued",
        filename="a.pdf",
        user_email="u@example.org",
        created_at_epoch=1.0,
        created_at=None,
        result=None,
        error=None,
        reviews={},
        deleted_table_ids=[],
        grouping_status=None,
        pipeline_step=None,
        source_type="pdf",
        organisation_id=None,
        updated_at=None,
    )
    child = SimpleNamespace(
        job_id="child",
        status="queued",
        stage="queued",
        percent=0,
        message="Queued",
        filename="b.pdf",
        user_email="u@example.org",
        created_at_epoch=2.0,
        created_at=None,
        result=None,
        error=None,
        reviews={"__parent_batch_id": "batch1"},
        deleted_table_ids=[],
        grouping_status=None,
        pipeline_step=None,
        source_type="pdf",
        organisation_id=None,
        updated_at=None,
    )
    session = MagicMock()
    session.scalars.return_value.all.return_value = [child, parent]

    claimed = pdf_jobs_repo.claim_next_queued_job(session)
    assert claimed is not None
    assert claimed["job_id"] == "parent"
    assert parent.status == "running"
    assert child.status == "queued"
    session.flush.assert_called()


def test_dispatch_extraction_queues_without_inline(monkeypatch):
    monkeypatch.delenv("DHARA_INLINE_JOBS", raising=False)
    with (
        patch("app.workers.extraction_jobs.queue_extraction_job") as queue,
        patch("app.workers.runner.submit_extraction_job") as submit,
    ):
        out = enqueue_mod.dispatch_extraction(
            job_id="j1",
            filename="f.pdf",
            user_email="u@example.org",
            source_type="pdf",
            file_bytes=b"%PDF",
        )
        queue.assert_called_once()
        submit.assert_not_called()
        assert out["job_id"] == "j1"


def test_dispatch_extraction_inline_when_enabled(monkeypatch):
    monkeypatch.setenv("DHARA_INLINE_JOBS", "1")
    with (
        patch("app.workers.extraction_jobs.queue_extraction_job") as queue,
        patch("app.workers.runner.submit_extraction_job") as submit,
    ):
        enqueue_mod.dispatch_extraction(
            job_id="j2",
            filename="f.pdf",
            user_email="u@example.org",
            source_type="pdf",
            file_bytes=b"%PDF",
        )
        queue.assert_called_once()
        submit.assert_called_once()
