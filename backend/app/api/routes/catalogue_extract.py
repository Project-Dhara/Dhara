"""Excel/SQL extraction, matching, metadata autofill, catalogue push, and
classification/NCO routes."""
import asyncio
import base64
import concurrent.futures
import json as _json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from app.api.dependencies import (
    CurrentUser,
    _extractor_for,
    require_user,
    require_user_email,
    resolve_llm_credentials,
)
from app.core.permissions import MUTATING_ROLES, READ_ROLES, require_roles
from app.db.repositories import kyds as kyds_repo
from app.db.repositories import pdf_jobs as pdf_jobs_repo
from app.db.session import dbapi_connection, session_scope
from app.services.catalogue.group_export import build_group_download_zip
from app.services.catalogue.query import (
    get_catalogue_group as query_catalogue_group,
    list_catalogue_datasets as query_catalogue_datasets,
    list_catalogue_groups as query_catalogue_groups,
)
from app.services.classification.classifications import (
    get_definition_facts,
    get_metadata_group_classifications,
    get_recent_classification_columns,
    update_metadata_group_classification_column,
)
from app.services.classification.nco_aliases import upsert_nco_aliases
from app.services.datasets.datasets import push_to_catalogue
from app.services.grouping.matching import match_tables_to_metadata
from app.services.standards.classification_standards import (
    create_standard as create_classification_standard,
    delete_standard as delete_classification_standard,
    ensure_bundled_nco_standard as ensure_bundled_classification_standard,
    ensure_selected_loaded as ensure_classification_standard_loaded,
    list_standards as list_classification_standards,
    select_standard as select_classification_standard,
)
from app.storage.object_store import (
    upload_excel_to_gcs as _upload_excel_to_gcs,
    upload_original_sheet_to_gcs as _upload_original_sheet_to_gcs,
    upload_table_excel_to_gcs as _upload_table_excel_to_gcs,
)
from app.services.metadata.metadata_excel import parse_metadata_workbook, parse_concept_file
from app.services.metadata.metadata_fill import (
    METADATA_FIELDS,
    SDG_METADATA_FIELDS,
    _fill_empty_group_metadata,
    _group_metadata_is_empty,
)
from app.services.ingestion.wizard.original_sheet_export import extract_sheet_with_formatting_from_bytes
from app.services.ingestion.wizard.sql_extract import extract_tables_from_sql
from app.services.ingestion.wizard.table_export import table_to_excel_bytes
from app.services.metadata.table_id_title import _catalogue_table_title, _validate_tables

router = APIRouter(tags=["Catalogue"])


@router.post("/api/table-metadata")
async def table_metadata(request: Request, user_email: str = Depends(require_user_email)):
    """LLM-based semantic category extraction from a table's raw structure."""
    data = await request.json()
    extractor = _extractor_for(request, user_email)
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
async def parse_concept_metadata_file(file: UploadFile = File(...), user_email: str = Depends(require_user_email)):
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
async def batch_extract(request: Request, files: list[UploadFile] = File(...), user_email: str = Depends(require_user_email)):
    """Runs table extraction across multiple uploaded dataset workbooks
    concurrently (each file's sheets are also processed concurrently, see
    TableExtractor.extract_from_file) and returns one combined table list,
    each tagged with its source file."""
    extractor = _extractor_for(request, user_email)
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
    await asyncio.to_thread(
        _validate_tables,
        all_tables,
        resolve_llm_credentials(request, user_email)[0],
    )

    # Stage full tables server-side so batch-push can send slim refs only
    # (avoids Starlette's 1MB multipart part limit on groups_json).
    from app.services.catalogue import extract_staging as _staging

    batch_id = _staging.new_batch_id()

    def _stage():
        with session_scope() as session:
            return _staging.save_staging_tables(session, batch_id, all_tables, user_email)

    await asyncio.to_thread(_stage)
    return {
        "tables": all_tables,
        "per_file": per_file,
        "table_count": len(all_tables),
        "batch_id": batch_id,
    }


@router.post("/api/catalogue/sql-extract")
async def sql_extract(request: Request, user_email: str = Depends(require_user_email)):
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

    from app.services.catalogue import extract_staging as _staging

    batch_id = _staging.new_batch_id()

    def _stage():
        with session_scope() as session:
            return _staging.save_staging_tables(session, batch_id, tables, user_email)

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
    user_email: str = Depends(require_user_email),
):
    """Parses multiple metadata workbooks and matches them against a set of
    already-extracted tables. Returns a proposed mapping for review --
    nothing is written to the database here. Metadata files are optional.

    Stage 4 LLM metadata autofill (KYDS + table/Excel facts) runs later,
    after the user finishes grouping — see `/api/catalogue/fill-group-metadata`.
    `dataset_files` is accepted for backwards compatibility but no longer
    triggers autofill here."""
    tables = _json.loads(tables_json)
    # Header overrides; else the caller's stored llm_api_keys row.
    api_key, _provider = resolve_llm_credentials(request, user_email)

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
        result = match_tables_to_metadata(tables, workbooks, api_key=api_key)
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
async def fill_group_metadata(request: Request, user_email: str = Depends(require_user_email)):
    """Stage 4 — after grouping is confirmed, fill empty catalogue metadata
    on each group from KYDS + in-memory table facts (and optional Excel
    workbook bytes if the client still has them).

    Body (JSON):
      groups (required) — same shape as batch-match `groups`
      standard? — `nmds` (default) or `sdg` for SDG indicator fields
      dataset_files_b64? — optional { filename: base64 } map of workbook bytes
    """
    extractor = _extractor_for(request, user_email)
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
        with session_scope() as session:
            kyds_responses = kyds_repo.get_latest_responses(session, user_email)
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
            "llm_filled": bool(g.get("_llm_filled")),
            "llm_filled_fields": list(g.get("_llm_filled_fields") or []),
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
        "autofill_llm_filled_count": sum(1 for item in group_metadata if item["llm_filled"]),
    }


