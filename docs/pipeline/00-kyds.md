# Stage 0 — KYDS / dataset context

**Status:** Implemented (KYDS entries in Postgres + UI)

## Purpose

Before (or alongside) processing files, DHARA captures what the **data
custodian says** the dataset is. That context is distinct from what extraction
later finds in the file.

| Source | Question answered |
|--------|-------------------|
| KYDS | What does the custodian claim this dataset is? |
| Extraction | What is physically present in the file? |
| Semantic understanding | What does the extracted data appear to mean? |
| Human approval | What is the trusted interpretation? |

## Typical fields

```text
Dataset purpose · Custodian · Domain · Entity
Geography · Time period · Frequency · Source
Existing metadata · Existing standards
```

KYDS is complementary to **Settings → Metadata configuration** (NMDS / SDG
schema and required fields). KYDS captures custodian narrative; Settings
chooses which catalogue schema later Metadata / Publish steps enforce. See
[Configuration modules](./overview.md#configuration-modules).

## Design

KYDS does not replace Preview. It seeds later metadata fill and helps reviewers
judge whether extracted tables match the intended product.

## In this codebase

- Table: `kyds_entries`
- API: KYDS routes under `backend/routes/kyds.py`
- UI: KYDS modal / dashboard entry points

## Next / design notes

Deeper binding of KYDS fields into PDF group metadata and automated
consistency checks against approved classifications remains roadmap work.
