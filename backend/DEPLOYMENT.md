# Dhara backend deployment

Postgres is the **source of truth** for catalogue metadata, auth, and upload job
state. Optional GCS holds Excel export blobs; pgvector holds an **ancillary**
semantic index (not authoritative for relationships).

## Requirements

- Python 3.11+ (Docker image uses 3.11)
- PostgreSQL 16+ with **pgvector** for semantic search (`semantic_embeddings`)
- Environment variables (see `backend/.env.example`)

## Database setup

### New environment

1. Create a Postgres database (local Docker, Neon, RDS, etc.).
2. Enable pgvector on first init (Docker: `backend/db/init-pgvector.sql`).
3. From `backend/`:

```bash
pip install -r requirements.txt
alembic upgrade head
```

4. Set `DISABLE_REQUEST_TIME_DDL=true` so the API does not run DDL on each request.

### Existing database (already on request-time DDL)

1. **Back up** the database.
2. Run `alembic upgrade head` (additive revision 001 — orgs, memberships, tenant columns).
3. Set `DISABLE_REQUEST_TIME_DDL=true`.
4. Ask users to **sign in again** (JWT `sub` is now user UUID).

See `migrations/README.md` for stamp/upgrade details.

## Portability policy (Postgres-first)

| Feature | Postgres | Notes |
|---------|----------|--------|
| Catalogue tables | Required | JSONB, `ON CONFLICT`, `ILIKE`, `TIMESTAMPTZ` |
| Upload jobs | Required | `pdf_jobs` JSONB + optional `pdf_bytes` BYTEA |
| Auth / orgs | Required | Alembic 001 |
| Semantic search | Optional | `CREATE EXTENSION vector`; `/api/ready` reports `pgvector` |
| Object storage | Optional | `ENABLE_GCS=true` + bucket; else Postgres-only URLs |
| SQLite / MySQL | Not supported | Do not target for production |

## Run locally

```bash
cd backend
cp .env.example .env   # edit JWT_SECRET, DATABASE_URL
./run.sh               # uvicorn main:app on :8000
```

## Docker Compose (repo root)

```bash
docker compose up -d postgres
# one-time on fresh volume:
docker compose run --rm backend alembic upgrade head
docker compose up -d --build backend frontend
```

Backend health: `GET /api/ready` (Postgres + optional pgvector check, no DDL).

Production combined image:

```bash
docker compose --profile prod up -d --build app postgres
```

## Environment variables

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | SQLAlchemy/psycopg2 DSN |
| `JWT_SECRET` | Bearer token signing |
| `DISABLE_REQUEST_TIME_DDL` | `true` after Alembic |
| `DEFAULT_ORGANISATION_SLUG` | Default tenant (default `default`) |
| `BOOTSTRAP_ADMIN_EMAIL` | First admin membership on signup |
| `ENABLE_GCS` / `GCS_BUCKET_NAME` | Catalogue Excel uploads to GCS |
| `STORAGE_LOCAL_PATH` | Local blob dir when using file storage dev tools |
| `EMBEDDING_DIM` | pgvector column width (default `1536`) |
| `MCP_HTTP_AUTH` | `off` (default), `jwt`, or `token` for `/mcp` |

LLM keys are per-user in the app (`llm_api_keys`), not server-wide env vars.

## Storage layout

| Data | Where |
|------|--------|
| PDF working bytes | `pdf_jobs.pdf_bytes` (BYTEA) |
| Job progress / results | `pdf_jobs` JSONB + in-memory cache |
| Catalogue rows | `datasets`, `dataset_rows`, `metadata_groups` |
| Export workbooks | GCS when enabled; URLs on dataset/group rows |
| Embeddings | `semantic_embeddings` (pgvector) |

Interfaces: `app.storage` (`ObjectStore`, `PgVectorStore`), workers: `app.workers`.

## Admin users

```bash
cd backend
python scripts/create_user.py user@org.example 'password' --name "Name" --dept "Team"
```

## Quality gates (CI)

GitHub Actions workflow `.github/workflows/backend-ci.yml` runs:

- `import main` / OpenAPI sanity
- `pytest` (unit tests; Postgres-marked tests skipped without DB)

Local:

```bash
cd backend
pytest -q
```

## Security checklist

- Set strong `JWT_SECRET`; disable public signup in production (`ENABLE_SIGNUP=false`).
- Use TLS to Postgres (`sslmode=require` on managed hosts).
- Restrict MCP exposure (`MCP_HTTP_AUTH=jwt` or `token` when agents are untrusted).
- Do not commit `backend/.env`.
