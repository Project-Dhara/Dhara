# Legacy residue audit

Updated 2026-10-11 after the file-structure migration. The 2026-10-10 inventory described packages that have since been removed.

## What remains outside `backend/app/`

| Path | Why it remains |
|------|----------------|
| `backend/main.py` | Process entry. Re-exports `app.main.app` so `uvicorn main:app`, `run.sh`, Docker, and Render stay valid. |

No other `catalogue/`, `pdf/`, `routes/`, `core/`, `data_ingestion/`, `metadata/`, or `backend/config.py` package remains.

## Where the old owners live

| Former path | Canonical path |
|-------------|----------------|
| `routes/*.py` | `app/api/routes/` |
| `catalogue/db.py` | `app/db/psycopg.py` |
| `pdf/pdf_store.py` | `app/db/pdf_store.py` |
| `catalogue/kyds.py` | `app/db/kyds_psycopg.py` (metadata-fill read only; HTTP KYDS uses `app/db/repositories/kyds.py`) |
| `pdf/pdf_jobs.py` | `app/workers/extraction_jobs.py` |
| `pdf/pdf_grouping.py` | `app/services/grouping/pdf_grouping.py` |
| `data_ingestion/`, `metadata/`, `catalogue/*` logic | `app/services/` |
| `core/` | `app/core/`, `app/api/dependencies.py`, `app/storage/` |
| `mcp_server/` | `app/mcp/` (`python -m app.mcp`) |
| `backend/config.py` | `app/services/llm_prompts.py` |

`catalogue/llm_keys.py` and `catalogue/users.py` had no in-repo callers besides the old facade. They were deleted with that facade. HTTP credentials and users stay on the SQLAlchemy repositories.

## Intentionally unchanged behavior

- psycopg2 connections and request-time DDL, including `DISABLE_REQUEST_TIME_DDL` defaulting off and the existing `init_schema` order.
- `app/db/repositories/pdf_jobs.py` is still the narrow SQLAlchemy helper. PDF persistence is `app/db/pdf_store.py`.
- MCP tools still call `app/services/catalogue/query.py` with the same arguments and no organisation filter. `MCP_HTTP_AUTH` still defaults to `off`.
- Preview continue still requires `status == "done"` only.

SQLAlchemy is used for auth, organisations, KYDS HTTP, and LLM keys. It is not the persistence path for catalogue or PDF jobs.
