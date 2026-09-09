# DHARA Toolkit

Internal tool for building and maintaining the DES Delhi data catalog (the
Postgres database that [des-website](https://des-website-235956738573.asia-south1.run.app)
reads from). Upload government **Excel** workbooks or **PDF** statistical
reports, extract tables (with optional LLM assistance), review/group them,
harmonise classifications, and push dataset records plus clean Excel exports
into the catalog.

For deeper module/API detail see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Project structure

```
dhara-poc/
├── Makefile                     make up / down / logs / psql / prod …
├── docker-compose.yml           postgres + backend + frontend (dev); app (prod)
├── Dockerfile                   Combined Next.js + FastAPI image (:8080)
├── backend/                     FastAPI + openpyxl + LLM + Postgres + pgvector
│   ├── main.py                  API routes
│   ├── auth.py                  JWT login / signup
│   ├── extractor.py             Claude/LLM table extraction from Excel
│   ├── sql_extract.py           Read-only Postgres SELECT → Excel-shaped table
│   ├── sda_india_pdf_extraction.py  PDF table extraction pipeline
│   ├── pdf_store.py / pdf_grouping.py / pdf_dual_column.py
│   ├── catalogue.py / catalogue_matching.py
│   ├── vector_store.py          Stage 6 semantic_embeddings (pgvector)
│   ├── create_user.py           Admin user provisioning CLI
│   ├── db/init-pgvector.sql     CREATE EXTENSION vector (first boot)
│   └── requirements.txt
└── frontend/                    Next.js 14 (App Router) + Tailwind + lucide-react
    └── src/
        ├── app/                 Routes: login, dashboard, console, catalogue, settings
        ├── components/          Console pipeline, PdfReview/Grouping, Catalogue, Auth …
        └── lib/                 auth, LLM key headers, settings
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
cd backend && python create_user.py
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

## Auth

API routes (except health / login / signup) expect `Authorization: Bearer <JWT>`.
Sign up via the UI when `ENABLE_SIGNUP=true`, or create accounts with
`backend/create_user.py`.

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
