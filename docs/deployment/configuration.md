# Configuration reference

This page covers **deploy-time** environment variables and secrets
(`backend/.env`). Steward-facing **Configuration modules** (Dataset ID,
Metadata standard, Classification codes, MEITY LLM key) live in the app
**Settings** UI — see [Architecture — Configuration modules](../architecture.md#configuration-modules)
and [Pipeline overview](../pipeline/overview.md#configuration-modules).

Primary template: `backend/.env.example`. Copy to `backend/.env` for local and
Compose (Compose also overrides `DATABASE_URL` for the backend service).

## Required / strongly recommended

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Postgres connection string (pgvector-capable) |
| `JWT_SECRET` | Signs login JWTs — use a long random hex |

Generate a secret:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Auth

| Variable | Default | Purpose |
|----------|---------|---------|
| `ENABLE_SIGNUP` | `true` | Allow `POST /api/signup`. Set `false` in locked deploys |
| `MCP_HTTP_AUTH` | `off` | Remote `/mcp` auth: `off` (open published reads), `jwt` (login Bearer), or `token` (`MCP_AUTH_TOKEN` only) |
| `MCP_AUTH_TOKEN` | _(unset)_ | Optional long-lived Bearer for agents when auth is enabled |

Admin provisioning: `backend/scripts/create_user.py`.

## LLM & embeddings

Paste a **MEITY-empanelled LLM** key in **Settings**. All AI paths (Excel
metadata fill, NCO matching, PDF extraction/grouping/validation) use that
key via the `X-Llm-Api-Key` header. Server `OPENAI_API_KEY` /
`ANTHROPIC_API_KEY` are **not** used as fallbacks.

| Variable | Purpose |
|----------|---------|
| `EMBEDDING_DIM` | Vector width (default 1536 for common small embedding models) |
| `EMBEDDING_MODEL` | Override embedding model if supported by code paths |

**Without a Settings key:** Uploads and the pipeline still work using
heuristics. AI-assisted steps (richer PDF extraction, metadata auto-fill,
NCO matching, LLM grouping) degrade or are skipped. There is no server
env-key fallback.

## Object storage

| Variable | Purpose |
|----------|---------|
| `ENABLE_GCS` | `true` to upload Excel artefacts on catalogue push |
| `GCS_BUCKET_NAME` | Target bucket |

When `ENABLE_GCS=false`, catalogue metadata still writes; download URLs may be
empty.

## PDF grouping (optional tuning)

| Variable | Purpose |
|----------|---------|
| `PDF_GROUP_DISTANCE` | Cosine-distance threshold for leftover clustering |
| `PDF_GROUP_TOP_K` | Neighbour count for propose |

## Combined container (cloud / `make prod`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `PORT` | `8080` | Public Next.js port (Cloud Run/Render set this) |
| `BACKEND_PORT` | `8000` | Internal uvicorn port |
| `BACKEND_ORIGIN` | `http://127.0.0.1:8000` | Next → FastAPI rewrite target |

## Compose frontend

| Variable | Purpose |
|----------|---------|
| `BACKEND_ORIGIN` | Set to `http://backend:8000` in Compose so the Next container proxies correctly |

## Classification data

Occupation / standards CSVs are managed in the app (**Settings → Classification
code configuration**) and stored in Postgres. Optional local file:

```text
backend/data/nco_2015_concordance.csv
```

When present, the backend auto-registers it as **NCO 2015** in the Settings
list (selected if nothing else is). Stewards can still upload more standards.
The full CSV is gitignored; see `.example` for headers.

## Health checks

```bash
curl -s -o /dev/null -w "%{http_code}\n" "$BASE/api/live"    # 200 if process up
curl -s "$BASE/api/ready"                                    # 200 or 503
# /api/health is an alias of /api/ready
```

`/api/live` has no dependency checks. `/api/ready` runs a read-only
`SELECT 1` against Postgres and reports whether the `vector` extension is
present (`pgvector` is informational; missing pgvector does not fail
readiness). Unreachable Postgres returns **HTTP 503**.
