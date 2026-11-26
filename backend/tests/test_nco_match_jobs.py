"""File-queue NCO match jobs used on desktop."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.classification.nco_match_jobs import enqueue_nco_match, read_job


def test_enqueue_writes_queued_job(tmp_path, monkeypatch):
    monkeypatch.setenv("DHARA_DATA_DIR", str(tmp_path))
    job_id = enqueue_nco_match(values=["Teacher", "Nurse"], context={"column": "occ"})
    job = read_job(job_id)
    assert job is not None
    assert job["status"] == "queued"
    assert job["values"] == ["Teacher", "Nurse"]
    assert (tmp_path / "nco_match_jobs" / f"{job_id}.json").is_file()
    raw = json.loads(Path(tmp_path, "nco_match_jobs", f"{job_id}.json").read_text(encoding="utf-8"))
    assert raw["job_id"] == job_id
