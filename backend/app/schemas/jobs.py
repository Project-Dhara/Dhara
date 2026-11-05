"""Job / pipeline step contracts used by the console dashboard."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PipelineStepRequest(BaseModel):
    """Body for PATCH /api/pdf/jobs/{job_id}/pipeline."""

    model_config = ConfigDict(extra="ignore")

    step: int = Field(..., ge=1, le=6, description="Console pipeline step 1–6")
