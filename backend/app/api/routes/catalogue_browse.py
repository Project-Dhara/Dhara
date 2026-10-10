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
@router.get("/api/catalogue/datasets")
async def list_catalogue_datasets(
    user: CurrentUser = Depends(require_roles(*READ_ROLES)),
):
    """Published tables (dataset rows). Prefer /api/catalogue/groups for the UI."""
    def _run():
        with session_scope() as session:
            return query_catalogue_datasets(
                session, organisation_id=user.organisation_id
            )

    datasets = await asyncio.to_thread(_run)
    return {"datasets": datasets}


@router.get("/api/catalogue/groups")
async def list_catalogue_groups(
    user: CurrentUser = Depends(require_roles(*READ_ROLES)),
):
    """Published releases for the Catalogue page — one card per metadata group."""
    def _run():
        with session_scope() as session:
            return query_catalogue_groups(
                session, organisation_id=user.organisation_id
            )

    groups = await asyncio.to_thread(_run)
    return {"groups": groups}


@router.get("/api/catalogue/groups/{metadata_id}")
async def get_catalogue_group(
    metadata_id: str,
    user: CurrentUser = Depends(require_roles(*READ_ROLES)),
):
    """One published metadata group (release) with its linked tables."""
    def _run():
        with session_scope() as session:
            return query_catalogue_group(
                session, metadata_id, organisation_id=user.organisation_id
            )

    group = await asyncio.to_thread(_run)
    if not group:
        raise HTTPException(404, f"No published group found for {metadata_id}")
    return group


@router.get("/api/catalogue/groups/{metadata_id}/download")
async def download_catalogue_group(metadata_id: str, user_email: str = Depends(require_user_email)):
    """ZIP of every table in the group, each with Code and Definition
    columns appended after classified / harmonised dimension columns."""
    def _run():
        with session_scope() as session:
            return build_group_download_zip(dbapi_connection(session), metadata_id)

    try:
        result = await asyncio.to_thread(_run)
    except Exception as e:
        raise HTTPException(500, f"Could not build group download: {e}")
    if not result:
        raise HTTPException(404, f"No published group found for {metadata_id}")
    payload, filename = result
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/api/catalogue/metadata-groups/{metadata_id}/classifications")
async def get_classifications(metadata_id: str, user_email: str = Depends(require_user_email)):
    """Classification columns + code lists for the Classify step."""
    def _run():
        with session_scope() as session:
            return get_metadata_group_classifications(
                dbapi_connection(session), metadata_id
            )

    try:
        columns = await asyncio.to_thread(_run)
    except Exception as e:
        raise HTTPException(500, f"Failed to load classifications: {e}")
    if columns is None:
        raise HTTPException(404, f"No metadata group found for {metadata_id}")
    return {"columns": columns}


@router.get("/api/catalogue/classifications/recent")
async def get_recent_classifications(user_email: str = Depends(require_user_email)):
    """Classified columns from this user's most recent metadata groups —
    used when Classify has no metadataIds in session (e.g. refresh)."""
    def _run():
        with session_scope() as session:
            return get_recent_classification_columns(dbapi_connection(session), user_email)

    columns = await asyncio.to_thread(_run)
    return {"columns": columns}


@router.patch("/api/catalogue/metadata-groups/{metadata_id}/classifications")
async def update_classification_column(metadata_id: str, request: Request, user_email: str = Depends(require_user_email)):
    """Persist edited code/definition rows for one classification column,
    or several alias columns that share the same categorical values."""
    data = await request.json()
    column_name = data.get("column_name")
    column_names = data.get("column_names")
    codes = data.get("codes")
    if codes is None or (not column_name and not column_names):
        raise HTTPException(400, "column_name (or column_names) and codes are required")

    def _run():
        with session_scope() as session:
            return update_metadata_group_classification_column(
                dbapi_connection(session),
                metadata_id,
                column_name,
                codes,
                column_names=column_names,
                expand_aliases=data.get("expand_aliases", True),
            )

    ok = await asyncio.to_thread(_run)
    if not ok:
        raise HTTPException(404, f"No metadata group found for {metadata_id}")
    return {"status": "ok"}


