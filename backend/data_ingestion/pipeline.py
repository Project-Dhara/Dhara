"""
Upload pipeline orchestration (compatibility module).

Implementation lives in ``app.services.ingestion.service``.
"""
from __future__ import annotations

from app.services.ingestion.service import run_upload_pipeline

__all__ = ["run_upload_pipeline"]
