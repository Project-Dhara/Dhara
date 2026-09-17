# Cloud deployment

DHARA can run as a single Docker web service against managed Postgres, with
optional object storage for Excel downloads.

## Topology

```text
                    Internet / IAP
                          │
                          ▼
              ┌───────────────────────┐
              │  Web service (:PORT)  │
              │  Next.js + FastAPI    │  ← root Dockerfile + start.sh
              └───────────┬───────────┘
                          │
              ┌───────────▼───────────┐
              │  Managed Postgres     │
              │  + pgvector           │  ← Neon, Cloud SQL, AlloyDB, …
              └───────────────────────┘
                          │
              ┌───────────▼───────────┐
              │  GCS bucket (optional)│
              │  ENABLE_GCS=true      │
              └───────────────────────┘
```

## Shared cloud steps

1. Provision Postgres **with pgvector** (`CREATE EXTENSION vector`).
2. Set secrets: `DATABASE_URL`, `JWT_SECRET`, provider keys as needed.
3. Set `ENABLE_SIGNUP=false` for non-demo environments.
4. Deploy the **root** `Dockerfile` (combined image).
5. Confirm `GET /api/health` and log in via the UI.

See [configuration](./configuration.md).

---

## Google Cloud Run

The root README documents a deploy used for this project:

```bash
gcloud run deploy extractionprocess --source=. \
  --region=asia-south1 --project=data-unlock
```

### Recommended settings

| Setting | Suggestion |
|---------|------------|
| Source | Repo root (uses root `Dockerfile`) |
| Port | Cloud Run sets `PORT`; `start.sh` respects it |
| Memory / CPU | Raise for PDF extraction workloads |
| Timeout | Longer than default if large PDFs are common |
| Max instances | Cap cost; PDF jobs are CPU-heavy |
| Ingress | Internal / IAP if the catalogue is sensitive |

### Env vars on the service

```text
DATABASE_URL=postgresql://…          # Cloud SQL or Neon; sslmode=require
JWT_SECRET=…
ENABLE_SIGNUP=false
ENABLE_GCS=true|false
GCS_BUCKET_NAME=…                    # if ENABLE_GCS=true
ANTHROPIC_API_KEY=…                  # optional MEITY-empanelled / Anthropic-compatible
OPENAI_API_KEY=…                     # optional MEITY-empanelled / OpenAI-compatible + embeddings
SKIP_LLM=false                       # prefer “no key” for heuristic PDF/Excel; see on-prem.md
```

### Cloud SQL

- Prefer private IP + Serverless VPC Access / Direct VPC egress
- Or Auth Proxy sidecar patterns your org already uses
- Ensure the `vector` extension is allowed on the instance

### Warning

A misconfigured deploy can write to the **live catalogue** that public sites
read. Use a separate database for staging.

### GCS

When `ENABLE_GCS=true`, the service account needs object create/read on
`GCS_BUCKET_NAME`. Application Default Credentials on Cloud Run are enough if
the runtime SA is granted access.

---

## Render

`render.yaml` defines a Docker web service:

```yaml
# conceptual — see render.yaml in repo root
type: web
dockerfilePath: ./Dockerfile
envVars:
  ANTHROPIC_API_KEY   # MEITY-empanelled / Anthropic-compatible — sync: false → set in dashboard
  OPENAI_API_KEY      # MEITY-empanelled / OpenAI-compatible
  DATABASE_URL        # e.g. Neon
  JWT_SECRET
  ENABLE_GCS: "false"
```

### Steps

1. Create a Render Blueprint from the repo or manually attach the Dockerfile.
2. Attach a Postgres (or external Neon) with pgvector enabled.
3. Paste secrets in the dashboard.
4. Deploy; open `https://<service>/` and `/api/health`.

Render injects `PORT`; no extra port mapping is required.

---

## Managed Postgres tips (Neon / others)

```text
DATABASE_URL=postgresql://user:pass@host/db?sslmode=require
```

After connect:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

If you change embedding width, `EMBEDDING_DIM` must match the column; existing
vector columns may need a migration if you change dimensions later.

---

## Multi-environment layout

| Env | Database | Signup | GCS | Notes |
|-----|----------|--------|-----|-------|
| Dev | Local Docker / Neon branch | true | false | Safe experimentation |
| Staging | Separate Cloud SQL/Neon | false | optional | Same image as prod |
| Prod | Protected catalogue DB | false | true | Narrow IAM; backups |

---

## CI / image build

Cloud Run `--source=.` builds remotely. For other platforms:

```bash
docker build -t dhara-app:latest -f Dockerfile .
docker push <registry>/dhara-app:latest
```

Do not copy `backend/.env` into the image; inject at runtime.

## Related

- [On-prem](./on-prem.md) for private networks
- [Architecture](../architecture.md)
