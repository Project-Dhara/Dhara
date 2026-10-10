# Dhara refactor checklist

Branch: `code-revamp`. Updated as work completes.

## Pytest baseline (before edits)

Command: `.venv/bin/python -m pytest -q -m "not postgres and not slow"` from `backend/`.

Result (2026-10-10, `venv` Python 3.14): **23 collection ERRORs**. Root cause is an environment break (`ImportError: No module named expat` / missing `_XML_SetAllocTrackerActivationThreshold` when importing `openpyxl`), not assertion failures. Suite could not run to completion. Re-run after domain move; prefer Python 3.11 if available.

## Feature status

Structure migration (2026-10-11): domain modules live under `app/`. `backend/main.py` is the process entry. MCP lives in `app/mcp/`. psycopg2 and request-time DDL were not replaced.

| Feature | Status | Notes |
|---------|--------|-------|
| Auth signup/login/me | Complete | `app/api/routes/auth.py` |
| Org membership | Partial | DB + ensure_membership live; route enforcement incomplete |
| LLM credentials | In `app/` | HTTP uses the SQLAlchemy repository; encryption behavior is whatever that repository already did |
| Permissions / logging | Missing | Placeholder modules |
| Ingestion orchestration | In `app/services/ingestion` | Upload and wizard extractors stay separate |
| Confidence validation | Complete | `app/services/extraction/pdf/confidence_validation/` |
| PDF parse pipeline | In `app/services/extraction/pdf` | |
| Spreadsheet ingest | In `app/services/ingestion` | |
| Catalogue wizard extract | In `app/services/ingestion/wizard` | |
| PDF jobs / review / grouping | In `app/` | Routes in `app/api/routes/pdf.py`; store in `app/db/pdf_store.py` |
| Catalogue publish / browse | In `app/` | `app/api/routes/catalogue.py` plus `app/services` |
| Classification / NCO / standards | In `app/services/classification` and `app/services/standards` | |
| Metadata / KYDS fill | In `app/services/metadata` | Fill read is `app/db/kyds_psycopg.py`; HTTP KYDS is SQLAlchemy |
| Dashboard / access API | In `app/api/routes` | |
| Object storage | Partial | GCS or silent no-op; local unused |
| Vector store | In `app/storage/vectors.py` | |
| MCP | In `app/mcp/` | No org scope; `MCP_HTTP_AUTH` default `off` |
| Alembic baseline | Partial | Missing HNSW; request-time DDL still on |
| Startup / Docker | `uvicorn main:app` via `backend/main.py` | |
| Frontend API contracts | Unchanged by the structure move | |

## Slice progress

- [x] Move domain modules into `app/`
- [x] Delete legacy packages (except `main.py`, the uvicorn entry)
- [ ] Credentials, permissions, logging, frontend auth/key behavior changes
- [ ] Repositories replace psycopg2; thin-route cleanup; approval gate
- [ ] Clean Alembic baseline; remove request-time DDL
- [ ] MCP organisation scope and storage-backend selection
