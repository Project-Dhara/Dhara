"""FastAPI application factory.

Deployment still starts via ``uvicorn main:app`` from ``backend/``;
``backend/main.py`` re-exports ``app`` from this module for compatibility.
"""
from __future__ import annotations

import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Route

from app.api.router import api_router
from app.core.exceptions import AppError
from app.mcp.http_asgi import mcp_http_handler, mcp_http_lifespan

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

# backend/static — parent of app/ is backend/
_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
_STATIC_DIR = _BACKEND_DIR / "static"
_ASSETS_DIR = _STATIC_DIR / "assets"
_INDEX_HTML = _STATIC_DIR / "index.html"


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    async with mcp_http_lifespan():
        yield


def create_app() -> FastAPI:
    """Build and return the DHARA FastAPI application."""
    from app.core.logging import configure_logging

    configure_logging()
    application = FastAPI(
        title="DHARA API",
        description=(
            "Internal catalogue pipeline API.\n\n"
            "## JWT\n\n"
            "1. Call **POST /api/login** with `{ \"email\", \"password\" }` (no token).\n"
            "2. Copy `token` from the response.\n"
            "3. Click **Authorize**, paste the token only (do not type `Bearer`).\n"
            "4. Try authenticated endpoints. The token expires after 12 hours "
            "(or sooner if JWT_SECRET is rotated).\n\n"
            "## Catalogue access (v1)\n\n"
            "Published datasets: **GET /api/v1/datasets**, "
            "**GET /api/v1/datasets/{id}**, "
            "**GET /api/v1/datasets/{id}/rows**.\n\n"
            "## MCP\n\n"
            "Remote Streamable HTTP: **`/mcp`** "
            "(tools: search_datasets, get_metadata, get_table). "
            "Requires Bearer JWT by default "
            "(`MCP_HTTP_AUTH=jwt`; use `token` with `MCP_AUTH_TOKEN`, "
            "or `off` only for trusted demos). "
            "Local stdio: `python -m app.mcp` from `backend/`."
        ),
        openapi_tags=OPENAPI_TAGS,
        swagger_ui_parameters={"persistAuthorization": True},
        lifespan=_lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.exception_handler(AppError)
    async def _app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message},
        )

    application.include_router(api_router)

    # Streamable HTTP MCP — register before the SPA catch-all. Both slash forms
    # so clients that omit the trailing slash still work (no 307 on POST).
    mcp_asgi = mcp_http_handler()
    application.router.routes.insert(0, Route("/mcp", endpoint=mcp_asgi))
    application.router.routes.insert(0, Route("/mcp/", endpoint=mcp_asgi))

    if _ASSETS_DIR.exists():
        application.mount(
            "/assets", StaticFiles(directory=str(_ASSETS_DIR)), name="assets"
        )

    @application.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        if _INDEX_HTML.exists():
            return FileResponse(str(_INDEX_HTML))
        raise HTTPException(
            404, "Frontend not built. Run: cd frontend && npm run build"
        )

    return application


app = create_app()
