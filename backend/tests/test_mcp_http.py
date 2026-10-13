"""HTTP MCP mount: auth gate + initialize on /mcp and /mcp/."""
from __future__ import annotations

import json
import os
import uuid

import pytest
from starlette.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-mcp-http")

from app.core import security as _auth  # noqa: E402
from app.core.config import clear_settings_cache  # noqa: E402
from main import app  # noqa: E402

INIT_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def _parse_payload(response):
    """Handle JSON or SSE Streamable HTTP responses."""
    ctype = (response.headers.get("content-type") or "").lower()
    if "application/json" in ctype:
        return response.json()
    for line in response.text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return None


@pytest.fixture
def client():
    with TestClient(app, follow_redirects=False) as c:
        yield c


@pytest.fixture(autouse=True)
def _clear_settings():
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_mcp_requires_auth_by_default(client, monkeypatch):
    monkeypatch.delenv("MCP_HTTP_AUTH", raising=False)
    clear_settings_cache()
    r = client.post("/mcp", json=INIT_BODY, headers=MCP_HEADERS)
    assert r.status_code == 401
    assert r.json()["error"] == "unauthorized"


def test_mcp_open_when_auth_off(client, monkeypatch):
    monkeypatch.setenv("MCP_HTTP_AUTH", "off")
    clear_settings_cache()
    r = client.post("/mcp", json=INIT_BODY, headers=MCP_HEADERS)
    assert r.status_code == 200
    body = _parse_payload(r)
    assert body["result"]["serverInfo"]["name"] == "DHARA Catalogue"


def test_mcp_requires_bearer_when_jwt_mode(client, monkeypatch):
    monkeypatch.setenv("MCP_HTTP_AUTH", "jwt")
    clear_settings_cache()
    r = client.post("/mcp", json=INIT_BODY, headers=MCP_HEADERS)
    assert r.status_code == 401
    assert r.json()["error"] == "unauthorized"


def test_mcp_accepts_jwt_on_both_paths(client, monkeypatch):
    monkeypatch.setenv("MCP_HTTP_AUTH", "jwt")
    clear_settings_cache()
    token = _auth.create_token(uuid.uuid4(), email="mcp-tester@example.gov.in")
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {token}"}
    for path in ("/mcp", "/mcp/"):
        r = client.post(path, json=INIT_BODY, headers=headers)
        assert r.status_code == 200, (path, r.status_code, r.text[:300])
        body = _parse_payload(r)
        assert body and "result" in body


def test_mcp_accepts_static_token(client, monkeypatch):
    monkeypatch.setenv("MCP_HTTP_AUTH", "jwt")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "static-agent-token")
    clear_settings_cache()
    headers = {**MCP_HEADERS, "Authorization": "Bearer static-agent-token"}
    r = client.post("/mcp", json=INIT_BODY, headers=headers)
    assert r.status_code == 200


def test_mcp_lists_tools_when_auth_off(client, monkeypatch):
    monkeypatch.setenv("MCP_HTTP_AUTH", "off")
    clear_settings_cache()
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers=MCP_HEADERS,
    )
    assert r.status_code == 200
    body = _parse_payload(r)
    names = [t["name"] for t in body["result"]["tools"]]
    assert names == ["search_datasets", "get_metadata", "get_table"]
