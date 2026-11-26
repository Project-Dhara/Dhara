# Stage 6 — Grouping

**Status:** Implemented (Excel title/match grouping; PDF title/SDG propose + UI)

## Purpose

Decide which tables belong together as one logical dataset / topic / group.

| Classification | Grouping |
|----------------|----------|
| What does *this* table mean? | Which *other* tables are related to it? |

## Designed flow

```text
Approved table → title-base / SDG rules → finished groups
  → untitled tables stay singletons
  → optional suggested_merges (steward confirms)
  → optional chat LLM merge of titled singletons
  → human review → save groups
```

**OpenAI / remote embeddings are not used** in this stage. Wrong automatic
merges are worse than leaving a table alone.

## Excel / SQL

- Title-based / batch-match grouping in `GroupingWorkspace`
- Backend matching in `backend/catalogue/catalogue_matching.py`
- API: batch-match style catalogue routes

## PDF

```text
Continue from Preview
  → POST …/persist-approved  (pdf_jobs + pdf_tables SoT)
  → propose groups (title-base / SDG goal buckets)
  → untitled leftovers remain singletons
  → suggested_merges from strict structural cues (domain + entity + table_type)
  → PdfGrouping UI (confirm/dismiss suggestions, drag-and-drop, rename, save)
```

Route: `/console/grouping?jobId=…` (static desktop) / grouping shell.

APIs include grouping get/put and `…/grouping/propose`.

After Continue, **Postgres is SoT** for finished tables and groups.
`suggested_merges` are advisory only until the steward confirms.

## Design / roadmap

- Optional LLM confirmation of splits/merges (titled singletons)
- Stronger cross-job / cross-release grouping
- Tighter link from approved groups into Metadata workspace fields
