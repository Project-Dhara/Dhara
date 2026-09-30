"""Liveness / readiness probe behavior (no real Postgres required)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import main


client = TestClient(main.app)


def test_live_always_ok():
    r = client.get("/api/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_ok_when_postgres_reachable():
    conn = MagicMock()
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchone.return_value = (1,)
    conn.cursor.return_value = cur

    with (
        patch.object(main._cat, "get_connection", return_value=conn) as get_conn,
        patch.object(main._cat, "init_schema") as init_schema,
        patch("core.vector_store.vector_extension_ready", return_value=True),
        patch("core.vector_store.embedding_dim", return_value=384),
    ):
        r = client.get("/api/ready")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["checks"]["postgres"] is True
    assert body["checks"]["pgvector"] is True
    assert body["checks"]["embedding_dim"] == 384
    get_conn.assert_called_once()
    init_schema.assert_not_called()
    conn.close.assert_called_once()


def test_ready_503_when_postgres_down():
    with (
        patch.object(main._cat, "get_connection", side_effect=OSError("refused")),
        patch.object(main._cat, "init_schema") as init_schema,
    ):
        r = client.get("/api/ready")

    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["postgres"] is False
    assert body["checks"]["error"] == "OSError"
    init_schema.assert_not_called()


def test_ready_still_200_when_pgvector_missing():
    """pgvector is ancillary; readiness only requires Postgres."""
    conn = MagicMock()
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchone.return_value = (1,)
    conn.cursor.return_value = cur

    with (
        patch.object(main._cat, "get_connection", return_value=conn),
        patch("core.vector_store.vector_extension_ready", return_value=False),
        patch("core.vector_store.embedding_dim", return_value=384),
    ):
        r = client.get("/api/ready")

    assert r.status_code == 200
    assert r.json()["checks"]["pgvector"] is False


def test_health_aliases_ready():
    with patch.object(main._cat, "get_connection", side_effect=RuntimeError("boom")):
        live = client.get("/api/live")
        ready = client.get("/api/ready")
        health = client.get("/api/health")

    assert live.status_code == 200
    assert ready.status_code == 503
    assert health.status_code == 503
    assert ready.json() == health.json()
