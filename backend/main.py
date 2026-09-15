import pathlib

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from catalogue import catalogue as _cat
from routes import auth as routes_auth
from routes import catalogue as routes_catalogue
from routes import dashboard as routes_dashboard
from routes import kyds as routes_kyds
from routes import pdf as routes_pdf

OPENAPI_TAGS = [
    {"name": "Health", "description": "Liveness. No JWT."},
    {"name": "Auth", "description": "Login issues a JWT. Send it as `Authorization: Bearer <token>` on every other route. `/api/me` checks the current session."},
    {"name": "KYDS", "description": "Know Your Dataset survey. JWT required."},
    {"name": "Catalogue", "description": "Excel/SQL extract → match → classify → publish. JWT required."},
    {"name": "PDF", "description": "PDF extract → preview → grouping. JWT required."},
    {"name": "Dashboard", "description": "Workspace readiness rows. JWT required."},
]

app = FastAPI(
    title="DHARA API",
    description=(
        "Internal catalogue pipeline API.\n\n"
        "## JWT\n\n"
        "1. Call **POST /api/login** with `{ \"email\", \"password\" }` (no token).\n"
        "2. Copy `token` from the response.\n"
        "3. Click **Authorize**, paste the token only (do not type `Bearer`).\n"
        "4. Try authenticated endpoints. The token expires after 12 hours and is "
        "invalidated when the backend process restarts."
    ),
    openapi_tags=OPENAPI_TAGS,
    swagger_ui_parameters={"persistAuthorization": True},
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
app.include_router(routes_dashboard.router)


@app.get("/api/health", tags=["Health"], summary="Health")
async def health():
    out = {"status": "ok", "pgvector": False}
    try:
        from core import vector_store as _vs
        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            out["pgvector"] = _vs.vector_extension_ready(conn)
            out["embedding_dim"] = _vs.embedding_dim()
        finally:
            conn.close()
    except Exception as exc:
        out["pgvector_error"] = str(exc)
    return out


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
