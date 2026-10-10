"""Compatibility shim for ``python -m data_ingestion.pdf``."""
from app.services.extraction.pdf.confidence_validation.dev_cli import *  # noqa: F403
from app.services.extraction.pdf.confidence_validation.dev_cli import main
