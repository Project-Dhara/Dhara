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

Admin provisioning: `backend/scripts/create_user.py`.

## LLM & embeddings

Prefer pasting a **MEITY-empanelled LLM** key in **Settings**. Env vars are
optional for server-side defaults (OpenAI-/Anthropic-compatible endpoints):

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | MEITY-empanelled / Anthropic-compatible API key (optional if key in Settings) |
| `OPENAI_API_KEY` | MEITY-empanelled / OpenAI-compatible API key + embeddings (optional if key in Settings) |
| `SKIP_LLM` | Legacy flag; Excel path already skips LLM when no Settings/header key is sent. Prefer documenting “no key” over relying on this alone |
| `EMBEDDING_DIM` | Vector width (default 1536 for common small embedding models) |
| `EMBEDDING_MODEL` | Override embedding model if supported by code paths |

**PDF without a key:** PyMuPDF extraction still runs; ambiguous pages are
accepted heuristically and flagged for human review (see [on-prem](./on-prem.md)).

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

Occupation / standards CSVs are uploaded in the app (**Settings → Classification
code configuration**). They are stored in Postgres and are not part of env
config. Optional local test file path:

```text
backend/data/nco_2015_concordance.csv
```

(ignored by git; see `.example` for headers)

## Health checks

```bash
curl -s "$BASE/api/health"
```

Expect Postgres connectivity and pgvector readiness indicators used by the
health handler.
