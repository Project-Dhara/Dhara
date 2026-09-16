"""Excel/SQL extraction, matching, metadata autofill, catalogue push, and
classification/NCO routes."""
import asyncio
import base64
import concurrent.futures
import json as _json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from catalogue import catalogue as _cat
from catalogue.catalogue_matching import match_tables_to_metadata
from core.deps import _extractor_for, require_user
from core.gcs_utils import _upload_excel_to_gcs, _upload_original_sheet_to_gcs, _upload_table_excel_to_gcs
from metadata.metadata_excel import parse_metadata_workbook, parse_concept_file
from metadata.metadata_fill import (
    METADATA_FIELDS,
    SDG_METADATA_FIELDS,
    _fill_empty_group_metadata,
    _group_metadata_is_empty,
)
from extraction.original_sheet_export import extract_sheet_with_formatting_from_bytes
from extraction.sql_extract import extract_tables_from_sql
from extraction.table_export import table_to_excel_bytes
from metadata.table_id_title import _catalogue_table_title, _validate_tables

router = APIRouter(tags=["Catalogue"])


@router.post("/api/table-metadata")
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


@router.post("/api/catalogue/parse-concept-file")
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


@router.post("/api/catalogue/batch-extract")
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
    from catalogue import extract_staging as _staging

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


@router.post("/api/catalogue/sql-extract")
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

    from catalogue import extract_staging as _staging

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


@router.post("/api/catalogue/batch-match")
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


@router.post("/api/catalogue/fill-group-metadata")
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


@router.post("/api/catalogue/batch-push")
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
                from catalogue import extract_staging as _staging
                staged = _staging.load_staging_tables(conn, batch_id)
            if pdf_job_id:
                from pdf import pdf_store as _pdf_store
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


@router.get("/api/catalogue/datasets")
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


@router.get("/api/catalogue/metadata-groups/{metadata_id}/classifications")
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


@router.get("/api/catalogue/classifications/recent")
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


@router.patch("/api/catalogue/metadata-groups/{metadata_id}/classifications")
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


@router.post("/api/catalogue/fill-definitions")
async def fill_definitions(request: Request, user_email: str = Depends(require_user)):
    """Fill classification definitions from values + catalogue/excel facts.
    Occupation columns are skipped (NCO matching owns those)."""
    import re as _re
    from metadata.metadata_llm import fill_classification_definitions

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


@router.get("/api/catalogue/classification-standards")
async def get_classification_standards(user_email: str = Depends(require_user)):
    """List steward-uploaded classification concordance standards."""

    def _run():
        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            return _cat.list_classification_standards(conn)
        finally:
            conn.close()

    standards = await asyncio.to_thread(_run)
    return {"standards": standards}


@router.post("/api/catalogue/classification-standards")
async def upload_classification_standard(
    name: str = Form(...),
    file: UploadFile = File(...),
    description: str = Form(""),
    select: str = Form("true"),
    user_email: str = Depends(require_user),
):
    """Upload a concordance CSV, name it, and optionally select it for Classify."""
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty file")
    fname = file.filename or "concordance.csv"
    if not fname.lower().endswith(".csv"):
        raise HTTPException(400, "Upload a .csv file in the NCO concordance column layout")
    do_select = str(select).strip().lower() not in ("0", "false", "no")

    def _run():
        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            return _cat.create_classification_standard(
                conn,
                name=name,
                csv_bytes=raw,
                original_filename=fname,
                description=description or None,
                uploaded_by=user_email,
                select=do_select,
            )
        finally:
            conn.close()

    try:
        standard = await asyncio.to_thread(_run)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Failed to store classification standard: {e}")
    return {"standard": standard}


@router.post("/api/catalogue/classification-standards/{standard_id}/select")
async def select_classification_standard_route(
    standard_id: int,
    user_email: str = Depends(require_user),
):
    """Make this uploaded standard the active source for occupation matching."""

    def _run():
        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            return _cat.select_classification_standard(conn, standard_id)
        finally:
            conn.close()

    try:
        result = await asyncio.to_thread(_run)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


@router.delete("/api/catalogue/classification-standards/{standard_id}")
async def delete_classification_standard_route(
    standard_id: int,
    user_email: str = Depends(require_user),
):
    def _run():
        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            return _cat.delete_classification_standard(conn, standard_id)
        finally:
            conn.close()

    try:
        result = await asyncio.to_thread(_run)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


@router.post("/api/catalogue/match-nco")
async def match_nco(request: Request, user_email: str = Depends(require_user)):
    """Suggest the coarsest fitting NCO 2015 level (division, subdivision, or family).
    Does not return specific .xxxx job codes. Dynamic: alias → embed/fuzzy → LLM.
    Codes come from the classification standard selected in Settings."""
    from catalogue import nco_matching as _nco
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
            _cat.ensure_classification_standard_loaded(conn)
            return _nco.match_occupations(conn, unique, extractor=extractor)
        finally:
            conn.close()

    matches = await asyncio.to_thread(_run)
    return {"matches": matches, "llm_used": not extractor.skip_llm}


@router.post("/api/catalogue/nco-aliases")
async def save_nco_aliases(request: Request, user_email: str = Depends(require_user)):
    """Learn occupation → NCO mappings from steward Verify in Classify."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Expected a JSON body")
    aliases = data.get("aliases") if isinstance(data, dict) else None
    if not isinstance(aliases, list):
        raise HTTPException(400, "aliases must be a list")

    def _run():
        conn = _cat.get_connection()
        try:
            _cat.init_schema(conn)
            return _cat.upsert_nco_aliases(conn, aliases, source="steward")
        finally:
            conn.close()

    saved = await asyncio.to_thread(_run)
    return {"saved": saved}
