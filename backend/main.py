import concurrent.futures
import io
import os
import pathlib
import json as _json
import asyncio
import base64
import threading
import time
import uuid
import zipfile
import re
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
import psycopg2.extras

load_dotenv()

import auth as _auth
from extractor import TableExtractor
import catalogue as _cat
from metadata_excel import parse_metadata_workbook, parse_concept_file
from metadata_llm import (
    METADATA_FIELDS,
    SDG_METADATA_FIELDS,
    extract_excel_facts,
    extract_facts_from_tables,
    generate_metadata_with_llm,
    generate_sdg_metadata_with_llm,
    parse_llm_metadata_output,
    parse_llm_sdg_metadata_output,
)
from catalogue_matching import match_tables_to_metadata
from table_export import table_to_excel_bytes, safe_download_stem
from original_sheet_export import extract_sheet_with_formatting_from_bytes
from validation import (
    validate_table_fields_code,
    validate_table_fields_llm,
    repair_table_id_title_llm,
    _title_looks_like_headers,
)
from sql_extract import extract_tables_from_sql


def _title_looks_like_column_headers(title: str, columns: list) -> bool:
    """True when an extracted 'title' is really the header row joined together."""
    text = " ".join(str(title or "").split()).strip().upper()
    cols = [" ".join(str(c).split()).strip().upper() for c in (columns or []) if c is not None and str(c).strip()]
    if not text or len(cols) < 2:
        return False
    joined = " ".join(cols)
    if text == joined:
        return True
    # Header-like if most leading column names appear as tokens in the title.
    hits = sum(1 for c in cols[: min(6, len(cols))] if c and c in text)
    return hits >= min(3, len(cols))


def _catalogue_table_title(table: dict, inventory_item: Optional[dict] = None) -> str:
    """Prefer a real descriptive title over mis-extracted column-header text."""
    inv_title = str((inventory_item or {}).get("short_description") or "").strip()
    title = str(table.get("title") or "").strip()
    table_id = str(table.get("table_id") or "").strip()
    columns = table.get("columns") or []

    if title and not _title_looks_like_column_headers(title, columns):
        return title
    if inv_title:
        return inv_title
    if table_id and not _title_looks_like_column_headers(table_id, columns):
        return table_id
    return title or inv_title or table_id or str(table.get("id") or "")


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


def _title_context_rows_for(table: dict) -> list:
    context = list(table.get("title_context_rows") or [])
    if context:
        return context
    for row in (table.get("raw_header_rows") or [])[:4]:
        if isinstance(row, (list, tuple)):
            text = " ".join(str(c).strip() for c in row if c is not None and str(c).strip())
        else:
            text = str(row or "").strip()
        if text:
            context.append(text)
    return context


def _apply_llm_id_title_repair(table: dict, table_id: str, title: str) -> tuple:
    """Apply LLM repair patches; returns (table_id, title, code_result)."""
    repaired = repair_table_id_title_llm(
        table_id,
        title,
        context_rows=_title_context_rows_for(table),
        columns=table.get("columns") or [],
    )
    if not repaired:
        return table_id, title, validate_table_fields_code(table_id, title)

    if repaired.get("table_id") and repaired["table_id"] != (table_id or "").strip():
        table["table_id"] = repaired["table_id"]
        table_id = table["table_id"]
        table["table_id_repaired_by_llm"] = True
    if repaired.get("title") and repaired["title"] != (title or "").strip():
        table["title"] = repaired["title"]
        title = table["title"]
        table["title_repaired_by_llm"] = True
    return table_id, title, validate_table_fields_code(table_id, title)


def _validate_table_id_title(table: dict) -> None:
    """Runs the code-based and prompt-based Source Table ID / Table Title validators
    on one extracted table (mirrors the notebook's Stage 2.5) and annotates
    the table in place with the results plus a `id_title_mismatch` flag the
    frontend uses to decide which tables need manual reconciliation.

    When the LLM auto-fills or corrects either field, sets
    ``table_id_repaired_by_llm`` / ``title_repaired_by_llm`` so Preview can
    highlight them for human review.
    """
    table_id = table.get("table_id", "")
    title = table.get("title", "")

    code_result = validate_table_fields_code(table_id, title)
    needs_repair = (
        (not (title or "").strip())
        or (not (table_id or "").strip())
        or _title_looks_like_headers(title, table.get("columns") or [])
        or any("swap" in str(i).lower() for i in (code_result.get("issues") or []))
        or any("title" in str(i).lower() and "missing" in str(i).lower() for i in (code_result.get("issues") or []))
        or any("table id" in str(i).lower() and "missing" in str(i).lower() for i in (code_result.get("issues") or []))
    )

    if needs_repair:
        table_id, title, code_result = _apply_llm_id_title_repair(table, table_id, title)

    if not str(table_id or "").strip() and not str(title or "").strip():
        # Nothing to send the model -- both fields are already conclusively
        # invalid, so skip the LLM call rather than prompting it with two
        # empty strings.
        llm_result = {"valid": False, "issues": ["Source Table ID and Table Title are both missing"]}
    else:
        try:
            llm_result = validate_table_fields_llm(table_id, title)
        except Exception as e:
            llm_result = {"valid": None, "issues": [f"LLM validation skipped ({e})"]}

    # If validation still says id/title is wrong, ask the model for a fix once.
    llm_field_issue = any(
        any(k in str(i).lower() for k in ("title", "table id", "swap", "header", "sl.no", "description", "missing"))
        for i in (llm_result.get("issues") or [])
    )
    already_repaired = table.get("title_repaired_by_llm") or table.get("table_id_repaired_by_llm")
    if (
        not already_repaired
        and llm_result.get("valid") is False
        and llm_field_issue
    ):
        table_id, title, code_result = _apply_llm_id_title_repair(table, table_id, title)
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


def _group_metadata_is_empty(metadata: Optional[dict], fields: Optional[list] = None) -> bool:
    keys = fields if fields is not None else METADATA_FIELDS
    return not any((metadata or {}).get(f) for f in keys)


def _stringify_field_values(metadata: dict, fields: list) -> dict:
    """Normalize LLM field values to plain strings for form inputs."""
    out = {}
    for field in fields:
        v = metadata.get(field)
        if v is None or v == "":
            out[field] = None
        elif isinstance(v, (dict, list)):
            out[field] = _json.dumps(v)
        else:
            out[field] = str(v)
    return out


def _stringify_metadata_values(metadata: dict) -> dict:
    """The LLM can return a structured value for a field like `key_statistics`
    (see the notebook's own example output, a JSON object of headline
    numbers) -- normalize every field to a plain string so it renders safely
    in a text input/textarea on the frontend."""
    return _stringify_field_values(metadata, METADATA_FIELDS)


def _stringify_sdg_metadata_values(metadata: dict) -> dict:
    return _stringify_field_values(metadata, SDG_METADATA_FIELDS)


def _fill_empty_group_metadata(
    groups: list,
    dataset_bytes_by_filename: dict,
    kyds_responses: Optional[dict],
    extractor: TableExtractor,
    standard: str = "nmds",
) -> tuple[bool, list[dict]]:
    """Stage 4 -- LLM metadata creation per group (mirrors the notebook's
    `generate_metadata_per_group`). Only groups with no metadata (i.e. not
    matched to a row in an uploaded metadata workbook) are touched; groups
    that already carry values parsed from a metadata file are left as-is,
    per bullet 1 -- metadata-file entry stays the source of truth when the
    user provided one.

    When `standard` is `sdg`, fills UN SDG indicator fields instead of the
    catalogue sheet fields. Catalogue values are still produced when possible
    and stored on `catalogue_metadata` for push/display compatibility.

    Facts come from either:
      - uploaded Excel workbook bytes (`dataset_bytes_by_filename` + extract_excel_facts), or
      - already-extracted in-memory tables (SQL / any source without workbook bytes)
        via extract_facts_from_tables.
    KYDS responses come from Postgres (see catalogue.get_latest_kyds_responses).

    `extractor` supplies the LLM call, built from the caller's own Settings
    key/provider (see `_extractor_for`) rather than a server-side env var.

    Returns `(skipped_no_key, errors)` where `errors` lists per-group failures
    as `{group, error}` so the UI can explain why fields are still empty and
    let the user fill them in manually.
    """
    if not kyds_responses:
        return False, []

    use_sdg = str(standard or "nmds").lower() == "sdg"

    def _group_tables(g: dict) -> list:
        matched = [mt["table"] for mt in g.get("matched_tables", []) if mt.get("table")]
        if matched:
            return matched
        # PDF grouping shape uses a flat `tables` list until the client
        # normalizes to matched_tables for BatchReview / batch-push.
        return [t for t in (g.get("tables") or []) if isinstance(t, dict)]

    def _is_empty(g: dict) -> bool:
        if use_sdg:
            # Prefer dedicated concept blob when present; otherwise treat
            # metadata keyed by SDG labels as the fill target.
            concept_meta = g.get("concept_metadata")
            if isinstance(concept_meta, dict) and concept_meta:
                return _group_metadata_is_empty(concept_meta, SDG_METADATA_FIELDS)
            return _group_metadata_is_empty(g.get("metadata"), SDG_METADATA_FIELDS)
        return _group_metadata_is_empty(g.get("metadata"), METADATA_FIELDS)

    has_fillable_group = any(_is_empty(g) and _group_tables(g) for g in groups)
    if not has_fillable_group:
        return False, []
    if extractor.skip_llm:
        return True, []

    facts_cache: dict = {}
    errors: list[dict] = []

    for gi, g in enumerate(groups):
        if not _is_empty(g):
            continue
        tables = _group_tables(g)
        if not tables:
            continue
        group_label = g.get("file_name") or g.get("name") or "Untitled group"
        source_file = tables[0].get("source_file") or group_label or "extracted"
        content = (dataset_bytes_by_filename or {}).get(source_file)

        try:
            if content:
                if source_file not in facts_cache:
                    facts_cache[source_file] = extract_excel_facts(content, source_file)
                facts = facts_cache[source_file]
            else:
                cache_key = f"tables::{source_file}::{g.get('file_name')}"
                if cache_key not in facts_cache:
                    facts_cache[cache_key] = extract_facts_from_tables(tables, source_file)
                facts = facts_cache[cache_key]

            if use_sdg:
                llm_output = generate_sdg_metadata_with_llm(
                    facts, kyds=kyds_responses, complete_fn=extractor._complete,
                )
                sdg_meta = _stringify_sdg_metadata_values(parse_llm_sdg_metadata_output(llm_output))
                g["concept_metadata"] = sdg_meta
                # Drive the metadata page grid from SDG fields when that
                # standard is selected; keep any prior catalogue values aside.
                prior = g.get("metadata") or {}
                if any(prior.get(f) for f in METADATA_FIELDS):
                    g["catalogue_metadata"] = {
                        f: prior.get(f) for f in METADATA_FIELDS if prior.get(f)
                    }
                g["metadata"] = sdg_meta
            else:
                llm_output = generate_metadata_with_llm(
                    facts, kyds=kyds_responses, complete_fn=extractor._complete,
                )
                g["metadata"] = _stringify_metadata_values(parse_llm_metadata_output(llm_output))
            # Keep a display name when the client sent PDF-style groups.
            if not g.get("file_name") and g.get("name"):
                g["file_name"] = g["name"]
        except Exception as e:
            msg = str(e).strip() or e.__class__.__name__
            print(f"Stage 4 LLM metadata generation failed for group {group_label}: {msg}")
            errors.append({"index": gi, "group": group_label, "error": msg})

    return False, errors


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
    out = {"status": "ok", "pgvector": False}
    try:
        import vector_store as _vs
        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            out["pgvector"] = _vs.vector_extension_ready(conn)
            out["embedding_dim"] = _vs.embedding_dim()
        finally:
            conn.close()
    except Exception as exc:
        out["pgvector_error"] = str(exc)
    return out


@app.get("/api/me")
async def me(user_email: str = Depends(require_user)):
    """Validate the current session and return the signed-in profile.
    Used on app boot so a stale localStorage token after a backend restart
    clears the client session and returns the user to login."""
    def _run():
        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            return _cat.get_user_by_email(conn, user_email)
        finally:
            conn.close()

    user = await asyncio.to_thread(_run)
    if not user:
        raise HTTPException(401, "Account not found — please sign in again")
    return {
        "email": user["email"],
        "name": user.get("name") or user["email"],
        "dept": user.get("dept") or "",
    }

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
    """Reads a concept metadata file (NMDS or SDG) — CSV or workbook sheet —
    and returns concept rows used to prefill the concept metadata step."""
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

    # Stage full tables server-side so batch-push can send slim refs only
    # (avoids Starlette's 1MB multipart part limit on groups_json).
    import extract_staging as _staging

    batch_id = _staging.new_batch_id()

    def _stage():
        conn = _cat.get_connection()
        try:
            return _staging.save_staging_tables(conn, batch_id, all_tables, user_email)
        finally:
            conn.close()

    await asyncio.to_thread(_stage)
    return {
        "tables": all_tables,
        "per_file": per_file,
        "table_count": len(all_tables),
        "batch_id": batch_id,
    }


@app.post("/api/catalogue/sql-extract")
async def sql_extract(request: Request, user_email: str = Depends(require_user)):
    """Connect to a user-supplied Postgres database and return Excel-shaped
    tables for batch-match → review → publish.

    Body (JSON):
      database_url?  OR  host + database + user (+ password?, port?, sslmode?)
      query?         optional — if omitted, auto-extract:
                       DHARA catalogue DBs expand datasets from dataset_rows;
                       otherwise every user table/view is extracted
      title?, table_id?  (used only when query is provided)
      row_limit?, max_tables?
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Expected a JSON body")
    if not isinstance(body, dict):
        raise HTTPException(400, "Expected a JSON object")

    query = body.get("query")
    query = str(query).strip() if query is not None and str(query).strip() else None

    def _run():
        return extract_tables_from_sql(
            query=query,
            database_url=body.get("database_url"),
            host=body.get("host"),
            port=body.get("port"),
            database=body.get("database"),
            user=body.get("user"),
            password=body.get("password"),
            sslmode=body.get("sslmode"),
            title=body.get("title"),
            table_id=body.get("table_id"),
            row_limit=body.get("row_limit") or None,
            max_tables=body.get("max_tables") or None,
        )

    try:
        tables = await asyncio.to_thread(_run)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"SQL extraction error: {e}")

    source = (tables[0].get("source_file") if tables else None) or "SQL database"
    if query:
        mode = "query"
    elif tables and any(t.get("sheet") == "catalogue" for t in tables):
        mode = "catalogue"
    else:
        mode = "auto"

    import extract_staging as _staging

    batch_id = _staging.new_batch_id()

    def _stage():
        conn = _cat.get_connection()
        try:
            return _staging.save_staging_tables(conn, batch_id, tables, user_email)
        finally:
            conn.close()

    await asyncio.to_thread(_stage)
    return {
        "tables": tables,
        "per_file": [{"filename": source, "table_count": len(tables)}],
        "table_count": len(tables),
        "mode": mode,
        "batch_id": batch_id,
    }


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
    nothing is written to the database here. Metadata files are optional.

    Stage 4 LLM metadata autofill (KYDS + table/Excel facts) runs later,
    after the user finishes grouping — see `/api/catalogue/fill-group-metadata`.
    `dataset_files` is accepted for backwards compatibility but no longer
    triggers autofill here."""
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
        result = match_tables_to_metadata(tables, workbooks)
        result["llm_autofill_skipped_no_key"] = False
        return result

    try:
        result = await asyncio.to_thread(_run)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Matching error: {e}")
    return result


@app.post("/api/catalogue/fill-group-metadata")
async def fill_group_metadata(request: Request, user_email: str = Depends(require_user)):
    """Stage 4 — after grouping is confirmed, fill empty catalogue metadata
    on each group from KYDS + in-memory table facts (and optional Excel
    workbook bytes if the client still has them).

    Body (JSON):
      groups (required) — same shape as batch-match `groups`
      standard? — `nmds` (default) or `sdg` for SDG indicator fields
      dataset_files_b64? — optional { filename: base64 } map of workbook bytes
    """
    extractor = _extractor_for(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Expected a JSON body")
    if not isinstance(body, dict):
        raise HTTPException(400, "Expected a JSON object")

    groups = body.get("groups")
    if not isinstance(groups, list):
        raise HTTPException(400, "groups must be a list")

    standard = str(body.get("standard") or "nmds").lower()
    if standard not in ("nmds", "sdg"):
        standard = "nmds"
    use_sdg = standard == "sdg"

    dataset_payloads: dict = {}
    raw_files = body.get("dataset_files_b64") or {}
    if isinstance(raw_files, dict):
        for filename, b64 in raw_files.items():
            if not filename or not b64:
                continue
            try:
                dataset_payloads[str(filename)] = base64.b64decode(b64)
            except Exception:
                raise HTTPException(400, f"Invalid base64 for dataset file {filename}")

    def _run():
        # Deep-ish copy so we don't mutate the request body unexpectedly if
        # the same object is reused; groups contain nested table dicts.
        filled = _json.loads(_json.dumps(groups))
        conn = _cat.get_connection()
        _cat.init_schema(conn)
        kyds_responses = _cat.get_latest_kyds_responses(conn, user_email)
        conn.close()
        skipped, errors = _fill_empty_group_metadata(
            filled, dataset_payloads, kyds_responses, extractor, standard=standard,
        )
        return filled, skipped, bool(kyds_responses), errors

    try:
        filled_groups, skipped_no_key, has_kyds, autofill_errors = await asyncio.to_thread(_run)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Metadata fill error: {e}")

    fill_fields = SDG_METADATA_FIELDS if use_sdg else METADATA_FIELDS

    # Return a lightweight patch — not the full groups with embedded table
    # rows — so a single failed LLM call can't blow up the response and the
    # client can merge successful metadata onto the groups it already has.
    group_metadata = [
        {
            "index": i,
            "file_name": g.get("file_name") or g.get("name"),
            "metadata": g.get("metadata") or {},
            "concept_metadata": g.get("concept_metadata") or {},
            "catalogue_metadata": g.get("catalogue_metadata") or {},
            "filled": not _group_metadata_is_empty(
                g.get("concept_metadata") if use_sdg and g.get("concept_metadata") else g.get("metadata"),
                fill_fields,
            ),
        }
        for i, g in enumerate(filled_groups)
    ]

    return {
        "group_metadata": group_metadata,
        "standard": standard,
        # Back-compat: still include groups, but strip bulky row payloads so
        # partial success survives large SQL catalogue extracts.
        "groups": [
            {
                **{k: v for k, v in g.items() if k not in ("matched_tables", "tables")},
                "matched_tables": [
                    {
                        **mt,
                        "table": {
                            **{
                                tk: tv
                                for tk, tv in (mt.get("table") or {}).items()
                                if tk != "rows"
                            },
                            "rows": [],
                            "row_count": (mt.get("table") or {}).get("row_count"),
                        },
                    }
                    for mt in (g.get("matched_tables") or [])
                ],
            }
            for g in filled_groups
        ],
        "llm_autofill_skipped_no_key": skipped_no_key,
        "kyds_missing": not has_kyds,
        "autofill_errors": autofill_errors,
        "autofill_failed_count": len(autofill_errors),
        "autofill_filled_count": sum(1 for item in group_metadata if item["filled"]),
    }


@app.post("/api/catalogue/batch-push")
async def batch_push(
    request: Request,
    groups_json: str = Form(...),
    metadata_files: list[UploadFile] = File(None),
    tables_blob: Optional[UploadFile] = File(None),
    nmds_concepts_json: Optional[str] = Form(None),
    batch_id: Optional[str] = Form(None),
    pdf_job_id: Optional[str] = Form(None),
    user_email: str = Depends(require_user),
):
    """Pushes a reviewed/confirmed batch mapping to the catalogue -- one
    metadata group + its matched tables per entry in `groups_json`.

    `groups_json` should carry slim table refs (ids + steward overlays). Full
    row payloads are loaded from extract_staging (`batch_id`), pdf_store
    (`pdf_job_id`), or an optional `tables_blob` JSON file upload (used for
    sessions extracted before staging existed). Legacy clients that still
    embed full `rows` in groups_json continue to work.

    Two phases, deliberately kept separate: (1) slow work -- per-table LLM
    enrichment and optional GCS uploads, parallelized -- happens BEFORE any
    database connection is opened, and (2) fast DB writes happen only once
    everything is ready. Doing this in one phase with a connection held open
    for the whole thing caused Neon to drop the (idle, minutes-long)
    connection before it could commit. GCS is skipped unless ENABLE_GCS=true."""
    groups = _json.loads(groups_json)
    extractor = _extractor_for(request)
    nmds_concepts = _json.loads(nmds_concepts_json) if nmds_concepts_json else None
    batch_id = (batch_id or "").strip() or None
    pdf_job_id = (pdf_job_id or "").strip() or None

    metadata_by_index = {}
    if metadata_files:
        for i, f in enumerate(metadata_files):
            if f and f.filename:
                metadata_by_index[i] = (f.filename, await f.read())

    blob_by_uid: dict = {}
    if tables_blob and tables_blob.filename:
        try:
            raw_blob = await tables_blob.read()
            parsed_blob = _json.loads(raw_blob.decode("utf-8"))
            if isinstance(parsed_blob, dict):
                blob_by_uid = {
                    str(k): v for k, v in parsed_blob.items() if isinstance(v, dict)
                }
        except Exception as e:
            raise HTTPException(400, f"Invalid tables_blob: {e}")

    def _load_sources():
        staged: dict = {}
        pdf_tables: dict = {}
        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            if batch_id:
                import extract_staging as _staging
                staged = _staging.load_staging_tables(conn, batch_id)
            if pdf_job_id:
                import pdf_store as _pdf_store
                for t in _pdf_store.list_active_tables(conn, pdf_job_id):
                    tid = str(t.get("id") or "")
                    if tid:
                        pdf_tables[tid] = t
                        # MatchResult also keys PDF tables by _uid === id.
                        pdf_tables[str(t.get("_uid") or tid)] = t
        finally:
            conn.close()
        return staged, pdf_tables

    staged_by_uid, pdf_by_id = await asyncio.to_thread(_load_sources)

    _OVERLAY_KEYS = (
        "_uid", "id", "table_id", "title", "sheet", "source_file", "source_type",
        "original_excel_url", "source_excel_url",
    )

    def _hydrate_table(raw: dict) -> dict:
        """Merge slim overlay onto staged/pdf/blob/full payload table."""
        raw = raw if isinstance(raw, dict) else {}
        uid = str(raw.get("_uid") or raw.get("id") or "").strip()
        full = None
        if uid and uid in staged_by_uid:
            full = dict(staged_by_uid[uid])
        elif uid and uid in pdf_by_id:
            full = dict(pdf_by_id[uid])
        elif uid and uid in blob_by_uid:
            full = dict(blob_by_uid[uid])
        elif raw.get("rows") is not None or raw.get("source_rows") is not None:
            # Legacy: client still sent the full table inside groups_json.
            full = dict(raw)
        if full is None:
            raise ValueError(
                f"Missing staged table for uid={uid or '(empty)'}. "
                "Re-run extract/preview so tables are stored before push."
            )
        for key in _OVERLAY_KEYS:
            if raw.get(key) not in (None, ""):
                full[key] = raw[key]
        if not full.get("_uid") and uid:
            full["_uid"] = uid
        return full

    def _prep_table(t):
        # Preserve the extractor's own clean table structure as a
        # downloadable single-sheet Excel per dataset, so a download
        # reflects what was actually cataloged rather than a re-flattened
        # reconstruction from the DB rows.
        xlsx_bytes = table_to_excel_bytes(t)
        t["source_excel_url"] = _upload_table_excel_to_gcs(xlsx_bytes, t.get("id", ""))
        return t, extractor.enrich_for_catalogue(t)

    def _prepare_group(group):
        tables = []
        for mt in group.get("matched_tables", []):
            raw = mt.get("table") or {}
            t = _hydrate_table(raw)
            t["title"] = _catalogue_table_title(t, mt.get("inventory_item"))
            tables.append(t)
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
            "real_classifications": group.get("classifications") or {},
            "catalogue_placement": group.get("catalogue_placement") or {},
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
                    p.get("real_classifications"),
                    p.get("catalogue_placement"),
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


@app.get("/api/catalogue/datasets")
async def list_catalogue_datasets(user_email: str = Depends(require_user)):
    """Published datasets for the Catalogue page."""
    def _run():
        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            return _cat.list_catalogue_datasets(conn)
        finally:
            conn.close()

    datasets = await asyncio.to_thread(_run)
    return {"datasets": datasets}


def _pdf_dashboard_row(
    job: Dict[str, Any],
    grouping_status: Optional[str] = None,
    pipeline_step: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Map a PDF extraction job into a Dashboard readiness row.

    Console steps: 1 Files → 2 Preview → 3 Grouping → 4 Metadata → 5 Classify → 6 Publish.
    Returns None when the job should be represented by catalogue rows instead
    (metadata already pushed / classify+).
    """
    job_id = job.get("job_id") or ""
    name = (job.get("filename") or "PDF upload").rsplit("/", 1)[-1]
    status = str(job.get("status") or "")
    percent = int(job.get("percent") or 0)
    needs_review = int(job.get("needs_review_count") or 0)
    table_count = int(job.get("table_count") or 0)
    gs = (grouping_status or "").strip().lower()
    step = pipeline_step if pipeline_step is not None else job.get("pipeline_step")
    try:
        step = int(step) if step is not None else None
    except (TypeError, ValueError):
        step = None

    base = {
        "id": f"pdf:{job_id}",
        "kind": "pdf_job",
        "name": name,
        "source": "PDF",
        "product": "—",
        "job_id": job_id,
        "updated_at": job.get("created_at") or job.get("updated_at"),
    }

    if status in ("queued", "running"):
        # Step 1 — extraction in progress (cap below Preview).
        return {
            **base,
            "readiness_pct": max(5, min(int(round(percent * 0.2)), 20)),
            "status": "Processing",
            "status_key": "processing",
            "action": "View",
            "href": f"/console/processing/{job_id}",
            "pipeline_step": 1,
        }
    if status == "error":
        return {
            **base,
            "readiness_pct": max(5, min(percent, 20)),
            "status": "Failed",
            "status_key": "failed",
            "action": "View",
            "href": f"/console/processing/{job_id}",
            "pipeline_step": 1,
        }

    # Infer step when not explicitly stored (older jobs).
    if step is None:
        if gs == "saved":
            step = 4  # grouping finished → Metadata
        elif grouping_status is not None:
            step = 3  # persisted tables, grouping in progress
        else:
            step = 2  # extraction done, Preview
    elif gs == "saved" and step < 4:
        # Grouping Continue always advances into Metadata.
        step = 4

    # After Metadata push the catalogue rows are the accurate readiness view.
    if step >= 5:
        return None

    if step >= 4:
        return {
            **base,
            "readiness_pct": 67,
            "status": "Metadata review",
            "status_key": "metadata_review",
            "action": "Review",
            "href": f"/console/grouping/{job_id}",
            "pipeline_step": 4,
        }
    if step >= 3:
        return {
            **base,
            "readiness_pct": 50,
            "status": "Harmonisation",
            "status_key": "harmonisation",
            "action": "Review",
            "href": f"/console/grouping/{job_id}",
            "pipeline_step": 3,
        }

    # Step 2 — Preview / table review
    if table_count > 0:
        cleared = max(0, table_count - needs_review)
        pct = int(round(25 + (cleared / table_count) * 10))  # 25–35%
    else:
        pct = 30
    label = "Table review" if needs_review > 0 else "Preview"
    return {
        **base,
        "readiness_pct": pct,
        "status": label,
        "status_key": "table_review",
        "action": "Review",
        "href": f"/console/review/{job_id}",
        "pipeline_step": 2,
    }


@app.patch("/api/pdf/jobs/{job_id}/pipeline")
async def pdf_set_pipeline_step(job_id: str, request: Request, user_email: str = Depends(require_user)):
    """Persist console pipeline step for dashboard readiness (steps 3–6)."""
    import pdf_store

    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be a JSON object")
    try:
        step = int(body.get("step"))
    except (TypeError, ValueError):
        raise HTTPException(400, "step must be an integer 1–6")
    if step < 1 or step > 6:
        raise HTTPException(400, "step must be an integer 1–6")

    def _run():
        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            pdf_store.init_pdf_schema(conn)
            job_row = pdf_store.get_job(conn, job_id)
            if not job_row or job_row.get("user_email") != user_email:
                with _pdf_jobs_lock:
                    mem = _get_pdf_job(job_id)
                if not mem or mem.get("user_email") != user_email:
                    return None
                pdf_store.upsert_job(
                    conn,
                    job_id=job_id,
                    user_email=user_email,
                    filename=mem.get("filename"),
                    status=mem.get("status") or "done",
                )
            pdf_store.set_pipeline_step(conn, job_id, step)
            return pdf_store.get_pipeline_step(conn, job_id)
        finally:
            conn.close()

    try:
        saved = await asyncio.to_thread(_run)
    except Exception as e:
        raise HTTPException(500, f"Could not save pipeline step: {e}")
    if saved is None:
        raise HTTPException(404, "Job not found")

    with _pdf_jobs_lock:
        job = _get_pdf_job(job_id)
        if job is not None:
            job["pipeline_step"] = saved

    return {"ok": True, "job_id": job_id, "pipeline_step": saved}


@app.get("/api/dashboard")
async def get_dashboard(user_email: str = Depends(require_user)):
    """Dataset readiness for the Dashboard: catalogue groups + in-flight PDF jobs."""
    import pdf_store

    def _run():
        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            pdf_store.init_pdf_schema(conn)
            base = _cat.list_dashboard(conn, user_email)
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT job_id, filename, status, grouping_status, pipeline_step,
                           created_at, updated_at
                    FROM pdf_jobs
                    WHERE user_email = %s
                    ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
                    """,
                    (user_email,),
                )
                pdf_db = {r["job_id"]: dict(r) for r in cur.fetchall()}
        finally:
            conn.close()
        return base, pdf_db

    base, pdf_db = await asyncio.to_thread(_run)

    with _pdf_jobs_lock:
        _hydrate_user_pdf_jobs(user_email)
        json_jobs = [
            _pdf_job_public(j)
            for j in _pdf_jobs.values()
            if j.get("user_email") == user_email
        ]

    seen = set()
    pdf_rows = []
    for job in json_jobs:
        jid = job.get("job_id")
        if not jid:
            continue
        seen.add(jid)
        db = pdf_db.get(jid) or {}
        step = db.get("pipeline_step")
        if step is None:
            step = job.get("pipeline_step")
        row = _pdf_dashboard_row(job, db.get("grouping_status"), step)
        if row:
            pdf_rows.append(row)

    for jid, db in pdf_db.items():
        if jid in seen:
            continue
        row = _pdf_dashboard_row({
            "job_id": jid,
            "filename": db.get("filename"),
            "status": db.get("status") or "done",
            "percent": 100,
            "created_at": db.get("updated_at") or db.get("created_at"),
            "needs_review_count": 0,
            "pipeline_step": db.get("pipeline_step"),
        }, db.get("grouping_status"), db.get("pipeline_step"))
        if row:
            pdf_rows.append(row)

    awaiting_extra = sum(
        1 for r in pdf_rows
        if r.get("status_key") not in ("failed", "published")
    )

    rows = list(pdf_rows) + list(base.get("rows") or [])
    stats = dict(base.get("stats") or {})
    stats["awaiting_review"] = int(stats.get("awaiting_review") or 0) + awaiting_extra
    stats["datasets"] = int(stats.get("datasets") or 0) + len(pdf_rows)

    def _sort_key(r):
        u = r.get("updated_at")
        if isinstance(u, (int, float)):
            return float(u)
        if hasattr(u, "timestamp"):
            try:
                return float(u.timestamp())
            except Exception:
                return 0.0
        if isinstance(u, str):
            try:
                from datetime import datetime
                return datetime.fromisoformat(u.replace("Z", "+00:00")).timestamp()
            except Exception:
                return 0.0
        return 0.0

    rows.sort(key=_sort_key, reverse=True)
    return {"stats": stats, "rows": rows}


@app.get("/api/catalogue/metadata-groups/{metadata_id}/classifications")
async def get_classifications(metadata_id: str, user_email: str = Depends(require_user)):
    """Classification columns + code lists for the Classify step."""
    def _run():
        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            return _cat.get_metadata_group_classifications(conn, metadata_id)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()

    try:
        columns = await asyncio.to_thread(_run)
    except Exception as e:
        raise HTTPException(500, f"Failed to load classifications: {e}")
    if columns is None:
        raise HTTPException(404, f"No metadata group found for {metadata_id}")
    return {"columns": columns}


@app.get("/api/catalogue/classifications/recent")
async def get_recent_classifications(user_email: str = Depends(require_user)):
    """Classified columns from this user's most recent metadata groups —
    used when Classify has no metadataIds in session (e.g. refresh)."""
    def _run():
        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            return _cat.get_recent_classification_columns(conn, user_email)
        finally:
            conn.close()

    columns = await asyncio.to_thread(_run)
    return {"columns": columns}


@app.patch("/api/catalogue/metadata-groups/{metadata_id}/classifications")
async def update_classification_column(metadata_id: str, request: Request, user_email: str = Depends(require_user)):
    """Persist edited code/definition rows for one classification column,
    or several alias columns that share the same categorical values."""
    data = await request.json()
    column_name = data.get("column_name")
    column_names = data.get("column_names")
    codes = data.get("codes")
    if codes is None or (not column_name and not column_names):
        raise HTTPException(400, "column_name (or column_names) and codes are required")

    def _run():
        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            return _cat.update_metadata_group_classification_column(
                conn, metadata_id, column_name, codes, column_names=column_names,
                expand_aliases=data.get("expand_aliases", True),
            )
        finally:
            conn.close()

    ok = await asyncio.to_thread(_run)
    if not ok:
        raise HTTPException(404, f"No metadata group found for {metadata_id}")
    return {"status": "ok"}


@app.post("/api/catalogue/fill-definitions")
async def fill_definitions(request: Request, user_email: str = Depends(require_user)):
    """Fill classification definitions from values + catalogue/excel facts.
    Occupation columns are skipped (NCO matching owns those)."""
    import re as _re
    from metadata_llm import fill_classification_definitions

    data = await request.json()
    columns = data.get("columns") or []
    if not isinstance(columns, list):
        raise HTTPException(400, "columns must be a list")
    extractor = _extractor_for(request)
    if extractor.skip_llm:
        raise HTTPException(400, "Configure an LLM key in Settings to fill definitions.")

    def _run():
        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            out = {}
            facts_by_id = {}
            for col in columns:
                name = (col.get("name") or "").strip()
                if not name or _re.search(r"occupat", name, _re.I):
                    continue
                values = [str(v) for v in (col.get("values") or []) if v is not None and str(v).strip()]
                if not values:
                    continue
                mid = col.get("metadata_id")
                if mid not in facts_by_id:
                    facts_by_id[mid] = _cat.get_definition_facts(conn, mid)
                try:
                    out[name] = fill_classification_definitions(
                        extractor._complete, name, values, facts_by_id[mid],
                    )
                except Exception:
                    out[name] = {}
            return out
        finally:
            conn.close()

    definitions = await asyncio.to_thread(_run)
    return {"definitions": definitions}


@app.post("/api/catalogue/match-nco")
async def match_nco(request: Request, user_email: str = Depends(require_user)):
    """Suggest the coarsest fitting NCO 2015 level (division, subdivision, or family).
    Does not return specific .xxxx job codes."""
    import nco_matching as _nco
    data = await request.json()
    values = data.get("values") or []
    if not isinstance(values, list):
        raise HTTPException(400, "values must be a list of strings")
    unique = []
    for v in values:
        s = str(v).strip() if v is not None else ""
        if s and s not in unique:
            unique.append(s)
    extractor = _extractor_for(request)

    def _run():
        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            _cat.seed_nco_2015(conn)
            return _nco.match_occupations(conn, unique, extractor=extractor)
        finally:
            conn.close()

    matches = await asyncio.to_thread(_run)
    return {"matches": matches, "llm_used": not extractor.skip_llm}


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


# --- PDF extraction/classification pipeline (upload -> background job -> review) ---
#
# Unlike the xlsx batch-extract flow above, this can take several minutes
# (pymupdf extraction + batched OpenAI reconstruction/classification -- see
# sda_india_pdf_extraction.py), far longer than a synchronous request should
# block for. Jobs are cached in memory for live progress and persisted to
# Postgres (pdf_store) — never under backend/data/. Pipeline runs use ephemeral
# temp files that are deleted when extraction finishes.
import tempfile

import sda_india_pdf_extraction as _pdf_pipeline
import pdf_store as _pdf_store

_pdf_jobs: Dict[str, Dict[str, Any]] = {}
_pdf_jobs_lock = threading.Lock()


def _pdf_db_conn():
    conn = _cat.get_connection()
    _cat.init_schema(conn)
    _pdf_store.init_pdf_schema(conn)
    return conn


def _save_pdf_job(
    job: Dict[str, Any],
    *,
    pdf_bytes: Optional[bytes] = None,
    clear_pdf_bytes: bool = False,
) -> None:
    """Persist working job state to Postgres (best-effort)."""
    try:
        conn = _pdf_db_conn()
        try:
            _pdf_store.save_working_job(
                conn, job, pdf_bytes=pdf_bytes, clear_pdf_bytes=clear_pdf_bytes,
            )
        finally:
            conn.close()
    except Exception as e:
        print(f"Warning: could not persist PDF job {job.get('job_id')}: {e}", flush=True)


def _load_pdf_job(job_id: str) -> Optional[Dict[str, Any]]:
    try:
        conn = _pdf_db_conn()
        try:
            return _pdf_store.load_working_job(conn, job_id)
        finally:
            conn.close()
    except Exception as e:
        print(f"Warning: could not load PDF job {job_id}: {e}", flush=True)
        return None


def _list_pdf_jobs_for_user(user_email: str) -> List[Dict[str, Any]]:
    try:
        conn = _pdf_db_conn()
        try:
            return _pdf_store.list_working_jobs(conn, user_email)
        finally:
            conn.close()
    except Exception as e:
        print(f"Warning: could not list PDF jobs: {e}", flush=True)
        return []


def _get_pdf_bytes(job_id: str) -> Optional[bytes]:
    try:
        conn = _pdf_db_conn()
        try:
            return _pdf_store.get_pdf_bytes(conn, job_id)
        finally:
            conn.close()
    except Exception as e:
        print(f"Warning: could not load PDF bytes for {job_id}: {e}", flush=True)
        return None


def _get_pdf_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Prefer in-memory job; fall back to Postgres after a process restart."""
    job = _pdf_jobs.get(job_id)
    if job is not None:
        return job
    job = _load_pdf_job(job_id)
    if job is not None:
        _pdf_jobs[job_id] = job
    return job


def _hydrate_user_pdf_jobs(user_email: str) -> None:
    """Ensure this user's Postgres jobs are present in the in-memory cache."""
    for job in _list_pdf_jobs_for_user(user_email):
        jid = job.get("job_id")
        if not jid:
            continue
        # Prefer live in-memory progress over a stale DB snapshot.
        if jid not in _pdf_jobs:
            _pdf_jobs[jid] = job


def _pdf_job_public(job: Dict[str, Any]) -> Dict[str, Any]:
    """Status view of a job -- everything except the (potentially large)
    result payload, which has its own endpoint."""
    public = {
        k: v for k, v in job.items()
        if k not in ("result", "reviews", "deleted_table_ids", "pdf_bytes")
    }
    if job.get("status") == "done" and job.get("result") is not None:
        deleted = set(job.get("deleted_table_ids") or [])
        tables = []
        for page_num, page in job["result"].items():
            for idx, t in enumerate(page.get("tables", [])):
                table_id = f"{page_num}-{idx}"
                if table_id not in deleted:
                    tables.append(t)
        public["table_count"] = len(tables)
        public["needs_review_count"] = sum(1 for t in tables if t.get("human_review_needed"))
    return public


def _run_pdf_job(job_id: str, pdf_bytes: bytes, api_key: Optional[str]) -> None:
    """Runs synchronously (called via asyncio.to_thread from the upload
    endpoint) -- this thread just blocks for the pipeline's duration while
    the event loop keeps serving other requests, including this job's own
    status-polling requests from the frontend.

    Writes an ephemeral tempfile for pymupdf (deleted in finally); durable
    state is Postgres only.
    """
    last_flush = {"stage": None, "bucket": -1}

    def on_progress(stage: str, percent: int, message: str) -> None:
        with _pdf_jobs_lock:
            job = _pdf_jobs.get(job_id)
            if job is not None:
                job.update(status="running", stage=stage, percent=percent, message=message)
                bucket = int(percent) // 10
                if stage != last_flush["stage"] or bucket != last_flush["bucket"]:
                    last_flush["stage"] = stage
                    last_flush["bucket"] = bucket
                    _save_pdf_job(job)

    tmp_path: Optional[pathlib.Path] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = pathlib.Path(tmp.name)
        result = _pdf_pipeline.run_pipeline(tmp_path, on_progress=on_progress, api_key=api_key)
        with _pdf_jobs_lock:
            job = _pdf_jobs.get(job_id)
            if job is not None:
                job.update(status="done", stage="done", percent=100, message="Complete", result=result)
                # Keep source PDF bytes in Postgres for review snapshots.
                _save_pdf_job(job, pdf_bytes=pdf_bytes)
    except Exception as e:
        print(f"PDF job {job_id} failed: {e}")
        with _pdf_jobs_lock:
            job = _pdf_jobs.get(job_id)
            if job is not None:
                job.update(status="error", message=f"Failed: {e}", error=str(e))
                _save_pdf_job(job, clear_pdf_bytes=True)
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass


@app.post("/api/pdf/upload")
async def pdf_upload(request: Request, file: UploadFile = File(...), user_email: str = Depends(require_user)):
    """Accepts one PDF, stores working state in Postgres, and starts background
    processing without blocking the response — returns a job_id immediately for
    the frontend to poll via GET /api/pdf/jobs/{job_id}."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only .pdf files are supported")

    content = await file.read()
    if not content:
        raise HTTPException(400, "Uploaded file is empty")

    job_id = uuid.uuid4().hex

    # Same per-request LLM key convention as the rest of the app (see
    # _extractor_for) -- falls back to the server's OPENAI_API_KEY env var
    # (openai.OpenAI(api_key=None)) when the caller hasn't configured one.
    api_key = request.headers.get(LLM_KEY_HEADER, "").strip() or None

    with _pdf_jobs_lock:
        _pdf_jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "stage": "queued",
            "percent": 0,
            "message": "Queued",
            "filename": file.filename,
            "user_email": user_email,
            "created_at": time.time(),
            "result": None,
            "error": None,
            "reviews": {},
            "deleted_table_ids": [],
        }
        _save_pdf_job(_pdf_jobs[job_id], pdf_bytes=content)

    asyncio.create_task(asyncio.to_thread(_run_pdf_job, job_id, content, api_key))
    return {"job_id": job_id}


@app.get("/api/pdf/jobs")
async def pdf_jobs_list(user_email: str = Depends(require_user)):
    """Lists the caller's own PDF jobs, most recent first -- lets the
    frontend recover an in-progress/finished job after a page refresh."""
    with _pdf_jobs_lock:
        _hydrate_user_pdf_jobs(user_email)
        mine = [_pdf_job_public(j) for j in _pdf_jobs.values() if j.get("user_email") == user_email]
    mine.sort(key=lambda j: j.get("created_at") or 0, reverse=True)
    return {"jobs": mine}


@app.get("/api/pdf/jobs/{job_id}")
async def pdf_job_status(job_id: str, user_email: str = Depends(require_user)):
    with _pdf_jobs_lock:
        job = _get_pdf_job(job_id)
        if not job or job.get("user_email") != user_email:
            raise HTTPException(404, "Job not found")
        return _pdf_job_public(job)


@app.get("/api/pdf/jobs/{job_id}/result")
async def pdf_job_result(job_id: str, user_email: str = Depends(require_user)):
    """Flattens the pipeline's page-keyed output into one list of tables for
    the review screen, each tagged with a stable table_id ("{page}-{index}")
    and merged with any reviewer edits already saved via the PATCH endpoint
    below. Table data (rows) is never modified by review -- only
    classification/human_review_* fields are ever patched."""
    with _pdf_jobs_lock:
        job = _get_pdf_job(job_id)
        if not job or job.get("user_email") != user_email:
            raise HTTPException(404, "Job not found. Please upload the PDF again.")
        if job["status"] != "done":
            raise HTTPException(409, f"Job not finished yet (status={job['status']})")
        reviews = dict(job.get("reviews") or {})
        deleted = set(job.get("deleted_table_ids") or [])
        result = job["result"] or {}
        filename = job["filename"]

    tables = []
    for page_num in sorted(result.keys(), key=lambda k: int(k) if str(k).isdigit() else str(k)):
        for idx, t in enumerate(result[page_num].get("tables", [])):
            table_id = f"{page_num}-{idx}"
            if table_id in deleted:
                continue
            merged = {**t, **reviews.get(table_id, {}), "table_id": table_id}
            tables.append(merged)
    return {"job_id": job_id, "filename": filename, "tables": tables}


@app.patch("/api/pdf/jobs/{job_id}/tables/{table_id}")
async def pdf_review_table(job_id: str, table_id: str, request: Request, user_email: str = Depends(require_user)):
    """Saves a reviewer's edits to one table (classification, columns, rows,
    structure). Merged onto the original table when /result is next fetched."""
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(400, "Body must be a JSON object")
    with _pdf_jobs_lock:
        job = _get_pdf_job(job_id)
        if not job or job.get("user_email") != user_email:
            raise HTTPException(404, "Job not found")
        job.setdefault("reviews", {})[table_id] = {**job["reviews"].get(table_id, {}), **payload}
        _save_pdf_job(job)
    return {"ok": True}


@app.get("/api/pdf/jobs/{job_id}/tables/{table_id}/snapshot")
async def pdf_table_snapshot(job_id: str, table_id: str, user_email: str = Depends(require_user)):
    """PNG crop of the source PDF region for this table (or the full page).

    Used in review so humans can compare the extracted grid against the page.
    Source PDF bytes are loaded from Postgres (not local disk).
    """
    import pymupdf

    with _pdf_jobs_lock:
        job = _get_pdf_job(job_id)
        if not job or job.get("user_email") != user_email:
            raise HTTPException(404, "Job not found")
        if job.get("status") != "done":
            raise HTTPException(409, f"Job not finished yet (status={job.get('status')})")
        reviews = dict(job.get("reviews") or {})
        deleted = set(job.get("deleted_table_ids") or [])
        result = job.get("result") or {}

    if table_id in deleted:
        raise HTTPException(404, "Table was deleted")

    try:
        page_s, idx = _parse_pdf_table_id(table_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    page_key = page_s if page_s in result else (int(page_s) if page_s.isdigit() and int(page_s) in result else None)
    if page_key is None and page_s.isdigit():
        # result keys may be ints or strings
        for k in result:
            if str(k) == page_s:
                page_key = k
                break
    if page_key is None:
        raise HTTPException(404, "Page not found in job result")

    page_tables = (result.get(page_key) or {}).get("tables") or []
    if idx < 0 or idx >= len(page_tables):
        raise HTTPException(404, "Table not found")
    table = {**page_tables[idx], **reviews.get(table_id, {})}

    pdf_bytes = await asyncio.to_thread(_get_pdf_bytes, job_id)
    if not pdf_bytes:
        raise HTTPException(
            404,
            "Source PDF is no longer available for snapshots (re-upload the file to enable comparison).",
        )

    page_num = int(table.get("page") or page_s)
    bbox = table.get("bbox")
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        try:
            if page_num < 1 or page_num > doc.page_count:
                raise HTTPException(404, f"Page {page_num} out of range")
            page = doc[page_num - 1]
            clip = None
            if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                x0, y0, x1, y1 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
                # Pad slightly so captions above the ruled grid stay visible.
                pad = 8.0
                clip = pymupdf.Rect(
                    max(0, x0 - pad),
                    max(0, y0 - pad),
                    min(page.rect.x1, x1 + pad),
                    min(page.rect.y1, y1 + pad),
                )
            pix = page.get_pixmap(clip=clip, dpi=144, alpha=False)
            png = pix.tobytes("png")
        finally:
            doc.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Could not render snapshot: {e}") from e

    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )


@app.post("/api/pdf/jobs/{job_id}/tables/delete")
async def pdf_delete_tables(job_id: str, request: Request, user_email: str = Depends(require_user)):
    """Soft-deletes one or more extracted tables from a finished job.
    table_id values stay stable (page-index), so deletions are recorded in
    deleted_table_ids rather than reshuffling the result payload."""
    payload = await request.json()
    table_ids = payload.get("table_ids") if isinstance(payload, dict) else None
    if not isinstance(table_ids, list) or not table_ids:
        raise HTTPException(400, "Body must include a non-empty table_ids array")
    ids = [str(tid) for tid in table_ids if tid is not None and str(tid).strip()]
    if not ids:
        raise HTTPException(400, "No valid table_ids provided")

    with _pdf_jobs_lock:
        job = _get_pdf_job(job_id)
        if not job or job.get("user_email") != user_email:
            raise HTTPException(404, "Job not found")
        if job["status"] != "done":
            raise HTTPException(409, f"Job not finished yet (status={job['status']})")
        deleted = set(job.get("deleted_table_ids") or [])
        deleted.update(ids)
        job["deleted_table_ids"] = sorted(deleted)
        reviews = job.get("reviews") or {}
        for tid in ids:
            reviews.pop(tid, None)
        job["reviews"] = reviews
        _save_pdf_job(job)
    return {"ok": True, "deleted": ids, "deleted_count": len(ids)}


def _normalize_pdf_header_name(name: Any) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip().lower())


def _pdf_table_header_key(table: Dict[str, Any]) -> str:
    """Stable fingerprint of column headers for cross-page merge eligibility."""
    names: List[str] = []
    for col in table.get("columns") or []:
        if isinstance(col, dict):
            names.append(_normalize_pdf_header_name(col.get("name")))
        else:
            names.append(_normalize_pdf_header_name(col))
    return "|".join(names)


def _parse_pdf_table_id(table_id: str) -> Tuple[str, int]:
    parts = str(table_id).rsplit("-", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        raise ValueError(f"Invalid table_id: {table_id}")
    return parts[0], int(parts[1])


def _pdf_table_sort_key(table_id: str) -> Tuple[Any, int]:
    page_s, idx = _parse_pdf_table_id(table_id)
    page_key: Any = int(page_s) if page_s.isdigit() else page_s
    return page_key, idx


@app.post("/api/pdf/jobs/{job_id}/tables/merge")
async def pdf_merge_tables(job_id: str, request: Request, user_email: str = Depends(require_user)):
    """
    Concatenate rows from 2+ Preview tables that share the same column headers
    (cross-page continuations of one logical table). Keeps the earliest table
    as survivor, soft-deletes the rest. Does not change extraction prompts.
    """
    payload = await request.json()
    table_ids = payload.get("table_ids") if isinstance(payload, dict) else None
    if not isinstance(table_ids, list) or len(table_ids) < 2:
        raise HTTPException(400, "Body must include table_ids with at least 2 ids")
    ids = [str(tid) for tid in table_ids if tid is not None and str(tid).strip()]
    # Preserve order but unique
    seen = set()
    ordered_ids: List[str] = []
    for tid in ids:
        if tid not in seen:
            seen.add(tid)
            ordered_ids.append(tid)
    if len(ordered_ids) < 2:
        raise HTTPException(400, "Select at least two distinct tables to merge")

    with _pdf_jobs_lock:
        job = _get_pdf_job(job_id)
        if not job or job.get("user_email") != user_email:
            raise HTTPException(404, "Job not found")
        if job["status"] != "done":
            raise HTTPException(409, f"Job not finished yet (status={job['status']})")

        approved = {str(t["table_id"]): t for t in _pdf_tables_from_job(job)}
        missing = [tid for tid in ordered_ids if tid not in approved]
        if missing:
            raise HTTPException(404, f"Table(s) not found or deleted: {', '.join(missing)}")

        selected = [approved[tid] for tid in ordered_ids]
        selected.sort(key=lambda t: _pdf_table_sort_key(str(t["table_id"])))

        header_keys = {_pdf_table_header_key(t) for t in selected}
        if len(header_keys) != 1 or not next(iter(header_keys)):
            raise HTTPException(
                400,
                "Can only merge tables that share the same column headers",
            )

        survivor = selected[0]
        survivors_id = str(survivor["table_id"])
        merge_ids = [str(t["table_id"]) for t in selected[1:]]

        # Concatenate rows in page order (already sorted).
        merged_rows: List[Any] = []
        for t in selected:
            rows = t.get("rows") or []
            if isinstance(rows, list):
                merged_rows.extend(rows)

        try:
            page_s, idx = _parse_pdf_table_id(survivors_id)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

        result = job.setdefault("result", {})
        page_entry = result.get(page_s)
        if page_entry is None and page_s.isdigit():
            page_entry = result.get(int(page_s))
        if page_entry is None:
            raise HTTPException(404, f"Survivor page {page_s} missing from job result")

        tables_list = page_entry.get("tables") or []
        if idx < 0 or idx >= len(tables_list):
            raise HTTPException(404, f"Survivor table {survivors_id} missing from job result")

        raw = tables_list[idx]
        raw["rows"] = merged_rows
        # Keep survivor columns; note provenance for Preview / debugging.
        pages = []
        for t in selected:
            p = t.get("page")
            if p is not None and p not in pages:
                pages.append(p)
        raw["merged_from_table_ids"] = [survivors_id, *merge_ids]
        raw["merged_pages"] = pages
        if pages:
            # Prefer an existing title; annotate page span when helpful.
            title = (raw.get("title") or survivor.get("title") or "").strip()
            if title and len(pages) > 1:
                if "page" not in title.lower():
                    raw["title"] = f"{title} (pages {pages[0]}–{pages[-1]})"
            elif not title and len(pages) > 1:
                raw["title"] = f"Merged table (pages {pages[0]}–{pages[-1]})"

        deleted = set(job.get("deleted_table_ids") or [])
        deleted.update(merge_ids)
        job["deleted_table_ids"] = sorted(deleted)

        reviews = job.get("reviews") or {}
        for tid in merge_ids:
            reviews.pop(tid, None)
        # Drop stale row-affecting review fields on survivor; keep classification edits.
        if survivors_id in reviews:
            reviews[survivors_id] = {
                k: v for k, v in reviews[survivors_id].items() if k not in ("rows",)
            }
            if raw.get("title"):
                reviews[survivors_id]["title"] = raw["title"]
        job["reviews"] = reviews
        _save_pdf_job(job)

        # Return survivor as Preview would see it after merge.
        out_tables = _pdf_tables_from_job(job)
        survivor_out = next((t for t in out_tables if str(t.get("table_id")) == survivors_id), None)

    return {
        "ok": True,
        "survivor_table_id": survivors_id,
        "merged_table_ids": merge_ids,
        "row_count": len(merged_rows),
        "table": survivor_out,
    }


def _pdf_merged_tables_for_job(job: Dict[str, Any]) -> list:
    """Approved (non-deleted) tables with review patches applied."""
    return _pdf_tables_from_job(job)


@app.get("/api/pdf/jobs/{job_id}/tables/{table_id}/download")
async def pdf_download_table(job_id: str, table_id: str, user_email: str = Depends(require_user)):
    """Download one extracted PDF table as a clean .xlsx workbook."""
    with _pdf_jobs_lock:
        job = _get_pdf_job(job_id)
        if not job or job.get("user_email") != user_email:
            raise HTTPException(404, "Job not found")
        if job["status"] != "done":
            raise HTTPException(409, f"Job not finished yet (status={job['status']})")
        tables = _pdf_merged_tables_for_job(job)

    table = next((t for t in tables if str(t.get("table_id")) == str(table_id)), None)
    if not table:
        raise HTTPException(404, "Table not found (it may have been deleted)")

    xlsx = table_to_excel_bytes(table)
    stem = safe_download_stem(table, fallback=f"table_{table_id}")
    filename = f"{stem}.xlsx"
    return Response(
        content=xlsx,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _pdf_tables_zip_bytes(tables: list, job_name: str, job_id: str) -> tuple[bytes, str]:
    """Build a ZIP of .xlsx files; returns (zip_bytes, download_filename)."""
    buf = io.BytesIO()
    used_names: set = set()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for t in tables:
            tid = str(t.get("table_id") or "table")
            stem = safe_download_stem(t, fallback=f"table_{tid}")
            name = f"{stem}.xlsx"
            if name in used_names:
                name = f"{stem}_{tid}.xlsx"
            used_names.add(name)
            zf.writestr(name, table_to_excel_bytes(t))
    zip_stem = safe_download_stem({"title": pathlib.Path(str(job_name)).stem}, fallback=job_id)
    return buf.getvalue(), f"{zip_stem}_tables.zip"


@app.get("/api/pdf/jobs/{job_id}/tables/download-zip")
async def pdf_download_tables_zip(job_id: str, user_email: str = Depends(require_user)):
    """Download all non-deleted tables for a PDF job as a .zip of .xlsx files."""
    with _pdf_jobs_lock:
        job = _get_pdf_job(job_id)
        if not job or job.get("user_email") != user_email:
            raise HTTPException(404, "Job not found")
        if job["status"] != "done":
            raise HTTPException(409, f"Job not finished yet (status={job['status']})")
        tables = _pdf_merged_tables_for_job(job)
        job_name = job.get("filename") or job_id

    if not tables:
        raise HTTPException(404, "No tables to download")

    payload, filename = _pdf_tables_zip_bytes(tables, job_name, job_id)
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/pdf/jobs/{job_id}/tables/download-zip")
async def pdf_download_tables_zip_selected(
    job_id: str, request: Request, user_email: str = Depends(require_user)
):
    """Download selected tables as a ZIP. Body: { table_ids: string[] }.
    If table_ids is omitted or empty, downloads all non-deleted tables."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    raw_ids = body.get("table_ids") if isinstance(body, dict) else None
    id_filter = None
    if isinstance(raw_ids, list) and raw_ids:
        id_filter = {str(tid) for tid in raw_ids if tid is not None and str(tid).strip()}

    with _pdf_jobs_lock:
        job = _get_pdf_job(job_id)
        if not job or job.get("user_email") != user_email:
            raise HTTPException(404, "Job not found")
        if job["status"] != "done":
            raise HTTPException(409, f"Job not finished yet (status={job['status']})")
        tables = _pdf_merged_tables_for_job(job)
        job_name = job.get("filename") or job_id

    if id_filter is not None:
        tables = [t for t in tables if str(t.get("table_id")) in id_filter]
    if not tables:
        raise HTTPException(404, "No matching tables to download")

    payload, filename = _pdf_tables_zip_bytes(tables, job_name, job_id)
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _pdf_tables_from_job(job: Dict[str, Any]) -> list:
    """Flatten JSON job result + reviews into the approved table list."""
    reviews = dict(job.get("reviews") or {})
    deleted = set(job.get("deleted_table_ids") or [])
    result = job.get("result") or {}
    tables = []
    for page_num in sorted(result.keys(), key=lambda k: int(k) if str(k).isdigit() else str(k)):
        for idx, t in enumerate(result[page_num].get("tables", [])):
            table_id = f"{page_num}-{idx}"
            if table_id in deleted:
                continue
            merged = {**t, **reviews.get(table_id, {}), "table_id": table_id, "page": t.get("page", page_num)}
            tables.append(merged)
    return tables


@app.post("/api/pdf/jobs/{job_id}/persist-approved")
async def pdf_persist_approved(job_id: str, request: Request, user_email: str = Depends(require_user)):
    """
    Continue from Preview: write approved tables to Postgres and propose
    title-based groups (same base-title rule as Excel; SDG jobs by goal).

    Optional JSON body `{ "tables": [ { table_id, title, rows, columns, … } ] }`
    overlays the in-memory job reviews so Preview edits that haven't been
    PATCHed yet (or failed silently) still reach grouping.
    """
    import pdf_store
    import pdf_grouping

    api_key = request.headers.get(LLM_KEY_HEADER, "").strip() or None
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    with _pdf_jobs_lock:
        job = _get_pdf_job(job_id)
        if not job or job.get("user_email") != user_email:
            raise HTTPException(404, "Job not found")
        if job["status"] != "done":
            raise HTTPException(409, f"Job not finished yet (status={job['status']})")
        tables = _pdf_tables_from_job(job)
        filename = job.get("filename")

        # Overlay client Preview state (titles etc.) onto job tables + reviews.
        client_tables = body.get("tables")
        if isinstance(client_tables, list) and client_tables:
            by_id = {
                str(t.get("table_id")): t
                for t in client_tables
                if isinstance(t, dict) and t.get("table_id")
            }
            overlay_keys = (
                "title",
                "rows",
                "columns",
                "classification",
                "human_review_needed",
                "human_review_reason",
                "semantic_status",
            )
            reviews = dict(job.get("reviews") or {})
            for t in tables:
                tid = str(t.get("table_id") or "")
                override = by_id.get(tid)
                if not override:
                    continue
                patch = {k: override[k] for k in overlay_keys if k in override}
                t.update(patch)
                reviews[tid] = {**reviews.get(tid, {}), **patch}
            job["reviews"] = reviews
            _save_pdf_job(job)

    conn = _cat.get_connection()
    try:
        _cat.init_schema(conn)
        persisted = pdf_store.persist_approved_tables(
            conn,
            job_id=job_id,
            user_email=user_email,
            filename=filename,
            tables=tables,
        )
        proposal = pdf_grouping.propose_groups(conn, job_id, api_key=api_key, reindex=True)
        grouping = pdf_grouping.apply_proposal_to_db(conn, job_id, proposal)
        return {
            "ok": True,
            "job_id": job_id,
            "table_count": len(persisted),
            "grouping": grouping,
        }
    finally:
        conn.close()


@app.get("/api/pdf/jobs/{job_id}/grouping")
async def pdf_get_grouping(job_id: str, user_email: str = Depends(require_user)):
    import pdf_store

    conn = _cat.get_connection()
    try:
        _cat.init_schema(conn)
        job_row = pdf_store.get_job(conn, job_id)
        if not job_row or job_row.get("user_email") != user_email:
            # Fall back: allow read if JSON job exists and belongs to user (not yet persisted)
            with _pdf_jobs_lock:
                job = _get_pdf_job(job_id)
            if not job or job.get("user_email") != user_email:
                raise HTTPException(404, "Job not found — continue from Preview to persist tables first.")
            raise HTTPException(409, "Tables not persisted yet — click Continue on Preview.")
        grouping = pdf_store.load_grouping(conn, job_id)
        tables = pdf_store.list_active_tables(conn, job_id)
        return {
            "job_id": job_id,
            "filename": job_row.get("filename"),
            "grouping_status": job_row.get("grouping_status"),
            "table_count": len(tables),
            **grouping,
        }
    finally:
        conn.close()


@app.post("/api/pdf/jobs/{job_id}/grouping/propose")
async def pdf_propose_grouping(job_id: str, request: Request, user_email: str = Depends(require_user)):
    """Re-run automatic title-based grouping and overwrite saved groups."""
    import pdf_store
    import pdf_grouping

    api_key = request.headers.get(LLM_KEY_HEADER, "").strip() or None
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    reindex = bool(body.get("reindex")) if isinstance(body, dict) else False

    conn = _cat.get_connection()
    try:
        _cat.init_schema(conn)
        job_row = pdf_store.get_job(conn, job_id)
        if not job_row or job_row.get("user_email") != user_email:
            raise HTTPException(404, "Job not found — continue from Preview first.")
        proposal = pdf_grouping.propose_groups(conn, job_id, api_key=api_key, reindex=reindex)
        grouping = pdf_grouping.apply_proposal_to_db(conn, job_id, proposal)
        return {"ok": True, "job_id": job_id, **grouping}
    finally:
        conn.close()


@app.put("/api/pdf/jobs/{job_id}/grouping")
async def pdf_save_grouping(job_id: str, request: Request, user_email: str = Depends(require_user)):
    """Persist human-edited groups. Body: { groups: [{ name, table_ids: [uuid...] }] }."""
    import pdf_store

    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(400, "Body must be a JSON object")
    groups_in = payload.get("groups")
    if not isinstance(groups_in, list):
        raise HTTPException(400, "groups must be an array")

    conn = _cat.get_connection()
    try:
        _cat.init_schema(conn)
        job_row = pdf_store.get_job(conn, job_id)
        if not job_row or job_row.get("user_email") != user_email:
            raise HTTPException(404, "Job not found")
        active = {t["id"] for t in pdf_store.list_active_tables(conn, job_id)}
        normalized = []
        for g in groups_in:
            if not isinstance(g, dict):
                continue
            name = (g.get("name") or "").strip() or "Untitled group"
            raw_ids = g.get("table_pks") or g.get("table_ids") or []
            pks = [str(x) for x in raw_ids if str(x) in active]
            if pks:
                normalized.append({"name": name, "table_pks": pks})
        pdf_store.save_grouping(conn, job_id=job_id, groups=normalized)
        return {"ok": True, **pdf_store.load_grouping(conn, job_id)}
    finally:
        conn.close()


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
