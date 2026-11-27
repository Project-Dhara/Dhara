"""NCO match job helpers (fingerprint, status file, dual response shapes)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.classification import nco_match_jobs as jobs


def test_compute_fingerprint_includes_owner_and_is_stable():
    a = jobs.compute_fingerprint(
        owner="a@example.com",
        values=["Teacher", "Nurse"],
        context={"column": "occ"},
        standard_id=1,
        alias_counter=0,
        llm_on=False,
    )
    b = jobs.compute_fingerprint(
        owner="a@example.com",
        values=["Nurse", "Teacher"],
        context={"column": "occ"},
        standard_id=1,
        alias_counter=0,
        llm_on=False,
    )
    c = jobs.compute_fingerprint(
        owner="b@example.com",
        values=["Teacher", "Nurse"],
        context={"column": "occ"},
        standard_id=1,
        alias_counter=0,
        llm_on=False,
    )
    assert a == b
    assert a != c


def test_compute_fingerprint_changes_with_alias_counter():
    base = dict(
        owner="a@example.com",
        values=["Teacher"],
        context={},
        standard_id=1,
        llm_on=False,
    )
    f0 = jobs.compute_fingerprint(**base, alias_counter=0)
    f1 = jobs.compute_fingerprint(**base, alias_counter=1)
    assert f0 != f1


def test_worker_status_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("DHARA_DATA_DIR", str(tmp_path))
    jobs.write_worker_status("busy:pdf", detail="abc")
    status = jobs.read_worker_status(max_age_sec=30)
    assert status["fresh"] is True
    assert status["state"] == "busy:pdf"
    assert (tmp_path / "worker_status.json").is_file()


def test_job_public_includes_max_wait_sec(monkeypatch):
    monkeypatch.setenv("DHARA_NCO_MATCH_TIMEOUT_SEC", "600")
    pub = jobs.job_public(
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "status": "queued",
            "stage": "queued",
            "fingerprint": "abc",
        }
    )
    assert pub["job_id"]
    assert pub["max_wait_sec"] == 600.0
    assert "matches" not in pub


def test_worker_max_above_client(monkeypatch):
    monkeypatch.setenv("DHARA_NCO_MATCH_TIMEOUT_SEC", "600")
    monkeypatch.setenv("DHARA_NCO_WORKER_MAX_SEC", "720")
    assert jobs.worker_max_runtime_sec() >= jobs.client_max_wait_sec()


@pytest.mark.asyncio
async def test_match_nco_desktop_returns_job_id(monkeypatch):
    monkeypatch.setenv("DHARA_DESKTOP", "1")
    monkeypatch.setenv("DHARA_NCO_LLM", "off")

    from app.api.routes import catalogue_standards as mod

    body = MagicMock()
    body.model_dump.return_value = {"values": ["Teacher"], "context": None}
    request = MagicMock()
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = (1,)

    payload = {
        "job_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "attach_token": "ffffffff-0000-1111-2222-333333333333",
        "status": "queued",
        "stage": "queued",
        "max_wait_sec": 600.0,
    }

    with patch(
        "app.services.classification.nco_match_jobs.maintenance",
        lambda session: None,
    ), patch(
        "app.services.classification.nco_match_jobs.enqueue_or_attach",
        return_value=dict(payload),
    ), patch(
        "app.services.classification.nco_match_jobs.read_worker_status",
        return_value={"state": "idle", "fresh": True},
    ):
        result = await mod.match_nco(request, body, user_email="u@example.com", db=db)

    assert result["job_id"] == payload["job_id"]
    assert result["attach_token"] == payload["attach_token"]
    assert result.get("status") == "queued"


@pytest.mark.asyncio
async def test_match_nco_docker_returns_sync_matches(monkeypatch):
    monkeypatch.setenv("DHARA_DESKTOP", "0")
    monkeypatch.setenv("DHARA_NCO_LLM", "off")

    from app.api.routes import catalogue_standards as mod

    body = MagicMock()
    body.model_dump.return_value = {"values": ["Teacher"], "context": None}
    request = MagicMock()
    db = MagicMock()

    session = MagicMock()
    scope_cm = MagicMock()
    scope_cm.__enter__.return_value = session
    scope_cm.__exit__.return_value = None

    with patch.object(mod, "session_scope", return_value=scope_cm), patch.object(
        mod, "dbapi_connection", return_value=MagicMock()
    ), patch.object(mod, "ensure_classification_standard_loaded"), patch(
        "app.services.classification.nco_matching.match_occupations",
        return_value={"Teacher": {"code": "23", "title": "Teachers"}},
    ), patch(
        "app.services.classification.nco_embedder.retrieval_status",
        return_value={"retrieval_mode": "keyword-only", "retrieval_reason": ""},
    ):
        result = await mod.match_nco(request, body, user_email="u@example.com", db=db)

    assert "matches" in result
    assert "Teacher" in result["matches"]
    assert "job_id" not in result
