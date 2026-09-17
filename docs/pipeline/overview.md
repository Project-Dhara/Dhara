# Pipeline overview

DHARA’s logical pipeline is the same whether the input is PDF, Excel, or SQL.
Intake adapters differ; semantic review, grouping, harmonisation, and catalogue
publish share one design.

**Configuration modules** (Settings) are cross-cutting: they are not a numbered
stage, but they govern dataset IDs, metadata standards, classification codes,
and optional LLM use across the flow.

## End-to-end flow

```text
                    GOVERNMENT DATA
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
            PDF         Excel        SQL
              │           │           │
              └───────────┼───────────┘
                          ▼
              0  KYDS / context (optional)
                          ▼
              1  Extraction (physical tables)
                          ▼
              2  Confidence + reconstruction
                          ▼
              3  Initial semantic understanding
                          ▼
              4  Human review (Preview)
                          ▼
                 APPROVED SEMANTIC REPRESENTATION
                          ▼
              5  Semantic chunks + embeddings
                          ▼
              6  Grouping (similarity → human)
                          ▼
              7  Harmonisation (standards / codes)
                          ▼
              8  Transformation (apply mappings)
                          ▼
              9  Validation
                          ▼
             10  Metadata & catalogue
                          ▼
             11  Access (Catalogue / API / MCP)


        ══ Configuration modules (Settings) ══════════════════════
           Dataset ID · Metadata (NMDS/SDG) · Classification
           codes · MEITY-empanelled LLM key
           → feed stages 2–4, 6–7, 10 (and LLM paths throughout)
```

## Configuration modules

Stewards configure DHARA in **Settings** before or during a Console run. These
modules are product configuration (not deploy env vars).

| Module | Settings tab / card | Effect on the pipeline |
|--------|---------------------|------------------------|
| **Dataset ID configuration** | Dataset ID configuration | Prefix, separator, and statistics domain used when minting / displaying dataset IDs in Preview and publish |
| **Metadata configuration** | Metadata configuration | Chooses **NMDS** vs **SDG** schema; marks which catalogue fields are required before submit |
| **Classification code configuration** | Classification code configuration | Uploads concordance / code-list CSVs into Postgres for stage 7 harmonisation |
| **MEITY-empanelled LLM** | LLM card | Enables reconstruction, metadata autofill, matching, and related AI proposals when a key is set |

| Module | Primary stages |
|--------|----------------|
| Dataset ID | 4 Preview · 10 Publish |
| Metadata standard / required fields | 0 KYDS (context) · 10 Metadata & catalogue |
| Classification codes | 7 Harmonisation · (8 Transformation) |
| LLM key | 2–3 Reconstruction / semantics · 6–7 · 10 fill |

Implementation notes:

- Dataset ID + metadata prefs: `frontend/src/lib/settingsConfig.ts` (browser)
- Classification standards API: catalogue `classification-standards` routes;
  UI in `Settings.jsx`
- Architecture summary: [Configuration modules](../architecture.md#configuration-modules)
- Deploy-time secrets / DB: [deployment/configuration.md](../deployment/configuration.md)

## Implementation status

| Stage | Design | Excel/SQL | PDF | Notes |
|-------|--------|-----------|-----|-------|
| Config modules | ✓ | ✓ | ✓ | Settings; see table above |
| 0 KYDS | ✓ | ✓ | ✓ | Custodian context before/alongside ingest |
| 1 Extraction | ✓ | ✓ | ✓ | openpyxl / sql_extract / PyMuPDF |
| 2 Confidence + reconstruction | ✓ | partial | ✓ | PDF: deterministic confidence + LLM path |
| 3 Semantic understanding | ✓ | ✓ | ✓ | Often same LLM call as reconstruction |
| 4 Human review | ✓ | ✓ | ✓ | Console Preview (+ Dataset ID rules) |
| 5 Vector index | ✓ | limited | ✓ | pgvector; PDF Continue indexes tables |
| 6 Grouping | ✓ | ✓ | ✓ | Excel: title/match; PDF: embeddings + UI |
| 7 Harmonisation | ✓ | ✓ | wired | Classify + Settings classification codes |
| 8 Transformation | design | partial | partial | Mappings stored; full transform layer planned |
| 9 Validation | design | partial | partial | Structural checks exist; full QA planned |
| 10 Metadata & catalogue | ✓ | ✓ | ✓ | `batch-push`; NMDS/SDG from Settings |
| 11 Access API/MCP | ✓ | ✓ | ✓ | `/api/v1` + stdio MCP |

Status legend: **✓** usable in the POC · **partial** some code/UI · **design**
documented intent without a complete product surface · **wired** shares Excel
post-preview steps from the PDF grouping screen.

## Console mapping

| Console step | Pipeline stages |
|--------------|-----------------|
| **Settings** (anytime) | Configuration modules |
| Files | 0–1 (and PDF processing progress) |
| Preview | 2–4 |
| Grouping | 5–6 |
| Metadata | 10 (group fields before push; schema from Settings) |
| Classification & harmonisation | 7 (and parts of 8; codes from Settings) |
| Publish | 10–11 |

## Stage docs

| Doc | Stage |
|-----|-------|
| [00 — KYDS](./00-kyds.md) | Dataset context |
| [01 — Extraction](./01-extraction.md) | Physical tables from files/SQL |
| [02 — Reconstruction](./02-reconstruction.md) | Confidence + clean tables |
| [03 — Semantic understanding](./03-semantic-understanding.md) | What the table appears to mean |
| [04 — Human review](./04-human-review.md) | Approve / edit AI proposals |
| [05 — Vector index](./05-vector-index.md) | Chunks + pgvector |
| [06 — Grouping](./06-grouping.md) | Related tables |
| [07 — Harmonisation](./07-harmonization.md) | Standards and codes |
| [08 — Transformation](./08-transformation.md) | Apply approved mappings |
| [09 — Validation](./09-validation.md) | Structure + semantics |
| [10 — Metadata & catalogue](./10-metadata-catalogue.md) | Publish metadata/datasets |
| [11 — Access](./11-access.md) | Catalogue, API, MCP |

## AI pattern (every semantic step)

```text
AI proposal → retrieval of candidates → reason → human review → approval
→ authoritative knowledge in Postgres
```

AI must not silently promote uncertain interpretations to truth.
