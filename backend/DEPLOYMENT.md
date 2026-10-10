# Dhara backend deployment

Postgres is the source of truth for users, catalogue rows, and upload jobs. Object storage is optional and, in the current code, only used for Excel export blobs. pgvector is an ancillary index.

This runbook lists configuration **names** and safe defaults. It does not contain production secrets. Do not paste API keys, JWT signing secrets, or database passwords into this file.

Inspection date: 2026-10-10. Behavior below is from code on `code-revamp`. Whether a deployed environment sets the recommended values is **runtime** and was not checked.

## Requirements

- Python 3.11+ (CI and the backend image use 3.11)
- PostgreSQL 16+ for catalogue and jobs
- pgvector when semantic grouping or `/api/ready`'s vector check must succeed
- A disposable database for tests. Never point tests at a developer or production database

## Configuration categories

### Database connection

| Variable | Role |
|----------|------|
| `DATABASE_URL` | Required for a real database. `app/core/config.py` rewrites `postgres://` and `postgresql://` to `postgresql+psycopg2://`. Inside Docker, localhost hosts are rewritten to the `postgres` service. |
| `DATABASE_POOL_SIZE` | SQLAlchemy pool. Default 10. |
| `DATABASE_MAX_OVERFLOW` | Default 20. |
| `DATABASE_POOL_TIMEOUT` | Default 30 seconds. |
| `DATABASE_SSLMODE` | Set `require` on managed Postgres. The field is loaded; confirm the DSN or this variable is what the host expects (**runtime**). |

psycopg2 catalogue calls use the same URL with the SQLAlchemy driver suffix stripped. They open a new connection per call. They do not use the SQLAlchemy pool.

The application does not support SQLite or MySQL. JSONB, arrays, `BYTEA`, `ON CONFLICT`, `ILIKE`, and optional pgvector are PostgreSQL-specific.

Local Compose sets a development database user and password in `docker-compose.yml`. That password is only for the local stack. Use a different credential for any shared or hosted database.

### Migrations

Schema changes belong in Alembic (`backend/migrations/`, revision `001_baseline` today).

```bash
cd backend
alembic upgrade head
```

`catalogue.db.init_schema()` still runs DDL on many requests when `DISABLE_REQUEST_TIME_DDL` is unset or false. `/api/ready` does not run DDL.

After a backup and a successful upgrade, set `DISABLE_REQUEST_TIME_DDL=true`. Alembic 001 does not create the HNSW index that `core/vector_store.py` creates. On a fresh database, semantic search indexes may be missing until that function runs or a later migration adds them. Confirm with `\d semantic_embeddings` (**runtime**).

Do not drop tables to "fix" drift. Add a forward migration.

### Authentication and signing

| Variable | Role |
|----------|------|
| `JWT_SECRET` | HMAC secret for access tokens. Required at login. Empty value raises when a token is created or decoded. Use a long random value, different per environment. |
| `JWT_EXP_SECONDS` | Access-token lifetime. Default 43200 (12 hours). No refresh token. |
| `ENABLE_SIGNUP` | Default **true** in code. Set `false` anywhere the API is reachable beyond a trusted dev machine. |
| `DEFAULT_ORGANISATION_SLUG` | Default `default`. Login attaches the user to this organisation. |
| `DEFAULT_ORGANISATION_NAME` | Display name used when the row is created. |
| `BOOTSTRAP_ADMIN_EMAIL` | If set, that email's first membership is `administrator`. Otherwise the first member of the org is admin and later signups are `data_steward`. |

Roles are stored and returned by `/api/me`. No HTTP handler enforces them yet. See `ARCHITECTURE.md`.

CORS allows every origin. Tighten this before exposing the API to a browser on the public internet.

### Credential encryption

Not implemented. LLM API keys are plaintext in `llm_api_keys.api_key`, returned by `GET /api/llm-key`, and cached in browser `localStorage`.

When encryption is added, configure:

| Variable | Role |
|----------|------|
| `LLM_CREDENTIALS_KEY` | Fernet key (or KMS key id) used only to encrypt provider credentials. Generate it outside the database. Do not commit it. Rotation: write new rows with a key version; keep the previous key until all rows are rewritten. |

There is no supported server-wide `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` for extraction. Users supply a key in Settings. Any key that was previously stored in the browser, returned by the API, or checked into history must be rotated at the provider and must not be reused in examples.

### Object storage

| Variable | Role |
|----------|------|
| `ENABLE_GCS` | Default false. |
| `GCS_BUCKET_NAME` | Required if GCS is true. Values starting with `your_` are treated as unset. |
| `STORAGE_LOCAL_PATH` | Default `data/object_store`. Used by `LocalFileStore`. |
| `STORAGE_BACKEND` | Default `auto`. **Loaded and unused.** `get_object_store()` picks GCS or a no-op. It does not select local files. |

PDF uploads are stored in `pdf_jobs.pdf_bytes`, not in the object store. GCS credentials are the platform's application-default credentials when the client library is invoked. Do not put a cloud private key in the repository.

### LLM provider

Provider name is per user (`anthropic` or `openai`), stored next to the key. Prompt text and model names live in `app/services/llm_prompts.py`, not in environment variables.

Grouping tunables (optional): `PDF_GROUP_DISTANCE`, `PDF_GROUP_TOP_K`, `EMBEDDING_DIM` (default 1536).

### Background work

There is no separate worker service, Celery, or RQ queue. `docker-compose.yml` runs one `uvicorn` process. Extraction threads die if that process restarts; finished jobs remain in Postgres and can be read again.

Do not put provider keys in job rows. Today the key is passed only as a worker argument. Keep it that way, and encrypt the database copy.

### MCP

| Variable | Role |
|----------|------|
| `MCP_HTTP_AUTH` | `off` (code default), `jwt`, or `token`. `off` serves catalogue tools with no identity. |
| `MCP_AUTH_TOKEN` | Shared bearer compared when mode is `token` (also accepted alongside JWT). |

HTTP tools are mounted at `/mcp` on the API port. Stdio is `python -m app.mcp` from `backend/`. Stdio trusts the OS user and loads `backend/.env`. Run it only as a dedicated account, with a database role that cannot read more than that account should see. The tools do not apply an organisation filter even when HTTP JWT is enabled.

`MCP_HTTP_AUTH` defaults to `off` in `app/mcp/http_asgi.py`. The OpenAPI text on the FastAPI app describes JWT as the usual client setup; that text is not the code default.

### Logging and health

| Probe | Meaning |
|-------|---------|
| `GET /api/live` | Process is up. No database. |
| `GET /api/ready` and `GET /api/health` | Postgres reachable. Does not run DDL. Reports pgvector as optional. |

Compose healthchecks call `/api/ready`.

`app/core/logging.py` does not configure handlers or redact secrets. Assume platform access logs may record `Authorization` and `X-Llm-Api-Key` until the proxy is configured to drop those headers (**runtime**).

## Deployment modes

| Mode | How it starts | Database | Signup | MCP | DDL |
|------|----------------|----------|--------|-----|-----|
| Host dev | `./run.sh` (`uvicorn main:app --reload`) | `DATABASE_URL` from `backend/.env` | Default on | Default off | Request-time DDL unless disabled |
| Compose dev | `backend` service, source mounted, `--reload` | URL overridden to the `postgres` service | Whatever `.env` sets, else default on | Same | Same |
| Compose prod profile | Root image, `start.sh` runs API and Next | Required env | Must be set | Must be set | Must be set |
| Render | Root `Dockerfile` | `DATABASE_URL` and `JWT_SECRET` configured on the service | Not set by `render.yaml` | Not set by `render.yaml` | Not set by `render.yaml` |
| CI | Import + pytest, no Postgres service | Dummy URL, fixed non-production JWT secret | Not exercised | Auth-mode unit tests only | Not applied |

`render.yaml` does not set `ENABLE_SIGNUP`, `MCP_HTTP_AUTH`, or `DISABLE_REQUEST_TIME_DDL`. Unset means the code defaults: signup on, MCP open, request-time DDL on.

## Local setup

```bash
cd backend
cp .env.example .env
# Set JWT_SECRET and DATABASE_URL. Leave LLM provider keys unset.
./run.sh
```

Compose:

```bash
docker compose up -d postgres
docker compose run --rm backend alembic upgrade head
docker compose up -d --build backend frontend
```

Health: `GET /api/ready`.

Combined image:

```bash
docker compose --profile prod up -d --build app postgres
```

## Admin users

```bash
cd backend
python scripts/create_user.py user@org.example 'password' --name "Name" --dept "Team"
```

The script uses the SQLAlchemy user repository and `ensure_membership`, not `catalogue/users.py`.

## Quality gates

`.github/workflows/backend-ci.yml`:

- Import `main` and assert at least 40 OpenAPI paths
- `pytest -q -m "not postgres and not slow"`

That workflow does not prove migrations, tenant isolation, or the upload-to-grouping path. See the end-to-end plan in `ARCHITECTURE.md`. This audit did not run CI.

## Security checklist

- Unique `JWT_SECRET` per environment. `ENABLE_SIGNUP=false` on shared deployments.
- TLS to Postgres (`sslmode=require` on hosted databases).
- `MCP_HTTP_AUTH=jwt` or `token` if `/mcp` is reachable. `off` publishes catalogue reads.
- After encryption exists: `LLM_CREDENTIALS_KEY` only in the secret store. Rotate any provider key that was stored in the browser or returned by `GET /api/llm-key`.
- `DISABLE_REQUEST_TIME_DDL=true` only after Alembic has been applied and vector indexes have been checked.
- Do not commit `backend/.env`.
