# Stage 4 — Human review (Preview)

**Status:** Implemented for Excel and PDF

## Purpose

Stewards edit incorrect AI interpretations and approve tables. After approval,
DHARA treats the result as an **approved semantic representation**.

```text
AI proposal → human correction → human approval
            → APPROVED SEMANTIC REPRESENTATION
```

Source data rows are not silently rewritten during classification review.

## PDF Preview

Routes:

```text
/console/processing/[jobId]   extraction progress
/console/review/[jobId]       Preview (PdfReview)
```

APIs:

```text
GET   /api/pdf/jobs/{id}/result
PATCH /api/pdf/jobs/{id}/tables/{table_id}
POST  /api/pdf/jobs/{id}/tables/delete
```

Capabilities include expandable table cards, classification/column edits,
filters (needs review, garbled, alignment, …), soft-delete, and Continue →
Grouping (which persists approved tables).

## Excel / SQL Preview

Console Preview + ID/title reconciliation (`ReconcileIds`) before grouping.
Staging may use `extract_staging` between extract and catalogue push.

## Design rules

- Reviewers must see *why* something needs attention (`human_review_reason`)
- Soft-delete / exclude tables that should not enter the catalogue
- Continue is an explicit gate into grouping / metadata
