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
@router.post("/api/catalogue/batch-push")
async def batch_push(
    request: Request,
    groups_json: str = Form(...),
    metadata_files: list[UploadFile] = File(None),
    tables_blob: Optional[UploadFile] = File(None),
    nmds_concepts_json: Optional[str] = Form(None),
    batch_id: Optional[str] = Form(None),
    pdf_job_id: Optional[str] = Form(None),
    user: CurrentUser = Depends(require_roles(*MUTATING_ROLES)),
):
    user_email = user.email
    org_id = user.organisation_id
    """Pushes a reviewed/confirmed batch mapping to the catalogue -- one
    metadata group + its matched tables per entry in `groups_json`.

    `groups_json` should carry slim table refs (ids + steward overlays). Full
    row payloads are loaded from extract_staging (`batch_id`), pdf_store
    (`pdf_job_id`), or an optional `tables_blob` JSON file upload (used for
    sessions extracted before staging existed). Legacy clients that still
    embed full `rows` in groups_json continue to work.

    Two phases, deliberately kept separate: (1) prepare -- rebuild per-table
    Excel bytes and optional GCS uploads, parallelized -- happens BEFORE any
    database connection is opened, and (2) fast DB writes happen only once
    everything is ready. Doing this in one phase with a connection held open
    for the whole thing caused Neon to drop the (idle, minutes-long)
    connection before it could commit. GCS is skipped unless ENABLE_GCS=true.

    Per-table LLM enrichment is intentionally NOT run here. Group metadata
    was already filled in Stage 4; a second LLM pass per table timed out
    Cloudflare's ~100s proxy limit on large PDF jobs (100+ tables) and
    surfaced as a generic UI "Push failed"."""
    groups = _json.loads(groups_json)
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
        with session_scope() as session:
            if batch_id:
                from app.services.catalogue import extract_staging as _staging
                staged = _staging.load_staging_tables(session, batch_id)
            if pdf_job_id:
                for t in pdf_jobs_repo.list_active_tables(session, pdf_job_id):
                    tid = str(t.get("id") or "")
                    if tid:
                        pdf_tables[tid] = t
                        # MatchResult also keys PDF tables by _uid === id.
                        pdf_tables[str(t.get("_uid") or tid)] = t
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

    def _local_enrich(t: dict) -> dict:
        """Title/unit heuristics only — no LLM. Classify rebuilds real
        classifications from row data via `_classifications_from_table_data`."""
        title = (t.get("title") or t.get("table_id") or "").strip()
        return {
            "short_description": title,
            "long_description": title,
            "units": t.get("unit") or "Count",
            "classifications": {},
            "age_column_keys": {},
        }

    def _prep_table(t):
        # Preserve the extractor's own clean table structure as a
        # downloadable single-sheet Excel per dataset, so a download
        # reflects what was actually cataloged rather than a re-flattened
        # reconstruction from the DB rows.
        xlsx_bytes = table_to_excel_bytes(t)
        t["source_excel_url"] = _upload_table_excel_to_gcs(xlsx_bytes, t.get("id", ""))
        return t, _local_enrich(t)

    def _prepare_group(group):
        tables = []
        for mt in group.get("matched_tables", []):
            raw = mt.get("table") or {}
            t = _hydrate_table(raw)
            t["title"] = _catalogue_table_title(t, mt.get("inventory_item"))
            tables.append(t)
        if not tables:
            return None

        # Local enrich + openpyxl only (no LLM) — safe to run sync per group
        # and parallelize across groups below.
        prepped = [_prep_table(t) for t in tables]

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
        workers = min(8, max(1, len(groups)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            return [g for g in pool.map(_prepare_group, groups) if g]

    def _write_all(prepared):
        results = []
        with session_scope() as session:
            for p in prepared:
                meta = p["meta"]
                result = push_to_catalogue(
                    session, p["tables"], p["enriched"], "new", None,
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
                    organisation_id=org_id,
                )
                results.append(result)
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


