"""PDF extraction/review/grouping routes (upload -> background job -> review)."""
from __future__ import annotations

import asyncio
import io
import pathlib
import uuid
import zipfile
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response

from app.api.dependencies import (
    CurrentUser,
    require_user,
    require_user_email,
    resolve_llm_credentials,
)
from app.db.session import session_scope
from app.workers.extraction_jobs import (
    _get_pdf_bytes,
    _get_pdf_job,
    _hydrate_user_pdf_jobs,
    _parse_pdf_table_id,
    _pdf_job_public,
    _pdf_jobs,
    _pdf_jobs_lock,
    _pdf_merged_tables_for_job,
    _pdf_table_header_key,
    _pdf_table_sort_key,
    _pdf_tables_from_job,
    _run_extraction_job,
    _save_pdf_job,
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


@router.post("/api/pdf/upload")
async def pdf_upload(
    request: Request,
    file: UploadFile = File(...),
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

    # Header X-Llm-Api-Key overrides; else the caller's stored llm_api_keys row.
    # Optional — without a key, PDF extraction falls back to heuristics.
    api_key, _provider = resolve_llm_credentials(request, user.email)

    queue_extraction_job(
        job_id=job_id,
        filename=file.filename,
        user_email=user.email,
        source_type="pdf",
        file_bytes=content,
        organisation_id=str(user.organisation_id),
        user_id=str(user.id),
    )

    asyncio.create_task(asyncio.to_thread(_run_extraction_job, job_id, content, "pdf", api_key))
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
    the review screen, each tagged with a stable table_id ("{page}-{index}")
    and merged with any reviewer edits already saved via the PATCH endpoint
    below. Table data (rows) is never modified by review -- only
    classification/human_review_* fields are ever patched."""
    with _pdf_jobs_lock:
        job = _get_pdf_job(job_id)
        if not _job_visible_to(job, user):
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


@router.get("/api/pdf/jobs/{job_id}/tables/{table_id}/download")
async def pdf_download_table(job_id: str, table_id: str, user_email: str = Depends(require_user_email)):
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


@router.get("/api/pdf/jobs/{job_id}/tables/download-zip")
async def pdf_download_tables_zip(job_id: str, user_email: str = Depends(require_user_email)):
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


@router.post("/api/pdf/jobs/{job_id}/persist-approved")
async def pdf_persist_approved(job_id: str, request: Request, user_email: str = Depends(require_user_email)):
    """
    Continue from Preview: write approved tables to Postgres and propose
    title-based groups (same base-title rule as Excel; SDG jobs by goal).

    Optional JSON body `{ "tables": [ { table_id, title, rows, columns, … } ] }`
    overlays the in-memory job reviews so Preview edits that haven't been
    PATCHed yet (or failed silently) still reach grouping.
    """
    from app.db import pdf_store
    from app.services.grouping import pdf_grouping

    api_key, _provider = resolve_llm_credentials(request, user_email)
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
async def pdf_propose_grouping(job_id: str, request: Request, user_email: str = Depends(require_user_email)):
    """Re-run automatic title-based grouping and overwrite saved groups."""
    from app.db import pdf_store
    from app.services.grouping import pdf_grouping

    api_key, _provider = resolve_llm_credentials(request, user_email)
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
