"""Unified file upload → data ingestion → extraction job (PDF, Excel, CSV)."""
import asyncio
import uuid
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.api.dependencies import CurrentUser
from app.core.permissions import MUTATING_ROLES, require_roles
from app.services.ingestion.utils.source_type import resolve_source_type
from app.workers.extraction_jobs import (
    _get_pdf_job,
    _pdf_job_public,
    _pdf_jobs_lock,
    _run_extraction_job,
    queue_extraction_job,
)
from app.workers.upload_batches import queue_upload_batch, retry_batch_file, run_upload_batch

router = APIRouter(tags=["Upload"])

MAX_BATCH_FILES = 20
MAX_BATCH_BYTES = 80 * 1024 * 1024


@router.post("/api/upload")
async def unified_upload(
    request: Request,
    file: UploadFile = File(...),
    type: str = Form(..., description="pdf, excel, or csv"),
    user: CurrentUser = Depends(require_roles(*MUTATING_ROLES)),
):
    """
    Accept one dataset file and start a background extraction job.
    Poll GET /api/pdf/jobs/{job_id} for progress (same job store as PDF uploads).
    """
    filename = file.filename or "upload"
    try:
        source_type = resolve_source_type(filename, type)
    except ValueError as e:
        raise HTTPException(400, str(e))

    content = await file.read()
    if not content:
        raise HTTPException(400, "Uploaded file is empty")

    if source_type == "excel" and filename.lower().endswith(".xls"):
        raise HTTPException(
            400,
            "Legacy .xls is not supported. Re-save the file as .xlsx.",
        )

    job_id = uuid.uuid4().hex

    # Worker decrypts the caller's stored llm_api_keys row at run time.
    queue_extraction_job(
        job_id=job_id,
        filename=filename,
        user_email=user.email,
        source_type=source_type,
        file_bytes=content,
        organisation_id=str(user.organisation_id),
        user_id=str(user.id),
    )

    asyncio.create_task(
        asyncio.to_thread(_run_extraction_job, job_id, content, source_type)
    )
    return {"job_id": job_id, "source_type": source_type}


def _job_visible_to(job, user: CurrentUser) -> bool:
    if not job or job.get("user_email") != user.email:
        return False
    job_org = job.get("organisation_id")
    if job_org and str(job_org) != str(user.organisation_id):
        return False
    return True


@router.post("/api/upload/batch")
async def upload_batch(
    files: List[UploadFile] = File(...),
    user: CurrentUser = Depends(require_roles(*MUTATING_ROLES)),
):
    """Upload multiple PDF / XLSX / CSV files; poll batch status via GET /api/upload/batches/{batch_id}."""
    if not files:
        raise HTTPException(400, "At least one file is required")
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(400, f"At most {MAX_BATCH_FILES} files per batch")

    prepared = []
    total = 0
    for upload in files:
        filename = upload.filename or "upload"
        try:
            source_type = resolve_source_type(filename, None)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        if source_type == "excel" and filename.lower().endswith(".xls"):
            raise HTTPException(400, "Legacy .xls is not supported. Re-save as .xlsx.")
        content = await upload.read()
        if not content:
            raise HTTPException(400, f"{filename} is empty")
        total += len(content)
        if total > MAX_BATCH_BYTES:
            raise HTTPException(400, "Total upload size exceeds batch limit")
        prepared.append((filename, source_type, content))

    batch_id = uuid.uuid4().hex
    queue_upload_batch(
        batch_id=batch_id,
        user_email=user.email,
        organisation_id=str(user.organisation_id),
        user_id=str(user.id),
        files=prepared,
    )
    asyncio.create_task(asyncio.to_thread(run_upload_batch, batch_id))
    return {"batch_id": batch_id, "job_id": batch_id, "file_count": len(prepared)}


@router.get("/api/upload/batches/{batch_id}")
async def upload_batch_status(batch_id: str, user: CurrentUser = Depends(require_roles(*MUTATING_ROLES))):
    with _pdf_jobs_lock:
        job = _get_pdf_job(batch_id)
        if not _job_visible_to(job, user):
            raise HTTPException(404, "Batch not found")
        return _pdf_job_public(job)


@router.post("/api/upload/batches/{batch_id}/retry")
async def upload_batch_retry(
    batch_id: str,
    file_job_id: str = Form(...),
    user: CurrentUser = Depends(require_roles(*MUTATING_ROLES)),
):
    with _pdf_jobs_lock:
        job = _get_pdf_job(batch_id)
        if not _job_visible_to(job, user):
            raise HTTPException(404, "Batch not found")
    try:
        retry_batch_file(batch_id, file_job_id.strip())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "batch_id": batch_id, "file_job_id": file_job_id}
