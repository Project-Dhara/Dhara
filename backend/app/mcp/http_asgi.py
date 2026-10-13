"""Streamable HTTP ASGI surface for the catalogue MCP tools.

Mounted on the FastAPI app at ``/mcp`` and ``/mcp/`` (same ports as today).
Auth mirrors ``/api/v1`` by default (Bearer JWT). Optional long-lived
``MCP_AUTH_TOKEN``, or ``MCP_HTTP_AUTH=off`` for open read-only demos.
"""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import jwt
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from starlette.types import Receive, Scope, Send

from app.core import security as _auth

from . import mcp


def _auth_mode() -> str:
    """``jwt`` (default), ``token`` (MCP_AUTH_TOKEN only), or ``off``.

    Default matches Settings / OpenAPI: Bearer JWT required. Use
    ``MCP_HTTP_AUTH=off`` only for trusted demos.
    """
    from app.core.config import get_settings

    env = (os.environ.get("MCP_HTTP_AUTH") or "").strip().lower()
    if env:
        return env
    return (get_settings().mcp_http_auth or "jwt").strip().lower()


def _static_token() -> str:
    return (os.environ.get("MCP_AUTH_TOKEN") or "").strip()


def _bearer_from_scope(scope: Scope) -> str:
    for raw_key, raw_val in scope.get("headers") or []:
        if raw_key.lower() == b"authorization":
            value = raw_val.decode("latin-1", errors="ignore").strip()
            if value.lower().startswith("bearer "):
                return value[7:].strip()
            return ""
    return ""


def _token_ok(token: str) -> bool:
    if not token:
        return False
    static = _static_token()
    if static and token == static:
        return True
    mode = _auth_mode()
    if mode == "token":
        return False
    if mode == "off":
        return True
    try:
        _auth.decode_token(token)
        return True
    except (jwt.PyJWTError, RuntimeError, ValueError):
        return False


async def _send_json(send: Send, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"www-authenticate", b'Bearer realm="dhara-mcp"'),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _resolve_org_from_token(token: str):
    """Return organisation UUID for a validated JWT, or None."""
    if not token:
        return None
    static = _static_token()
    if static and token == static:
        return None
    try:
        from app.db.repositories import organisations as org_repo
        from app.db.repositories import users as user_repo
        from app.db.session import session_scope

        user_id = _auth.decode_token(token)
        with session_scope() as session:
            user = user_repo.get_by_id(session, user_id)
            if not user:
                return None
            membership = org_repo.ensure_membership(session, user)
            return membership.organisation_id
    except Exception:
        return None


async def _authorize_or_reject(scope: Scope, send: Send):
    """Return organisation_id (may be None) if authorized, else False."""
    if scope["type"] != "http" or scope.get("method") == "OPTIONS":
        return None
    mode = _auth_mode()
    if mode == "off":
        return None
    if mode == "token" and not _static_token():
        await _send_json(
            send,
            503,
            {
                "error": "mcp_auth_misconfigured",
                "message": "MCP_HTTP_AUTH=token requires MCP_AUTH_TOKEN",
            },
        )
        return False
    token = _bearer_from_scope(scope)
    if not _token_ok(token):
        await _send_json(
            send,
            401,
            {
                "error": "unauthorized",
                "message": (
                    "Bearer JWT (same as /api/v1) required"
                    + (" or MCP_AUTH_TOKEN" if _static_token() else "")
                ),
            },
        )
        return False
    if mode == "jwt":
        return _resolve_org_from_token(token)
    return None


def _fresh_session_manager():
    """Build a new StreamableHTTP session manager (run() is one-shot)."""
    mcp._session_manager = None
    mcp.streamable_http_app()
    return mcp.session_manager


class McpHttpASGI:
    """Auth gate + Streamable HTTP, always using the live session manager."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        from app.mcp import mcp_organisation_id

        auth = await _authorize_or_reject(scope, send)
        if auth is False:
            return
        token = mcp_organisation_id.set(auth)
        try:
            await StreamableHTTPASGIApp(mcp.session_manager)(scope, receive, send)
        finally:
            mcp_organisation_id.reset(token)


def mcp_http_handler() -> McpHttpASGI:
    return McpHttpASGI()


@asynccontextmanager
async def mcp_http_lifespan() -> AsyncIterator[None]:
    manager = _fresh_session_manager()
    async with manager.run():
        yield
