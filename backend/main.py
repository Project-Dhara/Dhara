import concurrent.futures
import os
import pathlib
import json as _json
import asyncio
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from extractor import TableExtractor
import catalogue as _cat
from metadata_excel import parse_catalogue_summary, parse_metadata_workbook
from catalogue_matching import match_tables_to_metadata, match_result_to_push_groups
from table_export import table_to_excel_bytes
from original_sheet_export import extract_sheet_with_formatting_from_bytes

app = FastAPI(title="Table Extractor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

LLM_KEY_HEADER = "x-llm-api-key"

# GCS is opt-in so local/dev can push catalogue rows to Neon without a
# bucket. Set ENABLE_GCS=true (and GCS_BUCKET_NAME) for production Excel
# uploads. Placeholder bucket names are treated as unset.
_GCS_SKIP_LOGGED = False


def _gcs_enabled() -> bool:
    return os.getenv("ENABLE_GCS", "").strip().lower() in ("1", "true", "yes")


def _gcs_bucket_name() -> str:
    name = os.getenv("GCS_BUCKET_NAME", "").strip()
    if not name or name.startswith("your_"):
        return ""
    return name


def _extractor_for(request: Request) -> TableExtractor:
    """Build a TableExtractor from the caller's own LLM API key, sent on
    every LLM-backed request from the frontend's Settings screen. No key on
    the request means no LLM calls -- this replaces the old .env-based
    ANTHROPIC_API_KEY / SKIP_LLM toggle, which is no longer read."""
    key = request.headers.get(LLM_KEY_HEADER, "").strip() or None
    return TableExtractor(api_key=key, skip_llm=not key)


def _read_file(file: UploadFile) -> bytes:
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Only .xlsx / .xls files are supported")
    if file.filename.lower().endswith(".xls"):
        raise HTTPException(
            400,
            "Legacy .xls format is not supported. Re-save the file as .xlsx in Excel.",
        )
    return None  # signal to caller to await


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/extract")
async def extract_direct(request: Request, file: UploadFile = File(...)):
    """Direct LLM mode — single prompt → single response per table."""
    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(400, "Only .xlsx files are supported (re-save .xls as .xlsx)")
    content = await file.read()
    extractor = _extractor_for(request)
    try:
        tables = extractor.extract_from_file(content, file.filename)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Extraction error: {e}")
    return {"filename": file.filename, "mode": "direct_llm", "table_count": len(tables), "tables": tables}



@app.post("/api/table-metadata")
async def table_metadata(request: Request):
    """LLM-based semantic category extraction from a table's raw structure."""
    data = await request.json()
    extractor = _extractor_for(request)
    try:
        categories = extractor.extract_category_metadata(
            title=data.get("title", ""),
            description=data.get("description", ""),
            raw_header_rows=data.get("raw_header_rows", []),
            columns=data.get("columns", []),
            sample_rows=data.get("sample_rows", []),
            raw_notes=data.get("raw_notes", []),
        )
    except Exception as e:
        raise HTTPException(500, f"Metadata extraction error: {e}")
    return {"categories": categories}



@app.post("/api/group-tables")
async def group_tables(
    tables_json: str = Form(...),
    metadata_files: list[UploadFile] = File(None),
):
    """Group extracted tables using the same rule-based logic as batch upload."""
    tables = _json.loads(tables_json)
    for t in tables:
        if not t.get("source_file"):
            t["source_file"] = t.get("filename") or "Dataset"

    metadata_payloads = []
    if metadata_files:
        for f in metadata_files:
            if not f or not f.filename:
                continue
            if not f.filename.lower().endswith((".xlsx", ".xls")):
                raise HTTPException(400, f"Only .xlsx/.xls files are supported ({f.filename})")
            content = await f.read()
            metadata_payloads.append((f.filename, content))

    def _run():
        workbooks = []
        for filename, content in metadata_payloads:
            try:
                workbooks.append(parse_metadata_workbook(content, filename))
            except ValueError as e:
                raise ValueError(f"{filename}: {e}")
        result = match_tables_to_metadata(tables, workbooks)
        return match_result_to_push_groups(result)

    try:
        groups = await asyncio.to_thread(_run)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Grouping error: {e}")
    return {"groups": groups}


@app.get("/api/catalogue/groups")
async def get_catalogue_groups():
    def _run():
        conn = _cat.get_connection()
        _cat.init_schema(conn)
        groups = _cat.list_metadata_groups(conn)
        conn.close()
        return groups
    try:
        groups = await asyncio.to_thread(_run)
        return {"groups": groups}
    except Exception as e:
        raise HTTPException(500, f"Catalogue error: {e}")


@app.post("/api/catalogue/parse-metadata-excel")
async def parse_metadata_excel(file: UploadFile = File(...)):
    """Reads a DES metadata workbook's `catalogue_summary` sheet and returns
    the fields used to prefill the Create Metadata form."""
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Only .xlsx / .xls files are supported")
    content = await file.read()
    try:
        fields = await asyncio.to_thread(parse_catalogue_summary, content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Failed to parse metadata Excel: {e}")
    return {"fields": fields}


@app.post("/api/catalogue/batch-extract")
async def batch_extract(request: Request, files: list[UploadFile] = File(...)):
    """Runs table extraction across multiple uploaded dataset workbooks
    concurrently (each file's sheets are also processed concurrently, see
    TableExtractor.extract_from_file) and returns one combined table list,
    each tagged with its source file."""
    extractor = _extractor_for(request)
    for f in files:
        if not f.filename.lower().endswith(".xlsx"):
            raise HTTPException(400, f"Only .xlsx files are supported ({f.filename})")

    contents = [(f.filename, await f.read()) for f in files]

    def _attach_original_sheets(filename: str, content: bytes, tables: list):
        # One extraction+upload per unique sheet (several tables can share a
        # sheet, e.g. urban/rural split within one physical sheet) -- every
        # table on that sheet points at the same file, which is correct: if
        # the source doesn't separate them, neither should the download.
        cache = {}
        for t in tables:
            sheet = t.get("sheet")
            if not sheet:
                continue
            if sheet not in cache:
                xlsx_bytes = extract_sheet_with_formatting_from_bytes(content, sheet)
                cache[sheet] = _upload_original_sheet_to_gcs(xlsx_bytes, filename, sheet)
            t["original_excel_url"] = cache[sheet]

    async def _extract_one(filename: str, content: bytes):
        try:
            tables = await asyncio.to_thread(extractor.extract_from_file, content, filename)
        except ValueError as e:
            raise HTTPException(400, f"{filename}: {e}")
        except Exception as e:
            raise HTTPException(500, f"Extraction error in {filename}: {e}")
        for t in tables:
            t["source_file"] = filename
        try:
            await asyncio.to_thread(_attach_original_sheets, filename, content, tables)
        except Exception as e:
            # Non-fatal -- matching/review/push all still work without this,
            # datasets just fall back to the flat export on download.
            print(f"Original-sheet export failed for {filename}: {e}")
        return filename, tables

    results = await asyncio.gather(*(_extract_one(fn, ct) for fn, ct in contents))

    all_tables = []
    per_file = []
    for filename, tables in results:
        all_tables.extend(tables)
        per_file.append({"filename": filename, "table_count": len(tables)})
    return {"tables": all_tables, "per_file": per_file, "table_count": len(all_tables)}


@app.post("/api/catalogue/batch-match")
async def batch_match(
    tables_json: str = Form(...),
    metadata_files: list[UploadFile] = File(None),
):
    """Parses multiple metadata workbooks and matches them against a set of
    already-extracted tables. Returns a proposed mapping for review --
    nothing is written to the database here. Metadata files are optional;
    when omitted, groups are returned with empty catalogue fields."""
    tables = _json.loads(tables_json)

    metadata_payloads = []
    if metadata_files:
        for f in metadata_files:
            if not f or not f.filename:
                continue
            if not f.filename.lower().endswith((".xlsx", ".xls")):
                raise HTTPException(400, f"Only .xlsx/.xls files are supported ({f.filename})")
            content = await f.read()
            metadata_payloads.append((f.filename, content))

    def _run():
        workbooks = []
        for filename, content in metadata_payloads:
            try:
                workbooks.append(parse_metadata_workbook(content, filename))
            except ValueError as e:
                raise ValueError(f"{filename}: {e}")
        return match_tables_to_metadata(tables, workbooks)

    try:
        result = await asyncio.to_thread(_run)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Matching error: {e}")
    return result


@app.post("/api/catalogue/batch-push")
async def batch_push(
    request: Request,
    groups_json: str = Form(...),
    metadata_files: list[UploadFile] = File(None),
):
    """Pushes a reviewed/confirmed batch mapping to the catalogue -- one
    metadata group + its matched tables per entry in `groups_json`.

    Two phases, deliberately kept separate: (1) slow work -- per-table LLM
    enrichment and optional GCS uploads, parallelized -- happens BEFORE any
    database connection is opened, and (2) fast DB writes happen only once
    everything is ready. Doing this in one phase with a connection held open
    for the whole thing caused Neon to drop the (idle, minutes-long)
    connection before it could commit. GCS is skipped unless ENABLE_GCS=true."""
    groups = _json.loads(groups_json)
    extractor = _extractor_for(request)

    metadata_by_index = {}
    if metadata_files:
        for i, f in enumerate(metadata_files):
            if f and f.filename:
                metadata_by_index[i] = (f.filename, await f.read())

    def _prep_table(t):
        # Preserve the extractor's own clean table structure as a
        # downloadable single-sheet Excel per dataset, so a download
        # reflects what was actually cataloged rather than a re-flattened
        # reconstruction from the DB rows.
        xlsx_bytes = table_to_excel_bytes(t)
        t["source_excel_url"] = _upload_table_excel_to_gcs(xlsx_bytes, t.get("id", ""))
        return t, extractor.enrich_for_catalogue(t)

    def _prepare_group(group):
        tables = [mt["table"] for mt in group.get("matched_tables", [])]
        if not tables:
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            prepped = list(pool.map(_prep_table, tables))

        excel_url = None
        wi = group.get("workbook_index")
        if wi in metadata_by_index:
            filename, content = metadata_by_index[wi]
            excel_url = _upload_excel_to_gcs(content, filename)

        return {
            "meta": group.get("metadata", {}),
            "tables": [t for t, _ in prepped],
            "enriched": [e for _, e in prepped],
            "excel_url": excel_url,
        }

    def _prepare_all():
        return [g for g in (_prepare_group(group) for group in groups) if g]

    def _write_all(prepared):
        conn = _cat.get_connection()
        _cat.init_schema(conn)
        results = []
        try:
            for p in prepared:
                meta = p["meta"]
                result = _cat.push_to_catalogue(
                    conn, p["tables"], p["enriched"], "new", None,
                    meta.get("title") or meta.get("product"),
                    meta.get("description"),
                    meta.get("product"),
                    meta.get("category"),
                    meta.get("geography"),
                    meta.get("frequency"),
                    meta.get("time_period"),
                    meta.get("data_source"),
                    meta.get("last_updated"),
                    meta.get("future_release"),
                    meta.get("key_statistics"),
                    meta.get("remarks"),
                    p["excel_url"],
                )
                results.append(result)
        finally:
            conn.close()
        return results

    try:
        prepared = await asyncio.to_thread(_prepare_all)
    except Exception as e:
        raise HTTPException(500, f"Preparation error: {e}")

    try:
        results = await asyncio.to_thread(_write_all, prepared)
    except Exception as e:
        raise HTTPException(500, f"Push error: {e}")

    return {"results": results, "groups_pushed": len(results)}


def _upload_bytes_to_gcs(file_bytes: bytes, blob_name: str) -> Optional[str]:
    """Upload bytes to GCS, or return None when GCS is disabled (local/dev)."""
    global _GCS_SKIP_LOGGED
    if not _gcs_enabled():
        if not _GCS_SKIP_LOGGED:
            print("GCS uploads skipped (ENABLE_GCS is not true). Catalogue rows will still be written to Postgres.")
            _GCS_SKIP_LOGGED = True
        return None

    from google.cloud import storage as gcs
    bucket_name = _gcs_bucket_name()
    if not bucket_name:
        raise ValueError(
            "ENABLE_GCS is true but GCS_BUCKET_NAME is not set. "
            "Set GCS_BUCKET_NAME, or set ENABLE_GCS=false for Neon-only local testing."
        )
    client = gcs.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(file_bytes, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return f"gs://{bucket_name}/{blob_name}"


def _upload_excel_to_gcs(file_bytes: bytes, filename: str) -> Optional[str]:
    """Upload a metadata workbook and return the gs:// URL, stored on
    metadata_groups.metadata_excel. Returns None when GCS is disabled."""
    return _upload_bytes_to_gcs(file_bytes, f"metadata_excel/{filename}")


def _upload_table_excel_to_gcs(file_bytes: bytes, dataset_id: str) -> Optional[str]:
    """Upload a per-dataset clean Excel export (see table_export.py) and
    return the gs:// URL, stored on datasets.source_excel. Returns None
    when GCS is disabled."""
    return _upload_bytes_to_gcs(file_bytes, f"datasets/{dataset_id}.xlsx")


def _upload_original_sheet_to_gcs(file_bytes: bytes, source_file: str, sheet: str) -> Optional[str]:
    """Upload a formatting-preserving single-sheet export (see
    original_sheet_export.py) and return the gs:// URL, stored on
    datasets.original_excel. Returns None when GCS is disabled."""
    safe_name = f"{source_file}__{sheet}".replace("/", "_")
    return _upload_bytes_to_gcs(file_bytes, f"original_sheets/{safe_name}.xlsx")


@app.post("/api/catalogue/push")
async def push_to_catalogue(
    request: Request,
    tables_json: str = Form(...),
    metadata_mode: str = Form(...),
    metadata_id: Optional[str] = Form(None),
    meta_title: Optional[str] = Form(None),
    meta_description: Optional[str] = Form(None),
    meta_product: Optional[str] = Form(None),
    meta_category: Optional[str] = Form(None),
    meta_geography: Optional[str] = Form(None),
    meta_frequency: Optional[str] = Form(None),
    meta_time_period: Optional[str] = Form(None),
    meta_data_source: Optional[str] = Form(None),
    meta_last_updated: Optional[str] = Form(None),
    meta_future_release: Optional[str] = Form(None),
    meta_key_statistics: Optional[str] = Form(None),
    meta_remarks: Optional[str] = Form(None),
    meta_excel: Optional[UploadFile] = File(None),
):
    tables = _json.loads(tables_json)
    extractor = _extractor_for(request)

    # Upload Excel to GCS if provided
    excel_url = None
    if meta_excel and meta_excel.filename:
        excel_bytes = await meta_excel.read()
        if excel_bytes:
            try:
                excel_url = await asyncio.to_thread(
                    _upload_excel_to_gcs, excel_bytes, meta_excel.filename
                )
            except Exception as e:
                raise HTTPException(500, f"GCS upload error: {e}")

    # Per-table LLM enrichment (descriptions, classifications, units, age keys)
    def _enrich():
        return [extractor.enrich_for_catalogue(t) for t in tables]

    def _run(enriched_data):
        conn = _cat.get_connection()
        _cat.init_schema(conn)
        result = _cat.push_to_catalogue(
            conn, tables, enriched_data, metadata_mode, metadata_id,
            meta_title, meta_description, meta_product, meta_category,
            meta_geography, meta_frequency, meta_time_period,
            meta_data_source, meta_last_updated, meta_future_release,
            meta_key_statistics, meta_remarks, excel_url,
        )
        conn.close()
        return result

    try:
        enriched = await asyncio.to_thread(_enrich)
        result = await asyncio.to_thread(_run, enriched)
        return result
    except Exception as e:
        raise HTTPException(500, f"Push error: {e}")


# --- Serve React frontend (production) ---
_static_dir = pathlib.Path(__file__).parent / "static"
_assets_dir = _static_dir / "assets"
_index_html = _static_dir / "index.html"

if _assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if _index_html.exists():
        return FileResponse(str(_index_html))
    raise HTTPException(404, "Frontend not built. Run: cd frontend && npm run build")
