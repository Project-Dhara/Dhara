# Stage 10 — Metadata & catalogue

**Status:** Implemented (batch push to Postgres catalogue)

## Purpose

Persist approved groups and tables as **discoverable catalogue records** with
metadata suitable for government statistical products.

## Metadata concerns

Potential standards / profiles:

```text
NMDS · DCAT-AP · SDG tags · local DES conventions
```

Catalogue records should expose (as available):

```text
Dataset · tables · descriptions · custodian · domain
Geography · time · frequency · variables · concepts
Standards · provenance · quality · access info
```

## Console

- **Metadata** step: fill group-level catalogue fields
  (`fill-group-metadata`, BatchReview)
- **Publish** / batch push writes to Postgres

## In this codebase

| Piece | Location |
|-------|----------|
| Push | `backend/catalogue/datasets.py` (`push_to_catalogue`) |
| API | `POST /api/catalogue/batch-push` |
| Tables | `metadata_groups`, `datasets`, `dataset_rows` |
| Browse UI | Catalogue section in the frontend |
| Optional files | GCS when `ENABLE_GCS=true` |

### What gets pushed (typical)

Per dataset table: title/description, inherited group metadata, classifications
/ units (enrichment pass), and Excel exports when storage is enabled:

- `source_excel` — clean re-flattened table
- `original_excel` — source sheet formatting preserved

Downstream sites (e.g. des-website) prefer `original_excel`, falling back to
`source_excel`.

## Design / roadmap

- Stronger NMDS/DCAT export packages
- Deeper PDF-group → metadata-group binding without Excel-shaped staging
