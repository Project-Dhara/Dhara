# Dhara refactor checklist

Branch: `code-revamp`. Updated 2026-10-11 after modularisation phases 1–6.

## Feature status

| Feature | Status | Notes |
|---------|--------|-------|
| Auth signup/login/me | Complete | `AppError` hierarchy; global handler in `app.main` |
| Org membership | Complete | `organisations` service + repo; role gates on writes/reads |
| LLM credentials | Complete | SQLAlchemy repository |
| Permissions / logging | Complete | `require_roles`, `assert_org_access`; logging configured at startup |
| Domain exceptions | Complete | `AppError` → JSON via FastAPI handler |
| Ingestion orchestration | Complete | `app/services/ingestion` |
| Confidence validation | Complete | Under `app/services/extraction/pdf/confidence_validation/` |
| Catalogue / PDF / metadata | In `app/` | Session + repositories; some cursor helpers via `dbapi_connection` |
| Object storage | Partial | GCS / local via `STORAGE_BACKEND` |
| Vector store | Session API | `app/storage/vectors.py` |
| MCP | JWT default | Org-scoped query tools; `MCP_HTTP_AUTH=jwt` |
| Alembic | `001` + `002` | HNSW/indexes; request-time DDL off by default |
| Mega-module splits | Complete | header_utils, table_confidence, metadata_llm, pdf_grouping, catalogue routes |

## Slice progress

- [x] Move domain modules into `app/`
- [x] Delete legacy top-level packages
- [x] AppError handler + AuthError fold
- [x] Alembic 002 + disable request-time DDL by default
- [x] SQLAlchemy repositories (catalogue, datasets, pdf_jobs, staging, standards, kyds, vectors)
- [x] Hot paths use `session_scope` / `get_db` (pool via SA; no separate app-DB `psycopg2.connect`)
- [x] Org filters + `require_roles` on mutating routes; MCP JWT + org scope
- [x] Mega-module mechanical splits + catalogue route split
- [x] Leftovers: spreadsheet stub removed; `kyds_psycopg` removed; docs synced

## Remaining residue

- Cursor-based helpers in classification/standards/group_export still take a DBAPI connection from `dbapi_connection(session)` — rewrite to `session.execute` when touched next.
- External wizard `sql_extract` still uses `psycopg2.connect` for **user-supplied** DSNs (intentional).
- Legacy `organisation_id IS NULL` rows remain visible (`allow_null_legacy`).
