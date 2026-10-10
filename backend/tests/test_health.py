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
    with (
        patch("app.api.routes.health.ping_database", return_value=True),
        patch("app.api.routes.health.session_scope") as scope,
        patch("app.storage.vectors.vector_extension_ready", return_value=True),
        patch("app.storage.vectors.embedding_dim", return_value=384),
    ):
        session = MagicMock()
        scope.return_value.__enter__.return_value = session
        scope.return_value.__exit__.return_value = False
        r = client.get("/api/ready")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["checks"]["postgres"] is True
    assert body["checks"]["pgvector"] is True
    assert body["checks"]["embedding_dim"] == 384


def test_ready_503_when_postgres_down():
    with patch("app.api.routes.health.ping_database", return_value=False):
        r = client.get("/api/ready")

    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["postgres"] is False


def test_health_aliases_ready():
    with (
        patch("app.api.routes.health.ping_database", return_value=True),
        patch("app.api.routes.health.session_scope") as scope,
        patch("app.storage.vectors.vector_extension_ready", return_value=True),
        patch("app.storage.vectors.embedding_dim", return_value=384),
    ):
        session = MagicMock()
        scope.return_value.__enter__.return_value = session
        scope.return_value.__exit__.return_value = False
        r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"
