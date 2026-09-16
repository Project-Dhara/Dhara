# Architecture

## What DHARA is

DHARA turns government statistical products (Excel workbooks, PDF reports, and
SQL tables) into **reviewed, catalogued datasets**. Downstream consumers such as
des-website read the same Postgres catalogue that DHARA writes.

It is not a generic ETL product. It is shaped around:

- Human approval of semantic decisions
- NMDS / SDG-style metadata
- Classification standards (e.g. NCO-shaped occupation lists)
- One Console flow for Excel, SQL, and PDF intake

## High-level system

```text
┌─────────────────────────────────────────────────────────────────┐
│                         Browser (steward)                        │
│              Next.js 14 App Router + Tailwind UI                 │
└────────────────────────────┬────────────────────────────────────┘
                             │  /api/* (rewrites)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI backend                             │
│  auth · catalogue · pdf · kyds · dashboard · metadata helpers    │
└───────┬─────────────────────┬─────────────────────┬─────────────┘
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐   ┌─────────────────┐   ┌────────────────────┐
│   Postgres    │   │  LLM providers  │   │  Object storage    │
│  + pgvector   │   │  (optional)     │   │  GCS (optional)    │
│  SoT tables   │   │  Claude / OpenAI│   │  Excel artifacts   │
└───────────────┘   └─────────────────┘   └────────────────────┘
```

| Layer | Role |
|-------|------|
| **Frontend** | Console stages, Preview/Grouping editors, Catalogue browse, Settings |
| **Backend** | JWT auth, extraction, matching, PDF jobs, catalogue push, NCO matching |
| **Postgres** | Authoritative metadata, datasets, PDF tables/groups, users, standards |
| **pgvector** | Semantic similarity only — never the source of truth |
| **LLM** | Reconstruction, classification proposals, metadata fill (skippable) |
| **GCS** | Optional storage for published Excel downloads |

## Repository layout

```text
dhara-poc/
├── frontend/          Next.js UI
├── backend/
│   ├── routes/        HTTP API
│   ├── catalogue/     catalogue DB, matching, classifications, NCO
│   ├── pdf/           PDF extraction, jobs, grouping
│   ├── extraction/    Excel + SQL extractors
│   ├── metadata/      metadata fill / validation / LLM helpers
│   └── core/          auth, deps, vector_store, GCS
├── docker-compose.yml Dev stack + prod profile
├── Dockerfile         Combined Next + FastAPI image (:8080)
└── docs/              This documentation
```

## Console stages (product UX)

Excel/SQL and PDF share the same stage rail:

| Stage | Steps | Purpose |
|-------|-------|---------|
| **Dataset Inventory** | Files → Preview | Ingest and human-edit extracted tables |
| **Metadata Workspace** | Grouping → Metadata | Relate tables; fill catalogue fields |
| **Transformation & Harmonisation** | Classification | Code lists, NCO-style matching |
| **Dataset Publication** | Publish | Confirm push; surface API/MCP access (MCP planned) |

Intake differs; after Preview they converge on the same catalogue path.

```text
  Excel workbooks ──┐
  SQL connection  ──┼──► Preview → Grouping → Metadata → Classify → Publish
  PDF report      ──┘                                              │
                                                                   ▼
                                                         Postgres catalogue
```

## Design principles

### 1. AI proposes; humans decide

Every uncertain semantic claim should be reviewable. Approved meaning becomes
authoritative knowledge; raw AI output does not.

### 2. Postgres is the source of truth

Normal tables hold datasets, metadata groups, PDF tables/groups, users, and
classification standards. Embeddings in `semantic_embeddings` are for retrieval
and grouping candidates only.

### 3. Original source values stay immutable

Harmonisation stores **mappings** with provenance. Transformation (when fully
built) produces derived views; it does not silently rewrite source cells during
classification review.

### 4. Bring your own keys

LLM keys can be pasted in Settings (MEITY-empanelled providers). Server-side
keys in `.env` are optional for local work. `SKIP_LLM=true` runs heuristic
fallbacks without Claude.

### 5. Separation of concerns

| Component | Responsibility |
|-----------|----------------|
| PyMuPDF / openpyxl / SQL | Physical extraction |
| Deterministic Python | Confidence, validation, batch matching |
| LLM | Reconstruct, classify, reason over candidates |
| pgvector | Find similar semantic chunks |
| Human | Approve meaning and groupings |
| Catalogue / API | Discoverability and access |
| MCP (planned) | Agent-oriented access to approved data |

## Data model (essentials)

| Area | Tables |
|------|--------|
| Auth | `users` |
| Catalogue | `metadata_groups`, `datasets`, `dataset_rows` |
| KYDS | `kyds_entries` |
| PDF | `pdf_jobs`, `pdf_tables`, `pdf_table_groups`, `pdf_table_group_members` |
| Vectors | `semantic_embeddings` |
| Standards | `nco_2015_codes`, `nco_value_aliases`, `classification_standards`, … |
| Staging | `extract_staging` (Excel/SQL between extract and push) |

Schema is created lazily via `init_schema` on first catalogue/KYDS use.
pgvector is enabled from `backend/db/init-pgvector.sql` on first Postgres boot.

## Auth and API surface

- JWT Bearer auth on almost all routes (`/api/health`, login, signup excepted)
- Swagger at `/docs`
- Signup controlled by `ENABLE_SIGNUP`; otherwise provision with
  `backend/scripts/create_user.py`

## Related docs

- [Pipeline overview](./pipeline/overview.md)
- [On-prem deployment](./deployment/on-prem.md)
- [Cloud deployment](./deployment/cloud.md)
