# DHARA — Technical Architecture

## 1. System Overview

DHARA is a data-cataloguing tool: a user uploads raw Excel/SQL datasets or PDF statistical reports (plus optional metadata workbooks), the system extracts tables, classifies/harmonises their columns against coded taxonomies, and publishes the result into a Postgres catalogue. That catalogue is browsable in the app’s Catalogue UI, and is designed so the same query layer can later back MCP tools/resources for agents.

```
┌────────────────────┐        ┌─────────────────────────┐        ┌──────────────────────┐
│   Frontend          │  HTTP  │   Backend (FastAPI)      │  SQL   │   Postgres            │
│   Next.js 14        │◄──────►│   Python, uvicorn        │◄──────►│   (+ pgvector)        │
│   :3000 (dev)       │        │   :8000 (dev)            │        │   catalogue tables    │
└────────────────────┘        └─────────────────────────┘        └──────────────────────┘
                                        │
                                        ▼
                              ┌───────────────────┐
                              │  MEITY Empanelled  │
                              │      LLM APIs       │
                              │ (user-supplied key) │
                              └───────────────────┘
```

- **Dev**: `docker-compose.yml` runs 3 containers — `postgres` (`pgvector/pgvector:pg16`, :5432), `backend` (:8000, `uvicorn main:app --reload`), `frontend` (:3000, Next.js). `Makefile` wraps common commands (`make up/down/logs/psql/prod`).
- **Prod**: root `Dockerfile` + `start.sh` run **both** FastAPI (internal `BACKEND_PORT`) and Next.js (public `PORT`); Next proxies `/api/*` to the backend. Combined image is exposed on :8080 (`make prod`).
- **Database**: Postgres + **pgvector**. Catalogue / auth tables remain the source of truth; `semantic_embeddings` holds ancillary vectors (`backend/core/vector_store.py`). Connected via `DATABASE_URL` (Neon-hosted in production — enable the pgvector extension there too).

## 2. Backend layout (`backend/`)

Routes are thin FastAPI routers; domain logic lives in packages. External callers still use `from catalogue import catalogue as _cat` — `catalogue/catalogue.py` is a re-export shim over the split modules.

| Path | Responsibility |
|---|---|
| `main.py` | FastAPI app entrypoint; mounts routers; `/api/health`; optional static SPA fallback |
| `routes/` | HTTP routers: `auth`, `kyds`, `catalogue`, `pdf`, `dashboard` |
| `core/` | Cross-cutting: `auth.py` (JWT/bcrypt), `deps.py`, `gcs_utils.py`, `vector_store.py` |
| `catalogue/` | DB schema + catalogue domain: `db`, `users`, `kyds`, `datasets` (push), `query` (list), `classifications`, `dashboard`, `nco_aliases`, `nco_matching`, `catalogue_matching`, `extract_staging`; public shim `catalogue.py` |
| `extraction/` | `extractor.py`, `sql_extract.py`, `table_export.py`, `original_sheet_export.py` |
| `metadata/` | `metadata_excel.py`, `metadata_llm.py`, `metadata_fill.py`, `validation.py`, `table_id_title.py` |
| `pdf/` | PDF pipeline: `sda_india_pdf_extraction.py`, `pdf_store.py`, `pdf_jobs.py`, `pdf_grouping.py`, workers/confidence/dual-column helpers |
| `scripts/create_user.py` | Admin CLI to provision user accounts |
| `tests/` | `test_nco_matching.py`, `test_pdf_pipeline.py` |

### Key API routes

Declared on routers under `routes/` (not inlined in `main.py`):

| Method & path | Purpose |
|---|---|
| `GET /api/health` | Liveness + pgvector readiness |
| `POST /api/signup`, `POST /api/login` | Auth, issues JWT |
| `POST /api/kyds`, `GET /api/kyds/mine` | "Know Your Dataset" survey |
| `POST /api/catalogue/parse-concept-file` | Parses NMDS concept file |
| `POST /api/catalogue/batch-extract` | Extracts tables from workbook(s), validates Table ID/Title |
| `POST /api/catalogue/sql-extract` | Extracts tables from a Postgres connection |
| `POST /api/catalogue/batch-match` | Matches tables to metadata workbook(s) |
| `POST /api/catalogue/fill-group-metadata` | Group metadata autofill (shared Excel/PDF) |
| `GET`/`PATCH /api/catalogue/metadata-groups/{id}/classifications` | Classification codes (Classify step) |
| `GET /api/catalogue/classifications/recent` | Recent classifications fallback |
| `POST /api/catalogue/fill-definitions` | LLM autofill of classification definitions |
| `POST /api/catalogue/match-nco` | NCO occupation-code matching |
| `POST /api/catalogue/nco-aliases` | Persist learned NCO aliases |
| `POST /api/catalogue/batch-push` | Publishes reviewed groups into the catalogue DB |
| `GET /api/catalogue/datasets` | Lists published datasets (`catalogue.query.list_catalogue_datasets`) |
| `POST /api/pdf/upload`, job/result/table routes | PDF extract → review → persist → grouping |

All non-auth routes require a bearer JWT (`require_user`), so data is scoped to the authenticated user.

## 3. Database Schema (Postgres)

| Table | Notable columns |
|---|---|
| `users` | login credentials |
| `metadata_groups` | `classifications JSONB`, `nmds_concepts`, `sector`, `theme`, `catalogue_product` |
| `datasets` | `classifications JSONB`, `source_excel`, `original_excel` |
| `dataset_rows` | extracted table row data |
| `kyds_entries` | "Know Your Dataset" survey responses |
| `nco_2015_codes` / NCO alias tables | seeded concordance + learned value aliases |
| `pdf_jobs` / `pdf_tables` / `pdf_table_groups` | PDF job SoT after Preview Continue |
| `semantic_embeddings` | pgvector store — retrieval only, not source of truth |

## 4. Frontend (`frontend/src`)

Next.js App Router under `app/` (login, dashboard, console, catalogue, settings). Domain UI lives in folders; thin re-export shims remain at `components/*.jsx` for older imports.

| Path | Responsibility |
|---|---|
| `components/console/` | Excel/SQL Console pipeline: `Console.jsx`, `useConsolePipeline.js`, `ConsoleUploadChoice.jsx`, upload/review/grouping/classify/publish panels |
| `components/pdf/` | PDF Preview / edit / grouping / upload (`PdfReview.jsx`, `PdfGrouping.jsx`, …) |
| `components/catalogue/` | Catalogue browse UI |
| `components/` (shared) | `AppShell`, `Auth`, `Dashboard`, `Settings`, KYDS, `TableViewer`, `ui/` |
| `lib/` | `auth`, `llmKey`, `postPreview` (shared matchResult helpers), `pipeline.js` (barrel), console persist/status, settings |

**Console stages (shared Excel + post-PDF):** Files → Preview → Grouping → Metadata → Classification → Publish. Orchestration state lives in `useConsolePipeline`; PDF joins the same post-group path after grouping.

## 5. End-to-End Data Flow

```
Excel/SQL
1. Upload            console/BatchUpload|SqlUpload  ──batch-extract|sql-extract──►  extraction/
2. Preview           ReconcileIds + TableViewer       (ID/Title fixes)
3. Grouping          GroupingWorkspace                catalogue_matching / title groups
4. Metadata          BatchReview / NMDS panels        fill-group-metadata
5. Classify          Classify                         classifications + match-nco
6. Publish           Publish                          datasets.push_to_catalogue

PDF
1. Upload → processing → Preview (pdf/PdfReview) → Grouping (pdf/PdfGrouping)
2. Continues into shared stages 4–6 above

Browse               catalogue/Catalogue  ──GET /api/catalogue/datasets──►  catalogue.query
```

## 6. External Integrations

- **MEITY Empanelled LLM providers**: used across extraction, metadata fill, NCO matching, and definition autofill. There is no server-side API key — the user supplies their own key/provider in Settings, sent per-request via `x-llm-api-key` / `x-llm-provider` (`lib/llmKey`).

## 7. Auth

- JWT (HS256) + bcrypt (`backend/core/auth.py`).
- Accounts are admin-provisioned by default (`backend/scripts/create_user.py`); self-serve `/api/signup` is gated behind `ENABLE_SIGNUP`.
- Frontend stores the token and attaches `Authorization: Bearer <token>` via `withAuthHeaders`.

## 8. Catalogue & Publish

After extract → match → harmonise, Publish commits via `batch-push` → `catalogue.push_to_catalogue` (`catalogue/datasets.py`), writing `datasets` / `metadata_groups` (classifications, sector/theme/product, Excel export URLs). Catalogue list shaping lives in `catalogue/query.py` so REST (and a future MCP adapter) share one read path.

## 9. MCP Layer (planned adapter)

MCP is intended as a thin front door over the same catalogue query/write modules (not a second data model):

- **Resources / tools**: list/search datasets, classifications, NCO codes — backed by `catalogue.query` and related modules.
- **Auth**: same JWT-scoped model as REST.
- **Placement**: separate process talking to the same Postgres; REST and MCP should not duplicate SQL.

## 10. Suggested Diagram Views

1. **Deployment** — frontend / backend / Postgres / LLM (dev compose vs prod dual-process image).
2. **Backend packages** — `routes/` → `catalogue/` / `pdf/` / `extraction/` / `metadata/` / `core/`.
3. **Pipeline sequence** — Excel vs PDF spines joining at grouping → metadata → classify → publish.
4. **Catalogue access** — one Postgres catalogue; UI/REST now, MCP as a second door later.
