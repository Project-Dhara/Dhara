"""PDF extraction/review/grouping routes (upload -> background job -> review)."""
from __future__ import annotations

import asyncio
import io
import pathlib
import uuid
import zipfile
from typing import Any, List, Optional

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from sqlalchemy.orm import Session

from app.api.dependencies import (
    CurrentUser,
    get_db,
    require_user,
    require_user_email,
    resolve_llm_credentials,
)
from app.db.session import session_scope
from app.workers.extraction_jobs import (
    _get_pdf_job,
    _hydrate_user_pdf_jobs,
    _pdf_job_public,
    _pdf_jobs,
    _pdf_jobs_lock,
    _pdf_merged_tables_for_job,
    _pdf_table_header_key,
    _pdf_table_sort_key,
    _pdf_tables_from_job,
    _run_extraction_job,
    _save_pdf_job,
    job_extraction_complete,
    queue_extraction_job,
)
from app.services.ingestion.wizard.table_export import safe_download_stem, table_to_excel_bytes

router = APIRouter(tags=["PDF"])


def _job_visible_to(job: Optional[dict], user: CurrentUser) -> bool:
    """Owner email match plus organisation_id when the job is tenant-tagged."""
    if not job or job.get("user_email") != user.email:
        return False
    job_org = job.get("organisation_id")
    if job_org and str(job_org) != str(user.organisation_id):
        return False
    return True


def _parse_dataset_id_config_form(raw: Optional[str]) -> Optional[dict]:
    if not raw or not str(raw).strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid dataset_id_config JSON: {e}") from e
    return parsed if isinstance(parsed, dict) else None


@router.post("/api/pdf/upload")
async def pdf_upload(
    request: Request,
    file: UploadFile = File(...),
    dataset_id_config: Optional[str] = Form(None),
    user: CurrentUser = Depends(require_user),
):
    """Accepts one PDF, stores working state in Postgres, and starts background
    processing without blocking the response — returns a job_id immediately for
    the frontend to poll via GET /api/pdf/jobs/{job_id}."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only .pdf files are supported")

    content = await file.read()
    if not content:
        raise HTTPException(400, "Uploaded file is empty")

    job_id = uuid.uuid4().hex
    id_cfg = _parse_dataset_id_config_form(dataset_id_config)

    # Worker decrypts the caller's stored llm_api_keys row at run time.
    # Optional — without a key, PDF extraction falls back to heuristics.
    queue_extraction_job(
        job_id=job_id,
        filename=file.filename,
        user_email=user.email,
        source_type="pdf",
        file_bytes=content,
        organisation_id=str(user.organisation_id),
        user_id=str(user.id),
        dataset_id_config=id_cfg,
    )

    asyncio.create_task(asyncio.to_thread(_run_extraction_job, job_id, content, "pdf"))
    return {"job_id": job_id, "source_type": "pdf"}


@router.get("/api/pdf/jobs", include_in_schema=False)
async def pdf_jobs_list(user: CurrentUser = Depends(require_user)):
    """Lists the caller's own PDF jobs, most recent first -- lets the
    frontend recover an in-progress/finished job after a page refresh."""
    with _pdf_jobs_lock:
        _hydrate_user_pdf_jobs(user.email)
        mine = [
            _pdf_job_public(j)
            for j in _pdf_jobs.values()
            if _job_visible_to(j, user)
        ]
    mine.sort(key=lambda j: j.get("created_at") or 0, reverse=True)
    return {"jobs": mine}


@router.get("/api/pdf/jobs/{job_id}")
async def pdf_job_status(job_id: str, user: CurrentUser = Depends(require_user)):
    with _pdf_jobs_lock:
        job = _get_pdf_job(job_id)
        if not _job_visible_to(job, user):
            raise HTTPException(404, "Job not found")
        return _pdf_job_public(job)


@router.get("/api/pdf/jobs/{job_id}/result")
async def pdf_job_result(job_id: str, user: CurrentUser = Depends(require_user)):
    """Flattens the pipeline's page-keyed output into one list of tables for
    the review screen. Each table has a sequential dataset id
    (``{prefix}_{stats}_{NNNNN}``) stamped at extract (or upgraded on load).
    Table data (rows) is never modified by review -- only
    classification/human_review_* fields are ever patched."""
    with _pdf_jobs_lock:
        job = _get_pdf_job(job_id)
        if not _job_visible_to(job, user):
            raise HTTPException(404, "Job not found. Please upload the PDF again.")
        if job["status"] not in ("done", "completed_with_errors"):
            raise HTTPException(409, f"Job not finished yet (status={job['status']})")
        filename = job["filename"]
        # Ensures sequential ``{prefix}_{stats}_{NNNNN}`` ids (upgrades legacy).
        tables = _pdf_tables_from_job(job)
    return {"job_id": job_id, "filename": filename, "tables": tables, "is_batch": job.get("source_type") == "batch"}


@router.patch("/api/pdf/jobs/{job_id}/tables/{table_id}")
async def pdf_review_table(job_id: str, table_id: str, request: Request, user_email: str = Depends(require_user_email)):
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


@router.get("/api/pdf/jobs/{job_id}/tables/{table_id}/snapshot")
async def pdf_table_snapshot(job_id: str, table_id: str, user_email: str = Depends(require_user_email)):
    """PNG crop of the source PDF region for this table (or the full page).

    Used in review so humans can compare the extracted grid against the page.
    Prefers a previously saved snapshot in Postgres; otherwise renders from
    stored PDF bytes and persists the PNG for later reference.
    """
    from app.services.extraction.pdf.snapshots import get_or_create_table_snapshot
    from app.services.ingestion.table_ids import find_table_in_job_result, physical_page_value

    with _pdf_jobs_lock:
        job = _get_pdf_job(job_id)
        if not job or job.get("user_email") != user_email:
            raise HTTPException(404, "Job not found")
        if not job_extraction_complete(job.get("status")):
            raise HTTPException(409, f"Job not finished yet (status={job.get('status')})")
        reviews = dict(job.get("reviews") or {})
        deleted = set(job.get("deleted_table_ids") or [])
        job_snapshot = dict(job)

    if table_id in deleted:
        raise HTTPException(404, "Table was deleted")

    located = find_table_in_job_result(job_snapshot, table_id)
    if not located:
        raise HTTPException(404, "Table not found")
    page_key, _idx, raw_table = located
    table = {**raw_table, **reviews.get(table_id, {})}

    try:
        page_num = physical_page_value(table, page_key)
    except (TypeError, ValueError) as e:
        raise HTTPException(400, f"Invalid page for snapshot: {e}") from e
    bbox = table.get("bbox")

    # Batch children keep PDF bytes + pre-rendered PNGs; prefer that job when known.
    storage_job_id = str(table.get("source_file_id") or job_id)
    storage_table_id = str(
        table.get("source_table_id") or table.get("table_id") or table_id
    )
    also_save = None
    if storage_job_id != job_id:
        also_save = (job_id, table_id)

    png, err = await asyncio.to_thread(
        get_or_create_table_snapshot,
        storage_job_id,
        storage_table_id,
        page_num=page_num,
        bbox=bbox,
        also_save_as=also_save,
    )
    if not png:
        status = 404 if err and "no longer available" in err else 500
        raise HTTPException(status, err or "Snapshot unavailable")

    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.post("/api/pdf/jobs/{job_id}/tables/delete")
async def pdf_delete_tables(job_id: str, request: Request, user_email: str = Depends(require_user_email)):
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
        if not job_extraction_complete(job["status"]):
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


@router.post("/api/pdf/jobs/{job_id}/tables/ai-search")
async def pdf_ai_search_tables(
    job_id: str,
    request: Request,
    user_email: str = Depends(require_user_email),
    db: Session = Depends(get_db),
):
    """Natural-language search over extracted table titles.

    Returns ``{ intent: "find"|"remove", table_ids, rationale }``. Never deletes
    tables — ``remove`` only identifies candidates for the Preview selection UI.
    """
    from app.services.extraction.pdf.suggest_search import suggest_tables_from_prompt

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    prompt = str(body.get("prompt") or body.get("query") or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt is required")

    api_key, _provider = resolve_llm_credentials(request, user_email, db=db)
    if not (api_key or "").strip():
        raise HTTPException(400, "Save an LLM API key in Settings before using AI search")

    with _pdf_jobs_lock:
        job = _get_pdf_job(job_id)
        if not job or job.get("user_email") != user_email:
            raise HTTPException(404, "Job not found")
        if not job_extraction_complete(job["status"]):
            raise HTTPException(409, f"Job not finished yet (status={job['status']})")
        tables = _pdf_tables_from_job(job)

    # Prefer titles / summaries from the live Preview payload when sent.
    client_tables = body.get("tables")
    if isinstance(client_tables, list) and client_tables:
        by_id = {
            str(t.get("table_id")): t
            for t in client_tables
            if isinstance(t, dict) and t.get("table_id")
        }
        for t in tables:
            override = by_id.get(str(t.get("table_id") or ""))
            if not override:
                continue
            for key in ("title", "banner_table_id", "short_description", "description", "summary"):
                if key in override:
                    t[key] = override.get(key)

    try:
        result = await asyncio.to_thread(
            suggest_tables_from_prompt,
            prompt=prompt,
            tables=tables,
            api_key=api_key,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(500, f"Could not run AI search: {e}") from e
    return result


@router.post("/api/pdf/jobs/{job_id}/tables/merge")
async def pdf_merge_tables(job_id: str, request: Request, user_email: str = Depends(require_user_email)):
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
        if not job_extraction_complete(job["status"]):
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

        from app.services.ingestion.table_ids import find_table_in_job_result

        located = find_table_in_job_result(job, survivors_id)
        if not located:
            raise HTTPException(404, f"Survivor table {survivors_id} missing from job result")
        page_s, idx, _found = located
        result = job.setdefault("result", {})
        page_entry = result.get(page_s)
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


@router.get("/api/pdf/jobs/{job_id}/tables/{table_id}/download")
async def pdf_download_table(job_id: str, table_id: str, user_email: str = Depends(require_user_email)):
    """Download one extracted PDF table as a clean .xlsx workbook."""
    with _pdf_jobs_lock:
        job = _get_pdf_job(job_id)
        if not job or job.get("user_email") != user_email:
            raise HTTPException(404, "Job not found")
        if not job_extraction_complete(job["status"]):
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


@router.get("/api/pdf/jobs/{job_id}/tables/download-zip")
async def pdf_download_tables_zip(job_id: str, user_email: str = Depends(require_user_email)):
    """Download all non-deleted tables for a PDF job as a .zip of .xlsx files."""
    with _pdf_jobs_lock:
        job = _get_pdf_job(job_id)
        if not job or job.get("user_email") != user_email:
            raise HTTPException(404, "Job not found")
        if not job_extraction_complete(job["status"]):
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


@router.post("/api/pdf/jobs/{job_id}/tables/download-zip")
async def pdf_download_tables_zip_selected(
    job_id: str, request: Request, user_email: str = Depends(require_user_email)
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
        if not job_extraction_complete(job["status"]):
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


@router.post("/api/pdf/jobs/{job_id}/persist-approved")
async def pdf_persist_approved(
    job_id: str,
    request: Request,
    user_email: str = Depends(require_user_email),
    db: Session = Depends(get_db),
):
    """
    Continue from Preview: write approved tables to Postgres and propose
    title-based groups (same base-title rule as Excel; SDG jobs by goal).

    Optional JSON body `{ "tables": [ { table_id, title, rows, columns, … } ] }`
    overlays the in-memory job reviews so Preview edits that haven't been
    PATCHed yet (or failed silently) still reach grouping.

    Optional `approved_table_ids: string[]` limits which tables are written for
    grouping. Preview can keep showing every table; only the listed IDs proceed.
    When omitted, every job table is persisted (previous behaviour).
    """
    from app.db import pdf_store
    from app.services.grouping import pdf_grouping

    api_key, _provider = resolve_llm_credentials(request, user_email, db=db)
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
        if not job_extraction_complete(job["status"]):
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

        raw_approved = body.get("approved_table_ids")
        if isinstance(raw_approved, list) and raw_approved:
            allowed = {str(tid) for tid in raw_approved if tid}
            tables = [t for t in tables if str(t.get("table_id") or "") in allowed]
            if not tables:
                raise HTTPException(400, "No approved tables matched this job")

    with session_scope() as session:
        persisted = pdf_store.persist_approved_tables(
            session,
            job_id=job_id,
            user_email=user_email,
            filename=filename,
            tables=tables,
        )
        proposal = pdf_grouping.propose_groups(
            session, job_id, api_key=api_key, reindex=True
        )
        grouping = pdf_grouping.apply_proposal_to_db(session, job_id, proposal)
        return {
            "ok": True,
            "job_id": job_id,
            "table_count": len(persisted),
            "grouping": grouping,
        }


@router.get("/api/pdf/jobs/{job_id}/grouping")
async def pdf_get_grouping(job_id: str, user_email: str = Depends(require_user_email)):
    from app.db import pdf_store

    with session_scope() as session:
        job_row = pdf_store.get_job(session, job_id)
        if not job_row or job_row.get("user_email") != user_email:
            # Fall back: allow read if JSON job exists and belongs to user (not yet persisted)
            with _pdf_jobs_lock:
                job = _get_pdf_job(job_id)
            if not job or job.get("user_email") != user_email:
                raise HTTPException(404, "Job not found — continue from Preview to persist tables first.")
            raise HTTPException(409, "Tables not persisted yet — click Continue on Preview.")
        grouping = pdf_store.load_grouping(session, job_id)
        tables = pdf_store.list_active_tables(session, job_id)
        return {
            "job_id": job_id,
            "filename": job_row.get("filename"),
            "grouping_status": job_row.get("grouping_status"),
            "table_count": len(tables),
            **grouping,
        }


@router.post("/api/pdf/jobs/{job_id}/grouping/propose")
async def pdf_propose_grouping(
    job_id: str,
    request: Request,
    user_email: str = Depends(require_user_email),
    db: Session = Depends(get_db),
):
    """Re-run automatic title-based grouping and overwrite saved groups."""
    from app.db import pdf_store
    from app.services.grouping import pdf_grouping

    api_key, _provider = resolve_llm_credentials(request, user_email, db=db)
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    reindex = bool(body.get("reindex")) if isinstance(body, dict) else False

    with session_scope() as session:
        job_row = pdf_store.get_job(session, job_id)
        if not job_row or job_row.get("user_email") != user_email:
            raise HTTPException(404, "Job not found — continue from Preview first.")
        proposal = pdf_grouping.propose_groups(
            session, job_id, api_key=api_key, reindex=reindex
        )
        grouping = pdf_grouping.apply_proposal_to_db(session, job_id, proposal)
        return {"ok": True, "job_id": job_id, **grouping}


@router.put("/api/pdf/jobs/{job_id}/grouping")
async def pdf_save_grouping(job_id: str, request: Request, user_email: str = Depends(require_user_email)):
    """Persist human-edited groups. Body: { groups: [{ name, table_ids: [uuid...] }] }."""
    from app.db import pdf_store

    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(400, "Body must be a JSON object")
    groups_in = payload.get("groups")
    if not isinstance(groups_in, list):
        raise HTTPException(400, "groups must be an array")

    with session_scope() as session:
        job_row = pdf_store.get_job(session, job_id)
        if not job_row or job_row.get("user_email") != user_email:
            raise HTTPException(404, "Job not found")
        active = {t["id"] for t in pdf_store.list_active_tables(session, job_id)}
        normalized = []
        for g in groups_in:
            if not isinstance(g, dict):
                continue
            name = (g.get("name") or "").strip() or "Untitled group"
            raw_ids = g.get("table_pks") or g.get("table_ids") or []
            pks = [str(x) for x in raw_ids if str(x) in active]
            if pks:
                normalized.append({"name": name, "table_pks": pks})
        pdf_store.save_grouping(session, job_id=job_id, groups=normalized)
        return {"ok": True, **pdf_store.load_grouping(session, job_id)}
