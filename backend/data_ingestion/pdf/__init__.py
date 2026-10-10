"""
PDF upload **step 1** (before grouping).

Start with [`pipeline.py`](pipeline.py) / ``run_pdf_upload_pipeline``.
See [`README.md`](README.md) for the end-to-end diagram.

Step 2 (grouping → publish) lives under ``pdf/`` job routes, not here.
"""

from data_ingestion.pdf.confidence_validation import (
    run_pipeline,
    run_post_extraction_validation,
)
from data_ingestion.pdf.extract import extract_pdf_to_pre_input
from data_ingestion.pdf.pipeline import run_pdf_upload_pipeline, validate_pre_input
from data_ingestion.pdf.source import prepare_pdf_source

__all__ = [
    "extract_pdf_to_pre_input",
    "prepare_pdf_source",
    "run_pdf_upload_pipeline",
    "run_post_extraction_validation",
    "run_pipeline",
    "validate_pre_input",
]
