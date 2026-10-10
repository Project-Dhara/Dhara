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
@router.post("/api/catalogue/fill-definitions")
async def fill_definitions(request: Request, user_email: str = Depends(require_user_email)):
    """Fill classification definitions from values + catalogue/excel facts.
    Occupation columns are skipped by default (NCO matching owns those).
    Pass allow_occupation=true when no concordance is uploaded and the steward
    chooses Fill with AI as a fallback."""
    import re as _re
    from app.services.metadata.metadata_llm import fill_classification_definitions

    data = await request.json()
    columns = data.get("columns") or []
    if not isinstance(columns, list):
        raise HTTPException(400, "columns must be a list")
    allow_occupation = bool(data.get("allow_occupation"))
    extractor = _extractor_for(request, user_email)
    if extractor.skip_llm:
        raise HTTPException(400, "Configure an LLM key in Settings to fill definitions.")

    def _run():
        with session_scope() as session:
            out = {}
            facts_by_id = {}
            for col in columns:
                name = (col.get("name") or "").strip()
                if not name:
                    continue
                if not allow_occupation and _re.search(r"occupat", name, _re.I):
                    continue
                values = [str(v) for v in (col.get("values") or []) if v is not None and str(v).strip()]
                if not values:
                    continue
                mid = col.get("metadata_id")
                if mid not in facts_by_id:
                    facts_by_id[mid] = get_definition_facts(dbapi_connection(session), mid)
                try:
                    out[name] = fill_classification_definitions(
                        extractor._complete, name, values, facts_by_id[mid],
                    )
                except Exception:
                    out[name] = {}
            return out

    definitions = await asyncio.to_thread(_run)
    return {"definitions": definitions}


@router.get("/api/catalogue/classification-standards")
async def get_classification_standards(user_email: str = Depends(require_user_email)):
    """List classification concordance standards (uploads + bundled NCO CSV)."""

    def _run():
        with session_scope() as session:
            # Re-check in case the CSV appeared after first schema init.
            ensure_bundled_classification_standard(dbapi_connection(session))
            return list_classification_standards(dbapi_connection(session))

    standards = await asyncio.to_thread(_run)
    return {"standards": standards}


@router.post("/api/catalogue/classification-standards")
async def upload_classification_standard(
    name: str = Form(...),
    file: UploadFile = File(...),
    description: str = Form(""),
    select: str = Form("true"),
    user_email: str = Depends(require_user_email),
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
        with session_scope() as session:
            return create_classification_standard(
                dbapi_connection(session),
                name=name,
                csv_bytes=raw,
                original_filename=fname,
                description=description or None,
                uploaded_by=user_email,
                select=do_select,
            )

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
    user_email: str = Depends(require_user_email),
):
    """Make this uploaded standard the active source for occupation matching."""

    def _run():
        with session_scope() as session:
            return select_classification_standard(dbapi_connection(session), standard_id)

    try:
        result = await asyncio.to_thread(_run)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


@router.delete("/api/catalogue/classification-standards/{standard_id}")
async def delete_classification_standard_route(
    standard_id: int,
    user_email: str = Depends(require_user_email),
):
    def _run():
        with session_scope() as session:
            return delete_classification_standard(dbapi_connection(session), standard_id)

    try:
        result = await asyncio.to_thread(_run)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


@router.post("/api/catalogue/match-nco")
async def match_nco(request: Request, user_email: str = Depends(require_user_email)):
    """Suggest the coarsest fitting NCO 2015 level (division, subdivision, or family).
    Does not return specific .xxxx job codes. Dynamic: alias → embed/fuzzy → LLM.
    Codes come from the classification standard selected in Settings."""
    from app.services.classification import nco_matching as _nco
    data = await request.json()
    values = data.get("values") or []
    if not isinstance(values, list):
        raise HTTPException(400, "values must be a list of strings")
    unique = []
    for v in values:
        s = str(v).strip() if v is not None else ""
        if s and s not in unique:
            unique.append(s)
    extractor = _extractor_for(request, user_email)

    def _run():
        with session_scope() as session:
            ensure_classification_standard_loaded(dbapi_connection(session))
            return _nco.match_occupations(dbapi_connection(session), unique, extractor=extractor)

    matches = await asyncio.to_thread(_run)
    return {"matches": matches, "llm_used": not extractor.skip_llm}


@router.post("/api/catalogue/nco-aliases")
async def save_nco_aliases(request: Request, user_email: str = Depends(require_user_email)):
    """Learn occupation → NCO mappings from steward Verify in Classify."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Expected a JSON body")
    aliases = data.get("aliases") if isinstance(data, dict) else None
    if not isinstance(aliases, list):
        raise HTTPException(400, "aliases must be a list")

    def _run():
        with session_scope() as session:
            return upsert_nco_aliases(dbapi_connection(session), aliases, source="steward")

    saved = await asyncio.to_thread(_run)
    return {"saved": saved}
