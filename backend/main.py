import pathlib
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Route

load_dotenv()

from catalogue import catalogue as _cat
from mcp_server.http_asgi import mcp_http_handler, mcp_http_lifespan
from routes import auth as routes_auth
from routes import access as routes_access
from routes import catalogue as routes_catalogue
from routes import dashboard as routes_dashboard
from routes import kyds as routes_kyds
from routes import pdf as routes_pdf
from routes import upload as routes_upload

OPENAPI_TAGS = [
    {
        "name": "Health",
        "description": (
            "Probes (no JWT). `/api/live` = process up; "
            "`/api/ready` and `/api/health` = Postgres reachable (503 if not)."
        ),
    },
    {"name": "Auth", "description": "Login issues a JWT. Send it as `Authorization: Bearer <token>` on every other route. `/api/me` checks the current session."},
    {"name": "KYDS", "description": "Know Your Dataset survey. JWT required."},
    {"name": "Catalogue", "description": "Excel/SQL extract → match → classify → publish. JWT required."},
    {"name": "PDF", "description": "PDF extract → preview → grouping. JWT required."},
    {"name": "Upload", "description": "Unified upload → data ingestion by source type → extraction/validation job. JWT required."},
    {"name": "Dashboard", "description": "Workspace readiness rows. JWT required."},
    {"name": "Access", "description": "Published catalogue query API (v1) for apps and agents. JWT required. MCP tools mirror these routes."},
]


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    async with mcp_http_lifespan():
        yield


app = FastAPI(
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
        "Open by default for published reads "
        "(`MCP_HTTP_AUTH=jwt` or `token` to require Bearer; optional `MCP_AUTH_TOKEN`). "
        "Local stdio: `python -m mcp_server` from `backend/`."
    ),
    openapi_tags=OPENAPI_TAGS,
    swagger_ui_parameters={"persistAuthorization": True},
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_auth.router)
app.include_router(routes_kyds.router)
app.include_router(routes_catalogue.router)
app.include_router(routes_pdf.router)
app.include_router(routes_upload.router)
app.include_router(routes_dashboard.router)
app.include_router(routes_access.router)

# Streamable HTTP MCP — register before the SPA catch-all. Both slash forms
# so clients that omit the trailing slash still work (no 307 on POST).
_mcp_asgi = mcp_http_handler()
app.router.routes.insert(0, Route("/mcp", endpoint=_mcp_asgi))
app.router.routes.insert(0, Route("/mcp/", endpoint=_mcp_asgi))


def _readiness_payload(response: Response) -> dict:
    """Postgres SELECT 1 for readiness; report pgvector without failing on it.

    Schema init / migrations must never run here — probes are read-only.
    """
    checks: dict = {"postgres": False, "pgvector": False}
    try:
        from core import vector_store as _vs

        conn = _cat.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            checks["postgres"] = True
            checks["pgvector"] = _vs.vector_extension_ready(conn)
            checks["embedding_dim"] = _vs.embedding_dim()
        finally:
            conn.close()
    except Exception as exc:
        checks["error"] = type(exc).__name__
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "checks": checks}

    if not checks["postgres"]:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "checks": checks}
    return {"status": "ready", "checks": checks}


@app.get("/api/live", tags=["Health"], summary="Liveness")
async def live():
    """Process is up. No dependency checks."""
    return {"status": "ok"}


@app.get("/api/ready", tags=["Health"], summary="Readiness")
async def ready(response: Response):
    """Ready for traffic when Postgres answers SELECT 1. Returns 503 otherwise."""
    return _readiness_payload(response)


@app.get("/api/health", tags=["Health"], summary="Health (readiness alias)")
async def health(response: Response):
    """Alias of `/api/ready` for existing docs and curl habits."""
    return _readiness_payload(response)


# --- Serve React frontend (production) ---
_static_dir = pathlib.Path(__file__).parent / "static"
_assets_dir = _static_dir / "assets"
_index_html = _static_dir / "index.html"

if _assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa(full_path: str):
    if _index_html.exists():
        return FileResponse(str(_index_html))
    raise HTTPException(404, "Frontend not built. Run: cd frontend && npm run build")
