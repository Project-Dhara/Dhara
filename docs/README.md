# DHARA documentation

DHARA is a human-in-the-loop data cataloguing toolkit for government statistical
releases. It ingests Excel, SQL, and PDF sources, helps stewards review and
harmonise tables, and publishes approved datasets into a shared Postgres
catalogue.

**Core principle:** AI proposes → human reviews → human approves → DHARA
remembers the approved meaning.

## Contents

| Doc | What it covers |
|-----|----------------|
| [Architecture](./architecture.md) | System components, data stores, console stages, design principles |
| [Pipeline overview](./pipeline/overview.md) | End-to-end flow and implementation status |
| [Pipeline stages](./pipeline/) | Design + behaviour for each step (including planned stages) |
| [Deployment overview](./deployment/overview.md) | Choose on-prem vs cloud |
| [On-prem deployment](./deployment/on-prem.md) | Docker Compose, host-run, air-gapped notes |
| [Cloud deployment](./deployment/cloud.md) | Cloud Run, Render, managed Postgres, GCS |
| [Configuration](./deployment/configuration.md) | Environment variables and secrets |

## Quick links

- Root [README](../README.md) — quick start and project layout
- API Swagger (local) — `http://localhost:8000/docs`
- License — [Apache 2.0](../LICENSE)

## Reading order

1. [Architecture](./architecture.md) — how the pieces fit
2. [Pipeline overview](./pipeline/overview.md) — what happens to data
3. Stage docs under [pipeline/](./pipeline/) for any step you care about
4. [Deployment](./deployment/overview.md) for where you will run it
