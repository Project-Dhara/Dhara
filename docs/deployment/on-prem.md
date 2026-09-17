# On-prem deployment

Run DHARA on a laptop, VM, or private datacenter without depending on a public
PaaS. All required services can run in Docker.

## Prerequisites

- Docker Engine + Docker Compose v2
- (Optional) Node 20+ and Python 3.11+ if running UI/API on the host
- Outbound HTTPS only if you call a **MEITY-empanelled LLM** (or compatible
  endpoint) and embeddings; otherwise omit the key / use Settings with no key

## LLM and PDF extraction (important)

DHARA does **not** need a public SaaS LLM vendor name — configure a
**MEITY-empanelled LLM** API key in Settings (or `OPENAI_API_KEY` /
`ANTHROPIC_API_KEY` in `.env` for an OpenAI-/Anthropic-compatible endpoint).

| Mode | What happens |
|------|----------------|
| **With MEITY-empanelled LLM key** | Full PDF path: PyMuPDF candidates → confidence split → LLM reconstruct/classify for ambiguous pages; richer Excel assist, NCO suggest, singleton grouping merge |
| **Without LLM key** | PyMuPDF still extracts ruled tables. **High-confidence** pages are auto-accepted. **Ambiguous** pages fall back to the same heuristic grid (`table_dict_from_df`) and are flagged for human review — no remote LLM call. Excel extract uses structural heuristics. Title-base grouping still works; embedding / LLM singleton merge is skipped |

Air-gapped PDF ingest is therefore usable, but expect more steward review on
complex multi-header pages than with a MEITY-empanelled model available.

## 1. Quick start (recommended)

From the repo root:

```bash
cp backend/.env.example backend/.env
# Edit JWT_SECRET; optional MEITY-empanelled LLM key (OPENAI_API_KEY / ANTHROPIC_API_KEY)
make up
make urls
```

| Service | URL |
|---------|-----|
| UI | http://localhost:3000 |
| API | http://localhost:8000 |
| Swagger | http://localhost:8000/docs |
| Health | http://localhost:8000/api/health |

Useful targets:

```bash
make logs      # follow logs
make psql      # shell into Postgres
make down      # stop (keeps volume)
make clean     # stop and delete volumes
```

Compose services: `postgres` (`pgvector/pgvector:pg16`), `backend`, `frontend`.
Backend `DATABASE_URL` is forced to the Compose service hostname `postgres`.

## 2. Production-shaped single container

Builds the root `Dockerfile` (Next build + FastAPI) and serves UI+API on one
port:

```bash
make prod
# → http://localhost:8080
```

`start.sh` runs uvicorn on `BACKEND_PORT` (default 8000, internal) and
`next start` on `PORT` (default 8080, public). Next rewrites `/api/*` to the
backend.

Stop:

```bash
make prod-down
```

### Reverse proxy (on-prem)

Put nginx / Caddy / Traefik in front of `:8080` (or `:3000`+`:8000` in three-
container mode):

- Terminate TLS
- Forward to the app
- Optionally restrict by IP / mutual TLS / SSO

Example conceptual Caddy site:

```text
dhara.internal {
  reverse_proxy localhost:8080
}
```

## 3. Host backend/frontend + Docker Postgres only

```bash
make postgres
cp backend/.env.example backend/.env
# DATABASE_URL=postgresql://dhara:dhara_local_password@localhost:5432/dhara
```

Backend:

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm ci
npm run dev   # proxies /api to :8000
```

Provision a user if signup is disabled:

```bash
cd backend && python scripts/create_user.py
```

## 4. Datacenter / VM checklist

| Item | Guidance |
|------|----------|
| OS | Linux x86_64 with Docker |
| Disk | Persist the `dhara_pg_data` volume; back it up |
| Memory | PDF + MEITY-empanelled LLM extraction is the heavy path — size for concurrent jobs |
| CPU | Process-pool PDF workers benefit from multiple cores |
| Network | Block public ingress; allow steward VPN / jump host; allow egress only to your MEITY-empanelled endpoint if used |
| Secrets | Mount `backend/.env` or inject env via orchestrator — never bake keys into images |
| Updates | Rebuild images from the repo; keep Postgres volume across app upgrades |
| pgvector | Use the provided image or install the extension on your Postgres |

### Existing corporate Postgres

Point `DATABASE_URL` at your server. Ensure:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Schema tables are created by the app on first use (`init_schema`). Prefer a
dedicated database/role for DHARA.

## 5. Air-gapped / limited egress

1. Build images on a connected machine; transfer tarballs (`docker save` /
   `docker load`).
2. Omit MEITY-empanelled LLM keys (or leave Settings empty). PDF uses PyMuPDF +
   heuristic accept for all candidate pages; stewards should review flagged
   tables. Excel uses structural extract without remote LLM.
3. Pre-load classification standards via Settings upload (CSV) on a machine that
   can receive the file by USB/secure copy.
4. Disable GCS (`ENABLE_GCS=false`); catalogue rows still publish without file
   URLs.

## 6. What on-prem does *not* require

- Cloud Run / Render
- GCS (optional)
- Public DNS (internal hostname is fine)
- A MEITY-empanelled LLM (optional — improves PDF reconstruction and assists)

See [configuration](./configuration.md) for the full env list.
