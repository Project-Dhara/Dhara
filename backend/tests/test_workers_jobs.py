"""Extraction job registry (public view + queue)."""
from __future__ import annotations

from unittest.mock import patch

from app.workers.extraction_jobs import (
    _pdf_job_public,
    _pdf_jobs,
    _pdf_jobs_lock,
    queue_extraction_job,
)


def test_pdf_job_public_strips_heavy_fields():
    job = {
        "job_id": "abc",
        "status": "running",
        "result": {1: {"tables": []}},
        "pdf_bytes": b"secret",
        "reviews": {},
    }
    public = _pdf_job_public(job)
    assert "result" not in public
    assert "pdf_bytes" not in public
    assert public["job_id"] == "abc"


def test_queue_extraction_job_registers_and_persists():
    with patch("app.workers.extraction_jobs._save_pdf_job") as save:
        queue_extraction_job(
            job_id="j1",
            filename="f.pdf",
            user_email="u@example.org",
            source_type="pdf",
            file_bytes=b"%PDF",
            organisation_id="00000000-0000-0000-0000-000000000001",
        )
        save.assert_called_once()
        assert save.call_args.kwargs.get("pdf_bytes") == b"%PDF"
    with _pdf_jobs_lock:
        assert "j1" in _pdf_jobs
        assert _pdf_jobs["j1"]["status"] == "queued"
        del _pdf_jobs["j1"]


def test_queue_extraction_job_retains_single_csv_bytes():
    with patch("app.workers.extraction_jobs._save_pdf_job") as save:
        queue_extraction_job(
            job_id="csv1",
            filename="data.csv",
            user_email="u@example.org",
            source_type="csv",
            file_bytes=b"a,b\n1,2\n",
        )
        save.assert_called_once()
        assert save.call_args.kwargs.get("pdf_bytes") == b"a,b\n1,2\n"
    with _pdf_jobs_lock:
        assert _pdf_jobs["csv1"]["reviews"].get("__retain_file_bytes") is True
        del _pdf_jobs["csv1"]


def test_queue_extraction_job_retains_single_excel_bytes():
    with patch("app.workers.extraction_jobs._save_pdf_job") as save:
        queue_extraction_job(
            job_id="xlsx1",
            filename="data.xlsx",
            user_email="u@example.org",
            source_type="excel",
            file_bytes=b"PK\x03\x04",
        )
        save.assert_called_once()
        assert save.call_args.kwargs.get("pdf_bytes") == b"PK\x03\x04"
    with _pdf_jobs_lock:
        assert _pdf_jobs["xlsx1"]["reviews"].get("__retain_file_bytes") is True
        del _pdf_jobs["xlsx1"]
