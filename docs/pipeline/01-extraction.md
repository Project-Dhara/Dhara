# Stage 1 — Extraction

**Status:** Implemented for PDF, Excel, and SQL

## Purpose

Turn source artefacts into **candidate tables** (grids + light structure)
without silently inventing values. Extraction is physical, not semantic.

## Paths

### PDF

```text
PDF → PyMuPDF page inspection → find_tables()
    → lines_strict + text-based candidates → candidate tables
```

Key modules: `backend/pdf/sda_india_pdf_extraction.py`, workers,
`pdf_table_confidence.py`, `pdf_dual_column.py`. Jobs are orchestrated via
`backend/pdf/pdf_jobs.py` and `backend/routes/pdf.py`.

### Excel

```text
Workbook → openpyxl-based extract → sheet/table candidates
         → optional metadata tag-file matching
```

Key module: `backend/extraction/extractor.py`. API:
`POST /api/catalogue/batch-extract`.

### SQL

```text
Postgres URL → introspect / run extract
  → DHARA catalogue DBs expand datasets from dataset_rows.row_data
  → same review path as Excel
```

Key module: `backend/extraction/sql_extract.py`. API:
`POST /api/catalogue/sql-extract`.

## Design rules

- Prefer native parsers over OCR unless required
- Do not rewrite source cell values during extract
- Preserve enough provenance to show stewards where a grid came from
- Multi-strategy PDF extraction feeds confidence (stage 2)

## Console

**Files** step: upload Excel / connect SQL / upload PDF → processing UI for PDF.
