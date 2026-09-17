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
- Steward-configurable **Configuration modules** (dataset IDs, metadata
  standards, classification codes, LLM keys)

## High-level system

```text
┌─────────────────────────────────────────────────────────────────┐
│                         Browser (steward)                        │
│         Next.js 14 · Console · Catalogue · Settings              │
│                                                                  │
│   Configuration modules (Settings)                               │
│   · Dataset ID  · Metadata standard / required fields            │
│   · Classification codes  · MEITY-empanelled LLM key             │
└────────────────────────────┬────────────────────────────────────┘
                             │  /api/* (rewrites) + local prefs
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI backend                             │
│  auth · catalogue · pdf · kyds · dashboard · metadata helpers    │
└───────┬─────────────────────┬─────────────────────┬─────────────┘
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐   ┌─────────────────┐   ┌────────────────────┐
│   Postgres    │   │  MEITY-         │   │  Object storage    │
│  + pgvector   │   │  empanelled LLM │   │  GCS (optional)    │
│  SoT tables   │   │  (optional)     │   │  Excel artifacts   │
│  + standards  │   │                 │   │                    │
└───────────────┘   └─────────────────┘   └────────────────────┘
```

| Layer | Role |
|-------|------|
| **Frontend** | Console stages, Preview/Grouping editors, Catalogue browse, **Settings / Configuration modules** |
| **Backend** | JWT auth, extraction, matching, PDF jobs, catalogue push, NCO matching |
| **Postgres** | Authoritative metadata, datasets, PDF tables/groups, users, classification standards |
| **pgvector** | Semantic similarity only — never the source of truth |
| **LLM** | Reconstruction, classification proposals, metadata fill (skippable) |
| **GCS** | Optional storage for published Excel downloads |

## Configuration modules

Cross-cutting steward configuration lives under **Settings** (not env-only).
These modules shape how IDs are minted, which metadata schema is used, which
code lists are available for harmonisation, and whether LLM-assisted steps run.

| Module | Where (UI) | What it configures | Consumed by |
|--------|------------|--------------------|-------------|
| **Dataset ID configuration** | Settings → Dataset ID | Prefix, separator, statistics domain for generated dataset IDs | Preview (Dataset ID), grouping / publish identity |
| **Metadata configuration** | Settings → Metadata | Metadata standard (**NMDS** or **SDG**); required catalogue fields | Metadata step, Batch Review, catalogue push validation |
| **Classification code configuration** | Settings → Classification | Upload / manage concordance CSVs (e.g. NCO-shaped lists) stored in Postgres | Classification & harmonisation (stage 7) |
| **MEITY-empanelled LLM** | Settings (top card) | Provider + API key for reconstruction, metadata fill, matching | Stages 2–3, 6–7, 10 when a key is present |

```text
                    Settings / Configuration modules
          ┌──────────────┬──────────────┬──────────────┬──────────────┐
          │ Dataset ID   │ Metadata     │ Classification│ MEITY LLM   │
          │ prefix / sep │ NMDS · SDG   │ code CSVs     │ key         │
          └──────┬───────┴──────┬───────┴──────┬───────┴──────┬───────┘
                 │              │              │              │
                 ▼              ▼              ▼              ▼
            Preview IDs   Metadata fill   Harmonise     Optional AI
                          + required      code lists    paths
                          fields
```

Client preferences for dataset ID and metadata standard / required fields are
stored in the browser (`frontend/src/lib/settingsConfig.ts`). Classification
standards and codes are persisted in Postgres via catalogue APIs. LLM keys stay
in the steward session (and optional server `.env` defaults).

See also [Pipeline overview — Configuration modules](./pipeline/overview.md#configuration-modules)
and [deployment configuration](./deployment/configuration.md) for env vars.

## Repository layout

```text
dhara-poc/
├── frontend/          Next.js UI (Console, Catalogue, Settings)
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
| **Dataset Publication** | Publish | Confirm push; surface `/api/v1` + MCP access |

**Settings** sits beside the Console (AppShell) and is available at any time;
configuration modules apply to subsequent Console steps without a separate
pipeline stage number.

Intake differs; after Preview they converge on the same catalogue path.

```text
  Excel workbooks ──┐
  SQL connection  ──┼──► Preview → Grouping → Metadata → Classify → Publish
  PDF report      ──┘                                              │
         ▲                                                         ▼
         │                                               Postgres catalogue
         └── Settings: Dataset ID · Metadata · Standards · LLM key
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

LLM keys can be pasted in Settings (**MEITY-empanelled LLM**). Server-side
keys in `.env` are optional for local work. With no key, Excel uses structural
heuristics; PDF uses PyMuPDF + heuristic accept for ambiguous pages (flagged
for review).

### 5. Configuration is steward-owned

Dataset ID rules, metadata standard / required fields, and classification code
lists are **Configuration modules** — editable in Settings by data stewards —
not hard-coded product constants. Deploy-time env vars (DB, JWT, GCS) remain
separate; see [deployment/configuration.md](./deployment/configuration.md).

### 6. Separation of concerns

| Component | Responsibility |
|-----------|----------------|
| PyMuPDF / openpyxl / SQL | Physical extraction |
| Deterministic Python | Confidence, validation, batch matching |
| LLM | Reconstruct, classify, reason over candidates |
| pgvector | Find similar semantic chunks |
| Human | Approve meaning and groupings |
| Configuration modules | Dataset IDs, metadata schema, code lists, LLM key |
| Catalogue / API | Discoverability and access |
| MCP | Agent-oriented access via `python -m mcp_server` (stdio) |

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

- [Pipeline overview](./pipeline/overview.md) (includes Configuration modules)
- [On-prem deployment](./deployment/on-prem.md)
- [Cloud deployment](./deployment/cloud.md)
- [Env / secrets configuration](./deployment/configuration.md)
