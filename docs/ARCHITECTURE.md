# DHARA — Technical Architecture

## 1. System Overview

DHARA is a data-cataloguing tool: a user uploads raw Excel dataset workbooks plus metadata workbooks, the system extracts tables, classifies/harmonises their columns against coded taxonomies, and publishes the result into a Postgres catalogue. That catalogue is then reachable two ways: directly through the app's own Catalogue browsing UI, and through an MCP server that exposes the same catalogue data as tools/resources for AI agents and other MCP-aware clients.

```
┌────────────────────┐        ┌─────────────────────────┐        ┌──────────────────────┐
│   Frontend (SPA)    │  HTTP  │   Backend (FastAPI)      │  SQL   │   Postgres (Neon in   │
│   React + Vite      │◄──────►│   Python 3.11, uvicorn   │◄──────►│   prod)                │
│   :5173 (dev)        │        │   :8000 (dev)            │        │   catalogue tables    │
└────────────────────┘        └─────────────────────────┘        └──────────────────────┘
                                        │                                     ▲
                                        ▼                                     │
                              ┌───────────────────┐              ┌────────────────────────┐
                              │  MEITY Empanelled  │              │      MCP Server         │
                              │      LLM APIs       │              │  exposes catalogue data │
                              │ (user-supplied key) │              │  as MCP tools/resources │
                              └───────────────────┘              └────────────────────────┘
                                                                               ▲
                                                                               │
                                                                    ┌─────────────────────┐
                                                                    │  MCP clients (agents, │
                                                                    │  IDEs, other tools)   │
                                                                    └─────────────────────┘
```

- **Dev**: `docker-compose.yml` runs 3 containers — `postgres` (`pgvector/pgvector:pg16`, :5432), `backend` (:8000, `uvicorn main:app --reload`), `frontend` (:3000, Next.js). `Makefile` wraps common commands (`make up/down/logs/psql/prod`).
- **Prod**: a single root `Dockerfile`/`docker-compose` profile builds one image that serves the built frontend as static files from the same FastAPI process (`backend/main.py`, `StaticFiles` mount + SPA fallback), exposed on :8080.
- **Database**: Postgres + **pgvector** (`CREATE EXTENSION vector`). Catalogue / auth tables remain the source of truth; `semantic_embeddings` holds ancillary vectors for similarity search (`backend/vector_store.py`). Connected via `DATABASE_URL` (Neon-hosted in production — enable the pgvector extension there too).

## 2. Backend Modules (`backend/`)

| File | Responsibility |
|---|---|
| `main.py` | FastAPI app entrypoint; declares every HTTP route; wires auth, DB, and the other modules together |
| `auth.py` | JWT (HS256, 12h expiry) + bcrypt password hashing; `require_user` dependency |
| `catalogue.py` | Postgres schema/DDL, CRUD for datasets/metadata_groups, classification merge logic, `push_to_catalogue` |
| `catalogue_matching.py` | Groups extracted tables to metadata-workbook rows (auto-grouping by title) |
| `extractor.py` | `TableExtractor` — pulls tabular data out of uploaded Excel sheets, MEITY empanelled LLM-assisted enrichment |
| `metadata_excel.py` | Parses metadata/concept workbooks (openpyxl), incl. `parse_classifications` |
| `metadata_llm.py` | MEITY empanelled LLM-driven metadata field generation and classification-definition autofill |
| `nco_matching.py` | NCO-2015 occupation code matching (semantic/token scoring, optional MEITY empanelled LLM) |
| `validation.py` | Table ID / Title mismatch validators (rule-based + MEITY empanelled LLM) |
| `table_export.py` | Exports one extracted table to a clean single-sheet .xlsx |
| `original_sheet_export.py` | Re-exports the original sheet with formatting preserved |
| `vector_store.py` | Stage 6 pgvector helpers: enable extension, `semantic_embeddings` DDL, upsert + cosine similarity search |
| `pdf_store.py` | Authoritative `pdf_jobs` / `pdf_tables` / `pdf_table_groups` after Preview Continue |
| `pdf_grouping.py` | Chunk + embed approved PDF tables; propose groups via similarity clustering |
| `create_user.py` | Admin CLI to provision user accounts |

### Key API routes (`backend/main.py`)

| Method & path | Purpose |
|---|---|
| `GET /api/health` | Liveness check |
| `POST /api/signup`, `POST /api/login` | Auth, issues JWT |
| `POST /api/table-metadata` | MEITY empanelled LLM category extraction (auth required) |
| `POST /api/kyds`, `GET /api/kyds/mine` | "Know Your Dataset" survey form |
| `POST /api/catalogue/parse-concept-file` | Parses NMDS concept file |
| `POST /api/catalogue/batch-extract` | Extracts tables from uploaded workbook(s), validates Table ID/Title |
| `POST /api/catalogue/batch-match` | Matches extracted tables to metadata workbook(s), Stage-4 MEITY empanelled LLM autofill |
| `GET`/`PATCH /api/catalogue/metadata-groups/{id}/classifications` | Reads/writes column classification codes (Classify step) |
| `GET /api/catalogue/classifications/recent` | Fallback: most-recent classifications when no metadata group id is known |
| `POST /api/catalogue/fill-definitions` | MEITY empanelled LLM autofill of classification definitions |
| `POST /api/catalogue/match-nco` | NCO occupation-code matching |
| `POST /api/catalogue/batch-push` | Publishes reviewed groups into the catalogue DB |
| `GET /api/catalogue/datasets` | Lists published datasets (Catalogue page) |

All non-auth routes require a bearer JWT (`require_user` → `auth.email_from_request`), so all data is scoped to the authenticated user.

## 3. Database Schema (Postgres)

| Table | Notable columns |
|---|---|
| `users` | login credentials |
| `metadata_groups` | `classifications JSONB`, `nmds_concepts`, `sector`, `theme`, `catalogue_product` |
| `datasets` | `classifications JSONB`, `source_excel`, `original_excel` |
| `dataset_rows` | extracted table row data |
| `kyds_entries` | "Know Your Dataset" survey responses |
| `nco_2015_codes` | seeded from `backend/data/nco_2015_concordance.csv`, used by NCO matching |
| `semantic_embeddings` | pgvector store: `chunk_text`, `embedding vector(1536)`, keyed by `object_type` / `object_id` / `chunk_kind` — retrieval only, not SoT |

## 4. Frontend (`frontend/src`)

- **App.jsx** — root component: login gate, then an `AppShell` switches between `dashboard | console | catalogue | settings` (persisted in `sessionStorage`). `Console` is kept mounted (hidden) once visited so an in-progress pipeline run isn't lost when navigating away.
- **Console.jsx** — orchestrates the actual multi-step pipeline and holds cross-step state.
- **Pipeline step components** (rendered in order inside Console):
  1. `BatchUpload.jsx` — file upload (dataset + metadata workbooks)
  2. `BatchReview.jsx` — review/grouping of extracted tables
  3. `ReconcileIds.jsx` — fixes Table ID / Title mismatches
  4. `Classify.jsx` — classification/harmonisation code+definition editor, NCO occupation matching
  5. `Publish.jsx` — pushes the reviewed group into the catalogue
- **Other components**: `Catalogue.jsx` (browse published datasets), `Settings.jsx` (MEITY empanelled LLM key/provider, dataset-ID config), `KydsModal.jsx`/`KydsSummaryCard.jsx`, `TableViewer.jsx`, `MetadataSheetGrid.jsx`, `NmdsConcept*.jsx`, `Dashboard.jsx`, `AppShell.jsx`, `Auth.jsx`.
- **Support modules**: `auth.js` (token storage, `withAuthHeaders`), `llmKey.js` (user-supplied MEITY empanelled LLM key/provider, `withLlmKeyHeaders`), `clickThrough.js` (demo-mode flag used in the pipeline UI), `settingsConfig.js` (localStorage-persisted settings).

## 5. End-to-End Data Flow

```
1. Upload            BatchUpload.jsx  ──POST /api/catalogue/batch-extract──►  extractor.TableExtractor
                                                                               (parses tables, validates Table ID/Title)
2. Review/Group       BatchReview.jsx ──POST /api/catalogue/batch-match────►  catalogue_matching.py
                                                                               (groups tables ↔ metadata workbook rows,
                                                                                or MEITY empanelled LLM-autofills metadata via metadata_llm.py)
3. Reconcile IDs      ReconcileIds.jsx  (fixes flagged Table ID/Title mismatches)

4. Classify/Harmonise Classify.jsx ──GET/PATCH .../classifications────────►  catalogue.py
                                     ──POST /api/catalogue/match-nco──────►  nco_matching.py ──► nco_2015_codes table
                                     ──POST /api/catalogue/fill-definitions─► metadata_llm.py (MEITY empanelled LLM)

5. Publish            Publish.jsx ──POST /api/catalogue/batch-push───────►  catalogue.push_to_catalogue
                                                                               (writes datasets / metadata_groups rows)

6. Browse & consume   Catalogue.jsx ──GET /api/catalogue/datasets────────►  reads published rows
                       MCP clients ──MCP tool/resource calls────────────►  MCP Server ──► same catalogue tables
```

## 6. External Integrations

- **MEITY Empanelled LLM providers**: used across `extractor.py`, `metadata_llm.py`, `nco_matching.py`, and the `/fill-definitions` route. There is no server-side API key — the user supplies their own key/provider in Settings, sent per-request via `x-llm-api-key` / `x-llm-provider` headers (`llmKey.js` → `withLlmKeyHeaders`).

## 7. Auth

- JWT (HS256, 12h expiry) + bcrypt password hashing (`backend/auth.py`).
- Accounts are admin-provisioned by default (`create_user.py`); self-serve `/api/signup` is gated behind an `ENABLE_SIGNUP` env var.
- Frontend stores the token in localStorage (`frontend/src/auth.js`) and attaches it as `Authorization: Bearer <token>` via `withAuthHeaders` on every API call.

## 8. Catalogue & Publish

Once a dataset's tables are extracted, matched, and harmonised, `Publish.jsx` commits the group into the permanent catalogue via `batch-push` → `catalogue.push_to_catalogue`, writing final rows into `datasets` and `metadata_groups` (with their `classifications` JSONB, sector/theme/product taxonomy, and source Excel references). Once published, a dataset is:
- Browsable inside the app itself via `Catalogue.jsx` → `GET /api/catalogue/datasets`, showing sector/theme/product groupings, classification status, and dataset metadata.
- Reachable programmatically through the MCP server described below, so the same published rows can be queried by AI agents and other MCP clients without going through the web UI.

## 9. MCP Layer

Alongside the FastAPI backend, an MCP server sits in front of the catalogue and exposes it to MCP-aware clients (AI agents, IDE assistants, other automation) using the Model Context Protocol. Conceptually it is a thin adapter over the same Postgres catalogue tables and backend modules already described above:

- **Resources**: published datasets, their classification code lists, sector/theme/product taxonomy, and the NCO-2015 code table — exposed as readable MCP resources so a client can browse the catalogue the same way `Catalogue.jsx` does.
- **Tools**: query/search operations over the catalogue (e.g. "find datasets by sector/theme", "get classification codes for a column", "look up an NCO occupation code"), letting an agent answer questions or build on top of DHARA's data without needing direct database or REST access.
- **Auth**: reuses the same JWT-scoped access model as the REST API, so an MCP client authenticates as a user and only sees/queries catalogue data that user can access.
- **Placement**: it runs as its own process alongside the FastAPI backend, talking to the same Postgres database (and, for definitions/enrichment, the same MEITY empanelled LLM-provider integration) rather than duplicating catalogue logic — the REST API and the MCP server are two front doors onto one catalogue.

## 10. Suggested Diagram Views

For turning this into a diagram, four separate views will likely read more clearly than one giant diagram:

1. **Deployment/container view** — the box diagram in §1 (frontend / backend / Postgres / MEITY empanelled LLM providers / MCP server / MCP clients, dev vs. prod topology).
2. **Backend module view** — `main.py` at the center, with the other backend modules and their DB tables as satellites (§2–3).
3. **Pipeline sequence view** — the numbered flow in §5, as a left-to-right swimlane: Upload → Review/Group → Reconcile → Classify/Harmonise → Publish → Browse/Consume, with each stage's frontend component, backend route(s), and module(s) called out.
4. **Catalogue access view** — one catalogue (Postgres tables) with two front doors: the Catalogue UI/REST API on one side and the MCP server/MCP clients on the other (§8–9).
