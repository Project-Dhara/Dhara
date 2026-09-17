# Stage 7 — Harmonisation

**Status:** Partially implemented (Classify + classification standards / NCO matching)

## Purpose

Align observed meanings to **canonical concepts and official code lists**.

Example problem:

```text
Dataset A: Gender = M / F
Dataset B: Sex = Male / Female
Dataset C: Gender = 1 / 2
```

Classification already said these are “sex/gender” measures. Harmonisation asks
whether they map to one shared concept and standard codes.

## Designed flow

```text
Observed source value
  → AI interpretation
  → Canonical concept
  → Official standard / code
  → Human approval
  → Store mapping + provenance (do not overwrite source)
```

## Potential standards

```text
NMDS · LGD · NCO · NIC · domain-specific lists
```

## In this codebase

- Console **Classification & harmonisation** step (`Classify.jsx`)
- `backend/catalogue/classifications.py` — steward code lists / definitions
- `nco_matching.py` + `nco_aliases.py` — occupation matching (LLM optional)
- `classification_standards.py` — upload concordance CSV in
  **Settings → Classification code configuration**; codes stored in Postgres
- Working matching set still read from `nco_2015_codes` shape

NCO concordance files are **not** redistributed in the repo. Stewards upload
them; see `backend/data/nco_2015_concordance.csv.example` for columns.

### Configuration modules (required for this stage)

| Module | Role |
|--------|------|
| **Classification code configuration** | Source of official / uploaded code lists used when mapping observed values |
| **MEITY-empanelled LLM** | Optional assistance for occupation / alias matching when a key is set |

Without uploaded classification standards, harmonisation has little or no code
list to match against. See [Configuration modules](./overview.md#configuration-modules).

## Design / roadmap

- Broader non-occupation standards UX
- Cross-table consistency of approved mappings
- Explicit mapping store with full provenance UI
