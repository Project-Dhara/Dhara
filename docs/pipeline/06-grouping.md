# Stage 6 — Grouping

**Status:** Implemented (Excel title/match grouping; PDF embedding propose + UI)

## Purpose

Decide which tables belong together as one logical dataset / topic / group.

| Classification | Grouping |
|----------------|----------|
| What does *this* table mean? | Which *other* tables are related to it? |

## Designed flow

```text
Approved table → semantic representation → embedding
  → pgvector similarity → candidate set
  → (optional) LLM cluster reason → human review → approved groups
```

Vector similarity is **candidate retrieval**, not the final decision. Lexical /
title matching and steward edits complete the picture.

## Excel / SQL

- Title-based / batch-match grouping in `GroupingWorkspace`
- Backend matching in `backend/catalogue/catalogue_matching.py`
- API: batch-match style catalogue routes

## PDF

```text
Continue from Preview
  → POST …/persist-approved  (pdf_jobs + pdf_tables SoT)
  → embed table_summary (+ columns)
  → propose groups (cosine clustering / union-find)
  → PdfGrouping UI (automatic / manual, drag-and-drop, rename, save)
```

Route: `/console/grouping/[jobId]`.

APIs include grouping get/put and `…/grouping/propose`.

After Continue, **Postgres is SoT** for tables and groups (not the ephemeral
JSON working cache alone).

## Design / roadmap

- Optional LLM confirmation of splits/merges
- Stronger cross-job / cross-release grouping
- Tighter link from approved groups into Metadata workspace fields
