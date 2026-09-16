# Stage 2 — Confidence & reconstruction

**Status:** Strong for PDF; Excel relies more on sheet structure + later review

## Purpose

Not every table needs an LLM. First evaluate **deterministic confidence**, then
either accept the grid or send ambiguous candidates for LLM reconstruction.

## Confidence signals (PDF)

```text
Cell fill rate · Header shape · Candidate agreement · Table structure
```

```text
High confidence  → accept directly (may skip LLM)
Lower confidence → LLM reconstruction queue
```

## Reconstruction (LLM)

When invoked, the model reconciles competing extractions into a logical table:

- Flatten multi-row headers where needed
- Preserve titles / descriptions
- Flag uncertain cells
- Avoid inventing values not grounded in candidates

### Post-LLM guards (PDF POC)

```text
Strip ungrounded Direction / Trend columns not in source candidates
Flag column_alignment_mismatch when columns disagree with candidates
Optional fallback to lines_strict grid when alignment is badly broken
Retry BrokenProcessPool with smaller worker pools on OOM
```

## Design

Reconstruction answers: **What is the clean table?**  
It does not yet answer: **Which official standard code applies?**

## In this codebase

- `backend/pdf/pdf_table_confidence.py`
- LLM path inside PDF extraction pipeline
- `SKIP_LLM=true` uses heuristic structure instead of Claude
