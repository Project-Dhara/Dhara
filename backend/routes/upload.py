"""Unified file upload → data ingestion → extraction job (PDF, Excel, CSV)."""
import asyncio
import time
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from core.deps import require_user, resolve_llm_credentials
from data_ingestion import resolve_source_type
from pdf.pdf_jobs import (
    _pdf_jobs_lock,
    _run_extraction_job,
    queue_extraction_job,
)

router = APIRouter(tags=["Upload"])


@router.post("/api/upload")
async def unified_upload(
    request: Request,
    file: UploadFile = File(...),
    type: str = Form(..., description="pdf, excel, or csv"),
    user_email: str = Depends(require_user),
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
    api_key, _provider = resolve_llm_credentials(request, user_email)

    queue_extraction_job(
        job_id=job_id,
        filename=filename,
        user_email=user_email,
        source_type=source_type,
        file_bytes=content,
    )

    asyncio.create_task(
        asyncio.to_thread(_run_extraction_job, job_id, content, source_type, api_key)
    )
    return {"job_id": job_id, "source_type": source_type}
