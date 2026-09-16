<p align="center">
  <img src="./Dhara_logo.png" alt="Data Dhara" width="420" />
</p>

<p align="center">
  <a href="http://localhost:8000/docs"><img src="https://img.shields.io/badge/API-Swagger-0A7EA4?style=flat-square" alt="API docs" /></a>
  <img src="https://img.shields.io/badge/Frontend-Next.js_14-000000?style=flat-square" alt="Next.js" />
  <img src="https://img.shields.io/badge/Backend-FastAPI-009688?style=flat-square" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Database-Postgres_%2B_pgvector-336791?style=flat-square" alt="Postgres" />
  <img src="https://img.shields.io/badge/Deploy-Docker-2496ED?style=flat-square" alt="Docker" />
  <img src="https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square" alt="Apache 2.0" />
</p>

# DHARA: Data cataloguing for government statistical releases

Internal toolkit for building and maintaining the DES Delhi data catalog — the
Postgres database that
[des-website](https://des-website-235956738573.asia-south1.run.app) reads from.
Upload Excel workbooks or PDF statistical reports, extract and review tables,
harmonise classifications, and publish clean datasets into the catalogue.

Full design, stage-by-stage pipeline, and deployment guides live under
**[docs/](./docs/README.md)** (architecture, on-prem, cloud, configuration).

---

## What can be done with Dhara

- **Ingest Excel workbooks** — batch-extract tables, match them to metadata tag
  files, reconcile IDs/titles, classify columns, and publish.
- **Connect a SQL database** — paste a Postgres URL; tables are auto-extracted
  (DHARA catalogue DBs expand `datasets` from `dataset_rows`) and continue on
  the same review path as Excel.
- **Process PDF reports** — extract tables from statistical PDFs, preview and
  edit grids, merge cross-page tables, group related tables, then join the
  shared catalogue pipeline.
- **Harmonise classifications** — steward code lists, fill definitions, and
  match occupation values to NCO 2015 with optional LLM assistance.
- **Publish to a shared catalogue** — push metadata groups and table records
  (plus clean / original Excel exports) into Postgres for browsing and for
  downstream consumers like des-website.
- **Browse published datasets** — Catalogue UI lists what you have published,
  with access metadata and API-oriented previews.
- **Secure the API** — JWT login; Swagger at `/docs` with Bearer auth for
  exploring endpoints.

---

## Why Dhara

- **One pipeline for Excel, SQL, and PDF** — different intake paths, one
  Console flow into the same catalogue.
- **Human-in-the-loop by design** — Preview, grouping, metadata, and classify
  steps keep stewards in control before anything is published.
- **Catalogue as source of truth** — Postgres holds authoritative rows;
  pgvector is for semantic retrieval only, not a second database.
- **Bring your own LLM key** — MEITY-empanelled providers via Settings; no
  shared server-side model key required for local work.
- **Built for DES Delhi** — shaped around government statistical products,
  NMDS/SDG metadata, and NCO/NIC-style harmonisation — not a generic ETL toy.

---

## Project structure

```
dhara-poc/
├── docs/                        Architecture, pipeline stages, deployment
├── Makefile                     make up / down / logs / psql / prod …
├── docker-compose.yml           postgres + backend + frontend (dev); app (prod)
├── Dockerfile                   Combined Next.js + FastAPI image (:8080)
├── Dhara_logo.png               Brand mark (README / docs)
├── backend/                     FastAPI + openpyxl + LLM + Postgres + pgvector
│   ├── main.py                  App setup + router registration (entrypoint)
│   ├── routes/                  FastAPI routers: auth, kyds, catalogue, pdf, dashboard
│   ├── core/                    auth.py, deps.py, gcs_utils.py, vector_store.py
│   ├── catalogue/               query.py, datasets.py, catalogue.py (shim), matching, NCO, staging, …
│   ├── pdf/                     sda_india_pdf_extraction.py, pdf_store.py, pdf_jobs.py, grouping, …
│   ├── metadata/                metadata_excel.py, metadata_llm.py, metadata_fill.py, validation, …
│   ├── extraction/              extractor.py, sql_extract.py, table_export.py, …
│   ├── scripts/create_user.py   Admin user provisioning CLI
│   ├── tests/                   test_nco_matching.py, test_pdf_pipeline.py
│   ├── db/init-pgvector.sql     CREATE EXTENSION vector (first boot)
│   └── requirements.txt
└── frontend/                    Next.js 14 (App Router) + Tailwind + lucide-react
    └── src/
        ├── app/                 Routes: login, dashboard, console, catalogue, settings
        ├── components/
        │   ├── console/         Excel/SQL Console + useConsolePipeline + step panels
        │   ├── pdf/             PdfReview, PdfGrouping, upload/edit helpers
        │   ├── catalogue/       Catalogue browse UI
        │   └── …                Shared AppShell, Auth, Dashboard, Settings, ui/
        └── lib/                 auth, llmKey, postPreview, pipeline.js, settings
```

## Flows

Both Excel and PDF start from **Console** after login. Published rows land in
the same Postgres catalog and are browsable under **Catalogue**.

**Excel (batch)** — upload dataset workbooks (+ metadata tag files). Tables are
extracted, matched to metadata (exact ID → typo-tolerant → keyword
disambiguation), reconciled, classified/harmonised, then published.

**SQL (Postgres)** — paste a connection URL; **tables are auto-extracted**
(DHARA catalogue DBs expand each `datasets` row from `dataset_rows.row_data`)
(custom `SELECT` optional). Continues on the **same Excel review path**.
See Console → “Connect a SQL database”.

**PDF** — upload a report → extract tables → **Preview** (edit cells, merge
cross-page tables, show-all-rows) → **Grouping** (similarity / review) → continue
into the shared catalog pipeline as implemented.

## Quick start (Docker)

Requires Docker Compose. From the repo root:

```bash
cp backend/.env.example backend/.env   # then edit secrets / keys
make up                                 # postgres + backend :8000 + frontend :3000
make urls                               # print local URLs
```

| Service   | URL |
|-----------|-----|
| UI        | http://localhost:3000 |
| API       | http://localhost:8000 |
| API docs  | http://localhost:8000/docs |
| Health    | http://localhost:8000/api/health |

Useful Make targets:

```bash
make logs        # follow all container logs
make ps          # container status
make psql        # psql into Docker Postgres
make down        # stop (keeps DB volume)
make postgres    # Postgres only (run backend/frontend on the host)
make prod        # combined app image on :8080
make clean       # stop and delete volumes (incl. DB)
```

If the frontend container fails with missing packages after a `package.json`
change (named volume `frontend_node_modules`), reinstall inside the container
or reset that volume:

```bash
docker compose exec frontend npm ci
# or: docker compose down && docker volume rm dhara-poc_frontend_node_modules && make up
```

## Setup (host backend/frontend + Docker Postgres)

### 1. Postgres

```bash
make postgres
# or: docker compose up -d postgres
```

Postgres uses **`pgvector/pgvector:pg16`**. Catalogue tables stay in normal SQL;
embeddings live in `semantic_embeddings`.

If you previously used `postgres:16-alpine` on the same volume, recreate once:

```bash
docker compose down
docker compose pull postgres
docker compose up -d postgres
# full reset: docker compose down -v && docker compose up -d postgres
```

Connection string (also in `backend/.env.example`):

```
postgresql://dhara:dhara_local_password@localhost:5432/dhara
```

### 2. Environment

Copy `backend/.env.example` to `backend/.env` and set at least:

```
ANTHROPIC_API_KEY=sk-ant-...          # optional if you paste a key in Settings
DATABASE_URL=postgresql://dhara:dhara_local_password@localhost:5432/dhara
JWT_SECRET=<random hex>               # required for login tokens
ENABLE_GCS=false
ENABLE_SIGNUP=true                    # self-serve signup; set false in locked-down deploys
SKIP_LLM=false                        # true = heuristic/no-Claude mode
# EMBEDDING_DIM=1536                  # optional; text-embedding-3-small width
```

Generate a JWT secret:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Local testing needs `DATABASE_URL` pointing at Docker Postgres. Catalogue push
writes dataset/metadata rows; Excel file URLs stay empty until `ENABLE_GCS=true`
(with `GCS_BUCKET_NAME` and GCP credentials).

Provision a user (when signup is disabled):

```bash
cd backend && python scripts/create_user.py
```

### 3. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 4. Frontend

```bash
cd frontend
npm install   # or npm ci
npm run dev   # http://localhost:3000 — /api proxied to :8000
```

Schema is created on first catalogue/KYDS API use (`init_schema`). Verify:

```bash
curl http://localhost:8000/api/health
docker exec -it dhara-postgres psql -U dhara -d dhara -c '\dt'
```

Occupation matching needs a concordance CSV uploaded in **Settings →
Classification code configuration** (columns match
`backend/data/nco_2015_concordance.csv.example`). For offline golden tests
only, you may also place a CSV at `backend/data/nco_2015_concordance.csv`.

## Auth

API routes (except health / login / signup) expect `Authorization: Bearer <JWT>`.
Sign up via the UI when `ENABLE_SIGNUP=true`, or create accounts with
`backend/scripts/create_user.py`.

**Call the API**

Use Swagger at http://localhost:8000/docs: get a token via curl (below) or the
app login, click **Authorize**, paste the token only (no `Bearer` prefix).

```bash
TOKEN=$(curl -s http://localhost:8000/api/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@org.example","password":"…"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/me
```

## Deployment

Cloud Run service `extractionprocess` (project `data-unlock`, region
`asia-south1`), built from the root `Dockerfile` (Next.js build + FastAPI;
`start.sh` runs both; Next proxies `/api` to the backend). Local prod-shaped
stack:

```bash
make prod    # http://localhost:8080
```

Manual deploy example:

```bash
gcloud run deploy extractionprocess --source=. --region=asia-south1 --project=data-unlock
```

**Warning**: this can write to the live catalog database that `des-website`
serves. Auth gates the API; still treat deploy access and production secrets
carefully.

## What gets pushed to the catalog

Per dataset table: title/description, category/geography/frequency/etc.
(inherited from its metadata group), classifications and units (via an
enrichment pass), and two downloadable Excel exports — `source_excel` (clean
re-flattened table) and `original_excel` (source sheet with formatting
preserved). `des-website` prefers `original_excel`, falling back to
`source_excel` for older rows.

## Documentation

| Topic | Link |
|-------|------|
| Docs home | [docs/README.md](./docs/README.md) |
| Architecture | [docs/architecture.md](./docs/architecture.md) |
| Pipeline stages | [docs/pipeline/](./docs/pipeline/overview.md) |
| On-prem deploy | [docs/deployment/on-prem.md](./docs/deployment/on-prem.md) |
| Cloud deploy | [docs/deployment/cloud.md](./docs/deployment/cloud.md) |
| Configuration | [docs/deployment/configuration.md](./docs/deployment/configuration.md) |

## License

Copyright 2026 DHARA Authors

Licensed under the Apache License, Version 2.0. See [LICENSE](./LICENSE) and
[NOTICE](./NOTICE) for details.
