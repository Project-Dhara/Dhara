"""FastAPI application factory.

Deployment still starts via ``uvicorn main:app`` from ``backend/``;
``backend/main.py`` re-exports ``app`` from this module for compatibility.
"""
from __future__ import annotations

import os
import pathlib
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.routing import Route

from app.api.router import api_router
from app.core.exceptions import AppError
from app.core.startup import ensure_runtime_config
from app.mcp.http_asgi import mcp_http_handler, mcp_http_lifespan
from app.workers.runner import shutdown_job_runner

OPENAPI_TAGS = [
    {
        "name": "Health",
        "description": (
            "Probes (no JWT). `/api/live` = process up; "
            "`/api/ready` and `/api/health` = Postgres reachable (503 if not)."
        ),
    },
    {
        "name": "Auth",
        "description": (
            "Login issues a JWT. Send it as `Authorization: Bearer <token>` "
            "on every other route. `/api/me` checks the current session."
        ),
    },
    {"name": "KYDS", "description": "Know Your Dataset survey. JWT required."},
    {
        "name": "Settings",
        "description": "Per-user settings such as stored LLM API key. JWT required.",
    },
    {
        "name": "Catalogue",
        "description": "Excel/SQL extract → match → classify → publish. JWT required.",
    },
    {
        "name": "PDF",
        "description": "PDF extract → preview → grouping. JWT required.",
    },
    {
        "name": "Upload",
        "description": (
            "Unified upload → data ingestion by source type → "
            "extraction/validation job. JWT required."
        ),
    },
    {"name": "Dashboard", "description": "Workspace readiness rows. JWT required."},
    {
        "name": "Access",
        "description": (
            "Published catalogue query API (v1) for apps and agents. "
            "JWT required. MCP tools mirror these routes."
        ),
    },
]

# backend/static — parent of app/ is backend/ (override via DHARA_STATIC_UI_ROOT)
_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
_DEFAULT_STATIC_DIR = _BACKEND_DIR / "static"


def _resolve_ui_static_root() -> pathlib.Path:
    raw = (os.environ.get("DHARA_STATIC_UI_ROOT") or "").strip()
    if raw:
        custom = pathlib.Path(raw)
        if custom.is_dir():
            return custom
    return _DEFAULT_STATIC_DIR


def _parse_csv_env(name: str) -> list[str]:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _no_spa_fallback_prefix(full_path: str) -> bool:
    normalized = (full_path or "").lstrip("/")
    if not normalized:
        return False
    if normalized == "api" or normalized.startswith("api/"):
        return True
    if normalized == "mcp" or normalized.startswith("mcp/"):
        return True
    if normalized == ".well-known" or normalized.startswith(".well-known/"):
        return True
    return False


def _safe_path_under_root(root: pathlib.Path, *parts: str) -> Optional[pathlib.Path]:
    try:
        candidate = (root.joinpath(*parts)).resolve()
        candidate.relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    return candidate


def _resolve_static_file(root: pathlib.Path, full_path: str) -> Optional[pathlib.Path]:
    """Try ``path``, ``path/index.html``, then root ``index.html`` (SPA export)."""
    normalized = (full_path or "").strip().strip("/")
    if normalized:
        if ".." in pathlib.PurePosixPath(normalized).parts:
            return None
        direct = _safe_path_under_root(root, normalized)
        if direct is not None and direct.is_file():
            return direct
        index_under = _safe_path_under_root(root, normalized, "index.html")
        if index_under is not None and index_under.is_file():
            return index_under
    root_index = _safe_path_under_root(root, "index.html")
    if root_index is not None and root_index.is_file():
        return root_index
    return None


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    ensure_runtime_config()
    async with mcp_http_lifespan():
        try:
            yield
        finally:
            shutdown_job_runner(wait=False)


def _install_openapi(application: FastAPI) -> None:
    """Ensure Bearer JWT appears in /docs Authorize even for mixed public routes."""

    def custom_openapi():
        if application.openapi_schema:
            return application.openapi_schema
        schema = get_openapi(
            title=application.title,
            version=application.version or "0.1.0",
            description=application.description,
            routes=application.routes,
            tags=application.openapi_tags,
        )
        components = schema.setdefault("components", {})
        schemes = components.setdefault("securitySchemes", {})
        schemes["BearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": (
                "Paste the JWT from POST /api/login or /api/signup "
                "(token field only — do not type Bearer)."
            ),
        }
        application.openapi_schema = schema
        return application.openapi_schema

    application.openapi = custom_openapi  # type: ignore[method-assign]


def create_app() -> FastAPI:
    """Build and return the DHARA FastAPI application."""
    from app.core.logging import configure_logging

    configure_logging()
    application = FastAPI(
        title="DHARA API",
        version="0.1.0",
        description=(
            "Internal catalogue pipeline API.\n\n"
            "## JWT (try endpoints from /docs)\n\n"
            "1. Call **POST /api/signup** (if enabled) or **POST /api/login** — "
            "request bodies show email/password fields in Try it out.\n"
            "2. Copy `token` from the response.\n"
            "3. Click **Authorize**, paste the token only (do not type `Bearer`).\n"
            "4. Call authenticated endpoints. The token expires after 12 hours "
            "(or sooner if JWT_SECRET is rotated).\n\n"
            "Email must look like `name@organization.domain` "
            "(a dot is required in the domain).\n\n"
            "## Catalogue access (v1)\n\n"
            "Published datasets: **GET /api/v1/datasets**, "
            "**GET /api/v1/datasets/{id}**, "
            "**GET /api/v1/datasets/{id}/rows**.\n\n"
            "## MCP\n\n"
            "Remote Streamable HTTP: **`/mcp`** "
            "(tools: search_datasets, get_metadata, get_table). "
            "Open for published reads by default "
            "(`MCP_HTTP_AUTH=off`; set `jwt` for Bearer JWT, or `token` "
            "with `MCP_AUTH_TOKEN`). "
            "Local stdio: `python -m app.mcp` from `backend/`."
        ),
        openapi_tags=OPENAPI_TAGS,
        swagger_ui_parameters={"persistAuthorization": True},
        lifespan=_lifespan,
    )

    cors_origins = _parse_csv_env("DHARA_CORS_ORIGINS")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins if cors_origins else ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    allowed_hosts = _parse_csv_env("DHARA_ALLOWED_HOSTS")
    if allowed_hosts:
        for extra in ("localhost", "127.0.0.1"):
            if extra not in allowed_hosts:
                allowed_hosts.append(extra)
        application.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    static_root = _resolve_ui_static_root()
    assets_dir = static_root / "assets"

    @application.exception_handler(AppError)
    async def _app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message},
        )

    application.include_router(api_router)
    _install_openapi(application)

    # Streamable HTTP MCP — register before the SPA catch-all. Both slash forms
    # so clients that omit the trailing slash still work (no 307 on POST).
    mcp_asgi = mcp_http_handler()
    application.router.routes.insert(0, Route("/mcp", endpoint=mcp_asgi))
    application.router.routes.insert(0, Route("/mcp/", endpoint=mcp_asgi))

    if assets_dir.is_dir():
        application.mount(
            "/assets", StaticFiles(directory=str(assets_dir)), name="assets"
        )

    @application.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        # Never serve the SPA for OAuth / OIDC discovery probes. Claude and
        # other MCP brokers fetch /.well-known/*; HTML here looks like a
        # broken authorization server and fails client registration.
        if full_path == ".well-known" or full_path.startswith(".well-known/"):
            return JSONResponse(
                status_code=404,
                content={
                    "error": "not_found",
                    "message": (
                        "No OAuth discovery document at this path. "
                        "HTTP MCP is open by default (MCP_HTTP_AUTH=off)."
                    ),
                },
            )
        if _no_spa_fallback_prefix(full_path):
            raise HTTPException(status_code=404, detail="Not found")
        resolved = _resolve_static_file(static_root, full_path)
        if resolved is not None:
            return FileResponse(str(resolved))
        raise HTTPException(
            404, "Frontend not built. Run: cd frontend && npm run build"
        )

    return application


app = create_app()
