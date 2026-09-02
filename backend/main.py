import concurrent.futures
import os
import pathlib
import json as _json
import asyncio
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

import auth as _auth
from extractor import TableExtractor
import catalogue as _cat
from metadata_excel import parse_metadata_workbook, parse_concept_file
from metadata_llm import (
    METADATA_FIELDS,
    extract_excel_facts,
    generate_metadata_with_llm,
    parse_llm_metadata_output,
)
from catalogue_matching import match_tables_to_metadata
from table_export import table_to_excel_bytes
from original_sheet_export import extract_sheet_with_formatting_from_bytes
from validation import validate_table_fields_code, validate_table_fields_llm

app = FastAPI(title="Table Extractor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

LLM_KEY_HEADER = "x-llm-api-key"
LLM_PROVIDER_HEADER = "x-llm-provider"
_KNOWN_LLM_PROVIDERS = {"anthropic", "openai"}

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
    """Build a TableExtractor from the caller's own LLM API key (and chosen
    provider), sent on every LLM-backed request from the frontend's Settings
    screen. No key on the request means no LLM calls -- this replaces the old
    .env-based ANTHROPIC_API_KEY / SKIP_LLM toggle, which is no longer read."""
    key = request.headers.get(LLM_KEY_HEADER, "").strip() or None
    provider = request.headers.get(LLM_PROVIDER_HEADER, "").strip().lower() or None
    if provider not in _KNOWN_LLM_PROVIDERS:
        provider = None  # e.g. "self-hosted" or unset -- let extractor.py auto-detect
    return TableExtractor(api_key=key, skip_llm=not key, provider=provider)


def _validate_table_id_title(table: dict) -> None:
    """Runs the code-based and prompt-based Source Table ID / Table Title validators
    on one extracted table (mirrors the notebook's Stage 2.5) and annotates
    the table in place with the results plus a `id_title_mismatch` flag the
    frontend uses to decide which tables need manual reconciliation."""
    table_id = table.get("table_id", "")
    title = table.get("title", "")

    code_result = validate_table_fields_code(table_id, title)
    if not table_id.strip() and not title.strip():
        # Nothing to send the model -- both fields are already conclusively
        # invalid, so skip the LLM call rather than prompting it with two
        # empty strings.
        llm_result = {"valid": False, "issues": ["Source Table ID and Table Title are both missing"]}
    else:
        try:
            llm_result = validate_table_fields_llm(table_id, title)
        except Exception as e:
            llm_result = {"valid": None, "issues": [f"LLM validation skipped ({e})"]}

    # The regex/heuristic validator is deterministic and ground-truth for the
    # cases it checks (missing field, no "TABLE" marker, obvious swap), so it
    # is the source of truth for whether a table needs reconciliation. The
    # LLM validator can misfire on well-formed pairs (see validation.py); we
    # only let it force a mismatch when it flags a problem the code validator
    # doesn't already catch -- i.e. the code validator says valid, but the
    # LLM found an actual issue.
    mismatch = (not code_result["valid"]) or (
        code_result["valid"] and llm_result["valid"] is False and llm_result["issues"]
    )

    table["id_validation"] = {"code": code_result, "llm": llm_result}
    table["id_title_mismatch"] = mismatch


def _validate_tables(tables: list) -> None:
    """Runs `_validate_table_id_title` across all tables concurrently (each
    call makes a blocking LLM request) and annotates them in place."""
    if not tables:
        return
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(_validate_table_id_title, tables))


def _group_metadata_is_empty(metadata: Optional[dict]) -> bool:
    return not any((metadata or {}).get(f) for f in METADATA_FIELDS)


def _stringify_metadata_values(metadata: dict) -> dict:
    """The LLM can return a structured value for a field like `key_statistics`
    (see the notebook's own example output, a JSON object of headline
    numbers) -- normalize every field to a plain string so it renders safely
    in a text input/textarea on the frontend."""
    out = {}
    for field in METADATA_FIELDS:
        v = metadata.get(field)
        if v is None or v == "":
            out[field] = None
        elif isinstance(v, (dict, list)):
            out[field] = _json.dumps(v)
        else:
            out[field] = str(v)
    return out


def _fill_empty_group_metadata(
    groups: list, dataset_bytes_by_filename: dict, kyds_responses: Optional[dict], extractor: TableExtractor,
) -> bool:
    """Stage 4 -- LLM metadata creation per group (mirrors the notebook's
    `generate_metadata_per_group`). Only groups with no metadata (i.e. not
    matched to a row in an uploaded metadata workbook) are touched; groups
    that already carry values parsed from a metadata file are left as-is,
    per bullet 1 -- metadata-file entry stays the source of truth when the
    user provided one.

    Excel facts are derived once per source file (no LLM involved) and, as
    in the notebook, reused unchanged across every group from that file.
    KYDS responses come from Postgres (see catalogue.get_latest_kyds_responses)
    rather than a hardcoded payload.

    `extractor` supplies the LLM call, built from the caller's own Settings
    key/provider (see `_extractor_for`) rather than a server-side env var.

    Returns True when autofill was skipped specifically because no LLM key
    is configured (as opposed to there being nothing to fill) -- callers use
    this to tell the user why fields are still empty."""
    if not kyds_responses or not dataset_bytes_by_filename:
        return False

    has_fillable_group = any(
        _group_metadata_is_empty(g.get("metadata"))
        and g.get("matched_tables")
        and dataset_bytes_by_filename.get(g["matched_tables"][0]["table"].get("source_file"))
        for g in groups
    )
    if not has_fillable_group:
        return False
    if extractor.skip_llm:
        return True

    facts_cache: dict = {}

    for g in groups:
        if not _group_metadata_is_empty(g.get("metadata")):
            continue
        tables = [mt["table"] for mt in g.get("matched_tables", [])]
        if not tables:
            continue
        source_file = tables[0].get("source_file")
        content = dataset_bytes_by_filename.get(source_file)
        if not content:
            continue

        if source_file not in facts_cache:
            facts_cache[source_file] = extract_excel_facts(content, source_file)

        try:
            llm_output = generate_metadata_with_llm(
                facts_cache[source_file], kyds=kyds_responses, complete_fn=extractor._complete,
            )
            g["metadata"] = _stringify_metadata_values(parse_llm_metadata_output(llm_output))
        except Exception as e:
            print(f"Stage 4 LLM metadata generation failed for group {g.get('file_name')}: {e}")

    return False


def require_user(request: Request) -> str:
    """FastAPI dependency: verifies the bearer token and returns the email
    it carries. Every write-path route below depends on this so data is
    always stored under the authenticated caller, never a client-supplied
    value."""
    try:
        return _auth.email_from_request(request)
    except ValueError as e:
        raise HTTPException(401, str(e))


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


@app.post("/api/signup")
async def signup(request: Request):
    """Self-serve account creation. Enabled by default for dev — set
    ENABLE_SIGNUP=false to lock this down to admin-provisioned accounts
    only (see create_user.py) once this stops being a dev deployment."""
    if os.getenv("ENABLE_SIGNUP", "true").strip().lower() not in ("1", "true", "yes"):
        raise HTTPException(403, "Signup is disabled — ask an admin to create your account")

    data = await request.json()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    name = (data.get("name") or "").strip() or None
    dept = (data.get("dept") or "").strip() or None

    if not _auth.is_valid_org_email(email):
        raise HTTPException(400, "Email must be in name@organization.domain format")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")

    def _run():
        conn = _cat.get_connection()
        _cat.init_schema(conn)
        if _cat.get_user_by_email(conn, email):
            conn.close()
            return False
        _cat.create_user(conn, email, _auth.hash_password(password), name, dept)
        conn.close()
        return True

    try:
        created = await asyncio.to_thread(_run)
    except Exception as e:
        raise HTTPException(500, f"Signup error: {e}")

    if not created:
        raise HTTPException(409, "An account with that email already exists")

    token = _auth.create_token(email)
    return {"token": token, "email": email, "name": name, "dept": dept}


@app.post("/api/login")
async def login(request: Request):
    """Accounts are admin-provisioned only (see create_user.py) — this just
    verifies email/password and issues a bearer token."""
    data = await request.json()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not _auth.is_valid_org_email(email):
        raise HTTPException(400, "Email must be in name@organization.domain format")
    if not password:
        raise HTTPException(400, "Password is required")

    def _run():
        conn = _cat.get_connection()
        _cat.init_schema(conn)
        user = _cat.get_user_by_email(conn, email)
        conn.close()
        return user

    try:
        user = await asyncio.to_thread(_run)
    except Exception as e:
        raise HTTPException(500, f"Login error: {e}")

    if not user or not _auth.verify_password(password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")

    token = _auth.create_token(email)
    return {"token": token, "email": email, "name": user.get("name"), "dept": user.get("dept")}


@app.post("/api/table-metadata")
async def table_metadata(request: Request, user_email: str = Depends(require_user)):
    """LLM-based semantic category extraction from a table's raw structure."""
    data = await request.json()
    extractor = _extractor_for(request)
    try:
        categories = extractor.extract_category_metadata(
            title=data.get("table_id", ""),
            description=data.get("title", ""),
            raw_header_rows=data.get("raw_header_rows", []),
            columns=data.get("columns", []),
            sample_rows=data.get("sample_rows", []),
            raw_notes=data.get("raw_notes", []),
        )
    except Exception as e:
        raise HTTPException(500, f"Metadata extraction error: {e}")
    return {"categories": categories}



@app.post("/api/kyds")
async def save_kyds(request: Request, user_email: str = Depends(require_user)):
    """Store a KYDS (Know Your Dataset) form submission in Postgres, always
    attributed to the authenticated caller (never a client-supplied email)."""
    data = await request.json()
    responses = data.get("responses")
    if not isinstance(responses, dict):
        raise HTTPException(400, "responses must be an object")

    def _run():
        conn = _cat.get_connection()
        _cat.init_schema(conn)
        user_row = _cat.get_user_by_email(conn, user_email) or {}
        entry_id = _cat.save_kyds_entry(conn, responses, {
            "email": user_email,
            "name": user_row.get("name"),
            "dept": user_row.get("dept"),
        })
        conn.close()
        return entry_id

    try:
        entry_id = await asyncio.to_thread(_run)
    except Exception as e:
        raise HTTPException(500, f"KYDS save error: {e}")
    return {"id": entry_id, "status": "saved"}


@app.get("/api/kyds/mine")
async def get_my_kyds(user_email: str = Depends(require_user)):
    """Returns the authenticated caller's own most recent KYDS entry (or
    None), so the console can show it and offer an edit option."""
    def _run():
        conn = _cat.get_connection()
        _cat.init_schema(conn)
        entry = _cat.get_own_latest_kyds_entry(conn, user_email)
        conn.close()
        return entry

    try:
        entry = await asyncio.to_thread(_run)
    except Exception as e:
        raise HTTPException(500, f"KYDS fetch error: {e}")
    if entry and entry.get("created_at"):
        entry["created_at"] = entry["created_at"].isoformat()
    return {"entry": entry}


@app.post("/api/catalogue/parse-concept-file")
async def parse_concept_metadata_file(file: UploadFile = File(...), user_email: str = Depends(require_user)):
    """Reads an NMDS concept metadata file -- either a standalone CSV or a
    full metadata workbook's nmds_concept_meta_data sheet -- and returns the
    concept rows used to prefill the NMDS concept metadata step."""
    if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(400, "Only .xlsx / .xls / .csv files are supported")
    content = await file.read()
    try:
        concepts = await asyncio.to_thread(parse_concept_file, content, file.filename)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Failed to parse concept metadata file: {e}")
    return {"concepts": concepts}


@app.post("/api/catalogue/batch-extract")
async def batch_extract(request: Request, files: list[UploadFile] = File(...), user_email: str = Depends(require_user)):
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

    async def _extract_one(file_index: int, filename: str, content: bytes):
        try:
            tables = await asyncio.to_thread(extractor.extract_from_file, content, filename)
        except ValueError as e:
            raise HTTPException(400, f"{filename}: {e}")
        except Exception as e:
            raise HTTPException(500, f"Extraction error in {filename}: {e}")
        for i, t in enumerate(tables):
            t["source_file"] = filename
            # `id` is the catalog/DDI-style code derived from the table's own
            # content (TableExtractor._build_ddi_id) -- two physically
            # different tables (e.g. the same table title appearing in two
            # different uploaded workbooks) can legitimately end up with the
            # same `id`, which is fine for catalog matching but breaks the
            # frontend, which otherwise has nothing else to key preview tabs,
            # reconcile cards and edits on. `_uid` is a plain positional
            # identifier, unique within this batch regardless of content.
            t["_uid"] = f"{file_index}__{i}"
        try:
            await asyncio.to_thread(_attach_original_sheets, filename, content, tables)
        except Exception as e:
            # Non-fatal -- matching/review/push all still work without this,
            # datasets just fall back to the flat export on download.
            print(f"Original-sheet export failed for {filename}: {e}")
        return filename, tables

    results = await asyncio.gather(*(_extract_one(i, fn, ct) for i, (fn, ct) in enumerate(contents)))

    all_tables = []
    per_file = []
    for filename, tables in results:
        all_tables.extend(tables)
        per_file.append({"filename": filename, "table_count": len(tables)})
    await asyncio.to_thread(_validate_tables, all_tables)
    return {"tables": all_tables, "per_file": per_file, "table_count": len(all_tables)}


@app.post("/api/catalogue/batch-match")
async def batch_match(
    request: Request,
    tables_json: str = Form(...),
    metadata_files: list[UploadFile] = File(None),
    dataset_files: list[UploadFile] = File(None),
    user_email: str = Depends(require_user),
):
    """Parses multiple metadata workbooks and matches them against a set of
    already-extracted tables. Returns a proposed mapping for review --
    nothing is written to the database here. Metadata files are optional;
    when omitted (or when a dataset simply isn't described in any uploaded
    metadata workbook), that group's fields are auto-filled via Stage 4 LLM
    metadata generation instead of being left empty, provided the original
    dataset workbook was also sent (`dataset_files`) -- see
    `_fill_empty_group_metadata`. Uses the caller's own LLM key/provider from
    Settings (see `_extractor_for`); with no key configured, autofill is
    skipped and the response flags this via `llm_autofill_skipped_no_key` so
    the frontend can tell the user why fields are still empty."""
    extractor = _extractor_for(request)
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

    dataset_payloads = {}
    if dataset_files:
        for f in dataset_files:
            if f and f.filename:
                dataset_payloads[f.filename] = await f.read()

    def _run():
        workbooks = []
        for filename, content in metadata_payloads:
            try:
                workbooks.append(parse_metadata_workbook(content, filename))
            except ValueError as e:
                raise ValueError(f"{filename}: {e}")
        result = match_tables_to_metadata(tables, workbooks)
        result["llm_autofill_skipped_no_key"] = False

        if dataset_payloads:
            conn = _cat.get_connection()
            _cat.init_schema(conn)
            kyds_responses = _cat.get_latest_kyds_responses(conn, user_email)
            conn.close()
            result["llm_autofill_skipped_no_key"] = _fill_empty_group_metadata(
                result["groups"], dataset_payloads, kyds_responses, extractor,
            )

        return result

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
    nmds_concepts_json: Optional[str] = Form(None),
    user_email: str = Depends(require_user),
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
    nmds_concepts = _json.loads(nmds_concepts_json) if nmds_concepts_json else None

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
            "nmds_concepts": group.get("nmds_concepts") or nmds_concepts,
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
                    user_email,
                    p["nmds_concepts"],
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
