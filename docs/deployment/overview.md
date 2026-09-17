# Deployment overview

DHARA runs as:

1. **Postgres** with pgvector (required)
2. **FastAPI** backend (required)
3. **Next.js** frontend (required)
4. Optional **GCS** for Excel artefact URLs
5. Optional **LLM / embedding** provider keys

## Choose a path

| Goal | Guide |
|------|--------|
| Laptop / datacenter / air-gapped VM | [On-prem](./on-prem.md) |
| GCP Cloud Run, Render, managed DB | [Cloud](./cloud.md) |
| Env vars and secrets | [Configuration](./configuration.md) |

## Topology options

### A. Three containers (dev / on-prem)

```text
postgres (:5432) · backend (:8000) · frontend (:3000)
```

`make up` / `docker compose up -d --build`

### B. Combined app image (prod-shaped)

```text
postgres (:5432) · app (:8080)   # Next + FastAPI via start.sh
```

`make prod` / `docker compose --profile prod up -d --build postgres app`

Browser talks only to `:8080`; Next proxies `/api` to internal FastAPI.

### C. Host processes + Docker Postgres

```text
docker postgres · uvicorn on host · next dev on host
```

`make postgres` then run backend/frontend locally (see root README).

### D. Cloud single service + managed Postgres

```text
Cloud Run / Render (root Dockerfile) · Neon or Cloud SQL · optional GCS
```

## Shared requirements

- `DATABASE_URL` with pgvector available
- `JWT_SECRET` for login tokens
- `ENABLE_SIGNUP=false` on locked-down deployments
- MEITY-empanelled LLM keys only if you need full AI reconstruction / assists
  (see [on-prem](./on-prem.md) for what works without a key)

## Security checklist (any environment)

- [ ] Strong `JWT_SECRET`
- [ ] Disable open signup when not needed
- [ ] Do not point a throwaway deploy at the **live** catalogue used by
      production websites unless intentional
- [ ] Restrict who can reach the UI/API (VPN, IAP, private network)
- [ ] Rotate provider API keys; prefer Settings-scoped keys for demos
