# Configuration reference

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

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Claude for reconstruction / enrich (optional if key in Settings) |
| `OPENAI_API_KEY` | Embeddings and some LLM paths |
| `SKIP_LLM` | `true` = heuristic mode; no Claude required |
| `EMBEDDING_DIM` | Vector width (default 1536 for text-embedding-3-small) |
| `EMBEDDING_MODEL` | Override embedding model if supported by code paths |

Stewards can also paste provider keys in **Settings** for local/demo use.

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
