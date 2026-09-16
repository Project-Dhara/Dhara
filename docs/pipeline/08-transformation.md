# Stage 8 — Transformation

**Status:** Design + partial support (mappings exist; full transform engine planned)

## Purpose

Once mappings are approved, apply them to produce a **harmonised representation**
while keeping original source data immutable.

## Designed flow

```text
Approved mapping rules
  → transform pass over staged / published tables
  → harmonised columns / values
  → provenance for every change
```

Examples:

```text
Source M/F     → canonical Male/Female (or reverse for a target schema)
Source state name → LGD geography code
Occupation string → NCO family / division code
```

## Design rules

- Source workbook / PDF grids remain unchanged
- Derived outputs are explicit artefacts (exports, catalogue fields, side tables)
- Every transformed value should point at rule + approval

## In this codebase today

- Classification / NCO suggestions feed steward decisions
- Catalogue push writes cleaned Excel exports (`source_excel` /
  `original_excel`) when GCS is enabled
- A dedicated, reusable transformation rule engine and batch re-apply across
  releases is **roadmap**

## Target architecture

```text
mappings (Postgres) → transform service → validation → catalogue refresh
```
