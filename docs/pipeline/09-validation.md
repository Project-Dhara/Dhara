# Stage 9 — Validation

**Status:** Design + partial checks in metadata/extract paths

## Purpose

After (or before) publish, verify structural integrity and semantic consistency
of approved / transformed data.

## Structural checks

```text
Schema · column names · types · dates · units · IDs
Nulls · duplicates · ranges · row shape
```

## Semantic checks

```text
Do mapped columns still mean what was approved?
Are units compatible across related tables?
Are categories members of the approved code list?
Do grouped tables share compatible concepts?
```

## Provenance

Every transformation should remain traceable:

```text
Original value → rule/mapping → harmonised value → standard → approval
```

## In this codebase

- `backend/metadata/validation.py` and related fill/match guards
- PDF alignment / garbled flags surface issues earlier in Preview
- Full post-transform QA dashboard is **roadmap**

## Design target

Gate Publish (or a post-publish “quality” badge) on a validation report that
stewards can override with an explicit reason.
