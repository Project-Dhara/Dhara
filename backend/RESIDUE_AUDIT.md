# Legacy residue audit

Updated 2026-10-11 after modularisation (SQLAlchemy Session, org gates, mega-splits).

## What remains outside `backend/app/`

| Path | Why it remains |
|------|----------------|
| `backend/main.py` | Process entry. Re-exports `app.main.app`. |
| `backend/migrations/` | Alembic (`001_baseline`, `002_indexes_hnsw`). |
| `backend/tests/`, `backend/scripts/` | Test/ops layout. |

## Canonical homes

| Concern | Path |
|---------|------|
| HTTP routes | `app/api/routes/` (catalogue split: extract/publish/browse/standards) |
| SQLAlchemy session/repos | `app/db/session.py`, `app/db/repositories/` |
| PDF jobs | `app/db/repositories/pdf_jobs.py` (`pdf_store.py` is a re-export) |
| Catalogue query/publish | `app/db/repositories/catalogue.py`, `datasets.py` |
| Staging | `app/db/repositories/staging.py` |
| Vectors | `app/storage/vectors.py` (Session API) |
| Workers | `app/workers/extraction_jobs.py` |
| MCP | `app/mcp/` — JWT default, org-scoped tools |
| Pooled DBAPI bridge | `app/db/psycopg.get_connection` → SQLAlchemy `raw_connection` (no separate DSN connect); `init_schema` no-op |

## Intentionally kept

- External wizard `sql_extract` uses `psycopg2.connect` for **user-supplied** DSNs.
- Some classification/standards/group_export helpers still use `conn.cursor()` via `dbapi_connection(session)`.
- Legacy rows with `organisation_id IS NULL` remain visible to the caller’s org.

## Removed / fixed vs prior audit

- Request-time DDL default **off** (`DISABLE_REQUEST_TIME_DDL=true`).
- `kyds_psycopg.py` deleted; KYDS reads use SQLAlchemy repo.
- MCP auth default **jwt**; tools receive org from JWT context.
- Empty `extraction/spreadsheet` package deleted.
