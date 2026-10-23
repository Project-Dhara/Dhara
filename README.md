![Data Dhara](./Dhara_logo.png)

![API docs](https://img.shields.io/badge/API-Swagger-0A7EA4?style=flat-square)![Next.js](https://img.shields.io/badge/Frontend-Next.js_14-000000?style=flat-square)![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?style=flat-square)![Postgres](https://img.shields.io/badge/Database-Postgres_%2B_pgvector-336791?style=flat-square)![Docker](https://img.shields.io/badge/Deploy-Docker-2496ED?style=flat-square)![Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)

# Data DHARA (Data Harnessed for AI Ready Advancement)

The Data DHARA Toolkit takes a dataset through all seven stages in one workflow to make data discoverable and AI ready. It would identify datasets by building an inventory with unique IDs, describe them with NMDS 2.0, MDDS and other metadata standards. It makes them interoperable by harmonising codes and values into a stable structure, and catalogue them in a searchable browser. 

The catalogued data is made accessible through API and MCP endpoints.

## About

[https://datadhara.ekstep.org/](https://datadhara.ekstep.org/)

## Scope

### In Scope

- One workflow that takes a dataset from inventory through description, harmonisation, cataloguing, and access.
- A dataset inventory with unique IDs.
- Description with NMDS 2.0, MDDS, and other metadata standards configured for the release.
- Harmonising codes and values into a stable structure.
- A searchable catalogue browser.
- Access to catalogued data through API and MCP endpoints.
- Intake from Excel workbooks, PDF reports, and SQL (Postgres).

### Out of Scope

- Replacing the systems that originally produce the datasets.
- Acting as the public website that consumes the catalogue.
- Hosting or training the language model. A provider key is supplied in Settings when an AI step is used.
- Intake of file types other than Excel, PDF, and SQL.

## Project structure

```
dhara-poc/
├── docs/                        Architecture, pipeline stages, deployment
├── Makefile                     make up / down / logs / psql / prod …
├── docker-compose.yml           postgres + backend + frontend (dev); app (prod)
├── Dockerfile                   Combined Next.js + FastAPI image (host :80 → :8080)
├── Dhara_logo.png               Brand mark (README / docs)
├── backend/                     FastAPI + openpyxl + LLM + Postgres + pgvector
│   ├── main.py                  Process entry (`uvicorn main:app` → `app.main`)
│   ├── app/                     API, services, psycopg2 store, MCP
│   │   ├── api/routes/          HTTP: auth, kyds, catalogue, pdf, upload, dashboard, access
│   │   ├── db/                  psycopg.py, pdf_store.py, kyds_psycopg.py, SQLAlchemy repos
│   │   ├── services/            ingestion, extraction, grouping, catalogue, metadata
│   │   └── mcp/                 MCP tools (stdio `python -m app.mcp`, HTTP `/mcp`)
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

## Quick start (Docker)

Requires Docker Compose. From the repo root:

```bash
cp backend/.env.example backend/.env   # then edit secrets / keys
make up                                 # postgres + backend :8000 + frontend :80
make urls                               # print local URLs
```


| Service   | URL                                                                |
| --------- | ------------------------------------------------------------------ |
| UI        | [http://localhost:80](http://localhost:80)                         |
| API       | [http://localhost:8000](http://localhost:8000)                     |
| API docs  | [http://localhost:8000/docs](http://localhost:8000/docs)           |
| Liveness  | [http://localhost:8000/api/live](http://localhost:8000/api/live)   |
| Readiness | [http://localhost:8000/api/ready](http://localhost:8000/api/ready) |


Useful Make targets:

```bash
make logs        # follow all container logs
make ps          # container status
make psql        # psql into Docker Postgres
make down        # stop (keeps DB volume)
make postgres    # Postgres only (run backend/frontend on the host)
make prod        # combined app image on :80
make clean       # stop and delete volumes (incl. DB)
```

If the frontend container fails with missing packages after a `package.json`
change (named volume `frontend_node_modules`), reinstall inside the container
or reset that volume:

```bash
docker compose exec frontend npm ci
# or: docker compose down && docker volume rm dhara_frontend_node_modules && make up
```

## Setup (host backend/frontend + Docker Postgres)

### 1. Postgres

```bash
make postgres
# or: docker compose up -d postgres
```

Postgres uses `**pgvector/pgvector:pg16**`. Catalogue tables stay in normal SQL;
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
DATABASE_URL=postgresql://dhara:dhara_local_password@localhost:5432/dhara
JWT_SECRET=<random hex>               # required for login tokens
ENABLE_GCS=false
ENABLE_SIGNUP=true                    # self-serve signup; set false in locked-down deploys
# EMBEDDING_DIM=1536                  # optional embedding width
# LLM keys: paste in Settings (not server .env). Optional — AI steps degrade without one.
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
curl http://localhost:8000/api/live    # process up
curl http://localhost:8000/api/ready   # Postgres reachable (503 if not)
docker exec -it dhara-postgres psql -U dhara -d dhara -c '\dt'
```

**NCO 2015** is pre-configured from backend data and appears selected in
**Settings → Classification code configuration**. Stewards can also upload
additional standards there.

## Auth

API routes (except health / login / signup) expect `Authorization: Bearer <JWT>`.
Sign up via the UI when `ENABLE_SIGNUP=true`, or create accounts with
`backend/scripts/create_user.py`.

**Call the API**

Use Swagger at [http://localhost:8000/docs](http://localhost:8000/docs): get a token via curl (below) or the
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
make prod    # http://localhost:80

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


| Topic                 | Link                                                                                                                         |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Docs home             | [docs/README.md](./docs/README.md)                                                                                           |
| Architecture          | [docs/architecture.md](./docs/architecture.md) (includes Configuration modules)                                              |
| Pipeline stages       | [docs/pipeline/overview.md](./docs/pipeline/overview.md)                                                                     |
| Configuration modules | [Architecture](./docs/architecture.md#configuration-modules) · [Pipeline](./docs/pipeline/overview.md#configuration-modules) |
| On-prem deploy        | [docs/deployment/on-prem.md](./docs/deployment/on-prem.md)                                                                   |
| Cloud deploy          | [docs/deployment/cloud.md](./docs/deployment/cloud.md)                                                                       |
| Configuration (env)   | [docs/deployment/configuration.md](./docs/deployment/configuration.md)                                                       |


## License

Copyright 2026 DHARA Authors

Licensed under the Apache License, Version 2.0. See [LICENSE](./LICENSE) and
[NOTICE](./NOTICE) for details.