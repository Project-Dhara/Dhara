# Migrations (Alembic)

Schema changes for organisations, tenancy columns, and the ORM baseline are
managed with Alembic. **Do not** run migrations automatically on every API
request or app startup.

Request-time DDL in `catalogue.db.init_schema()` remains the default for
environments that have not yet applied Alembic. After you upgrade, set:

```bash
DISABLE_REQUEST_TIME_DDL=true
```

so routes stop creating/altering tables at request time.

## Prerequisites

- `DATABASE_URL` pointing at Postgres (same URL as the API)
- Dependencies from `backend/requirements.txt` (`SQLAlchemy`, `alembic`, `psycopg2-binary`)
- Working directory: `backend/`

## Upgrade (fresh or existing DB)

**Back up production data before upgrading.**

```bash
cd backend
alembic upgrade head
```

Revision `001_baseline_orgs_tenant` is **additive**:

- Ensures `users.id` (UUID, unique) while keeping `email` as PK
- Creates `organisations` + `organisation_memberships`
- Adds nullable `organisation_id` on tenant-scoped tables
- Inserts the default organisation (`DEFAULT_ORGANISATION_SLUG`, default `default`)
- Backfills memberships and `organisation_id` from existing `user_email` owners
- Attempts `CREATE EXTENSION IF NOT EXISTS vector` (safe to skip on hosts without pgvector)

## Stamp an already-migrated database

If you applied equivalent DDL manually and Alembic history is empty:

```bash
alembic stamp head
```

Only do this when the live schema already matches revision 001.

## Docker / compose

Run `alembic upgrade head` once before (or as a one-shot init container ahead of)
starting the API. Do **not** put `alembic upgrade` inside the per-request path.

Example (manual):

```bash
docker compose exec backend alembic upgrade head
```

Then set `DISABLE_REQUEST_TIME_DDL=true` on the backend service.

## Driver note

SQLAlchemy URLs are normalized to `postgresql+psycopg2://` in
`app.core.config`. Legacy `catalogue.db.get_connection()` continues to use
psycopg2 DSNs without the SQLAlchemy driver suffix.
