# Stage 3 — Initial semantic understanding

**Status:** Implemented (often combined with reconstruction in one LLM call)

## Purpose

Propose what a table and its columns **appear to mean**. This is
**classification**, not harmonisation.

| Ask now | Ask later (harmonisation) |
|---------|---------------------------|
| What does this represent? | Which canonical standard/code should it map to? |

## Table-level proposals

```text
Domain · Subject · Entity · Table type
Geography · Time period · Frequency · Unit
```

## Column-level proposals

```text
Name · Role · Concept · Description · Data type · Unit · Category
```

### Roles

```text
identifier | dimension | measure | attribute | unknown
```

Example:

```text
State     → dimension → concept: State
PHC ID    → identifier → concept: Primary Health Centre
Male      → measure → Population · category Male
```

## Uncertainty tracking

Proposals may carry:

```text
human_review_needed
human_review_reason   e.g. uncertain_semantic_role
```

Flags can exist at table, field, or column level.

Important distinction:

| Field | Meaning |
|-------|---------|
| `semantic_status` | Has classification happened? |
| `human_review_needed` | Does an existing result need attention? |

A high-confidence table that bypassed the LLM can have
`semantic_status = not_classified` and `human_review_needed = false`.

## Design

LLM output is a **proposal**, never authoritative truth, until Preview approval.
