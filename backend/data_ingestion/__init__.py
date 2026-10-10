"""
Data ingestion: Excel/CSV → ``PreValidationInput``; PDF extraction stays in ``extraction``.

Spreadsheet uploads: ``data_ingestion.spreadsheet_pipeline``.
All upload types: ``data_ingestion.pipeline.run_upload_pipeline``.
"""

from data_ingestion.pipeline import run_upload_pipeline
from data_ingestion.utils import PreValidationInput, resolve_source_type, SourceType

__all__ = [
    "PreValidationInput",
    "SourceType",
    "resolve_source_type",
    "run_upload_pipeline",
]
