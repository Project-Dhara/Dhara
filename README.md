# DHARA Toolkit

Internal tool for building and maintaining the DES Delhi data catalog (the
Postgres database that [des-website](https://des-website-235956738573.asia-south1.run.app)
reads from). Takes raw government Excel workbooks, uses Claude to extract
their tables, matches them against metadata tag files, and pushes the
result — dataset records, metadata groups, and clean per-table Excel
exports — into the catalog.

## Project structure

```
extraction_comp/
├── backend/                     FastAPI + openpyxl + Claude AI + Postgres + GCS
│   ├── main.py                  API routes
│   ├── extractor.py             Claude-based table extraction from Excel
│   ├── catalogue_matching.py    Matches extracted tables to metadata rows
│   ├── metadata_excel.py        Parses metadata workbooks
│   ├── table_export.py          Clean re-flattened per-table Excel export
│   ├── original_sheet_export.py Formatting-preserving single-sheet export
│   ├── catalogue.py             Postgres schema + push logic
│   └── requirements.txt
└── frontend/                    React + Vite
    └── src/
        ├── App.jsx               Switches between the two flows below
        └── components/
            ├── ModeSelector.jsx  Sidebar toggle between the two flows
            ├── BatchFlow.jsx     Batch upload + auto-map (see below)
            ├── BatchUpload.jsx
            ├── BatchReview.jsx
            ├── SingleFileFlow.jsx  Original single-file flow (see below)
            ├── FileUpload.jsx
            ├── TableSidebar.jsx
            ├── TableViewer.jsx
            └── PushModal.jsx
```

## Two upload flows

Both write to the same catalog; pick whichever suits the task.

**Batch Auto-Map** — upload every dataset workbook and every metadata tag
file for a release together. Tables are extracted (Claude), then matched
to their metadata rows automatically (exact ID match → typo-tolerant
match → table-code + keyword disambiguation, in that order). Nothing gets
matched wrong silently: anything ambiguous or unmatched is flagged for
manual review before you confirm and push.

**Single File (Manual)** — upload one dataset workbook at a time, review
extracted tables individually, group them, and fill in (or edit) metadata
by hand via the Create Metadata modal. Selecting an existing group prefills
its current metadata; editing any field creates a new group instead of
overwriting the one other datasets are already filed under. The "Source
Excel" picker also auto-fills the form from a metadata workbook's
`catalogue_summary` sheet.

## Setup

### 1. Environment

Copy `backend/.env.example` to `backend/.env` and fill in:

```
ANTHROPIC_API_KEY=sk-ant-...          # Claude API key, used for extraction + enrichment
DATABASE_URL=postgresql://...          # same Postgres DB des-website reads from
GCS_BUCKET_NAME=dhara-toolkit-excel    # bucket for metadata + dataset Excel exports
```

### 2. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 — Vite proxies `/api` to `localhost:8000`.

## Deployment

Deployed as the Cloud Run service `extractionprocess` (project `data-unlock`,
region `asia-south1`), built from the root `Dockerfile` (multi-stage: builds
the Vite frontend, then bundles it into the FastAPI backend's static dir).
Pushing to `main` on the repo the Cloud Build trigger watches deploys
automatically; from any other remote (e.g. a fork without trigger access),
deploy manually:

```bash
gcloud run deploy extractionprocess --source=. --region=asia-south1 --project=data-unlock
```

**Warning**: this writes directly to the live catalog database that
`des-website` serves to the public. There's no auth in front of either the
API or the push endpoints — treat access to this tool (and to who can
deploy it) accordingly.

## What gets pushed to the catalog

Per dataset table: title/description, category/geography/frequency/etc.
(inherited from its metadata group), classifications and units (via a
Claude enrichment pass), and two downloadable Excel exports —
`source_excel` (a clean, re-flattened single-table version) and
`original_excel` (the actual source sheet with formatting — merged cells,
multi-row headers — intact, one per unique source sheet). `des-website`
prefers `original_excel` on download, falling back to `source_excel` for
any dataset pushed before `original_excel` existed.
