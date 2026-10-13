"""
PyMuPDF extraction → ``PreValidationInput`` (no confidence / LLM yet).

Uses ``utils.pymupdf`` + ``utils.workers``. Validation continues in
``confidence_validation``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from app.services.extraction.pdf.source import prepare_pdf_source
from app.services.extraction.pdf.utils.pymupdf import run_pdf_extraction
from app.services.ingestion.contracts import PreValidationInput

_PROGRESS = Optional[Callable[[str, int, str], None]]


def extract_pdf_to_pre_input(
    path: Path,
    *,
    on_progress: _PROGRESS = None,
) -> PreValidationInput:
    """PDF upload → grid candidates + per-page context text."""
    pdf_path = prepare_pdf_source(path)
    pages_grouped, unit_context, outline_index = run_pdf_extraction(
        pdf_path,
        on_progress=on_progress,
    )
    return PreValidationInput(
        pages_grouped=pages_grouped,
        unit_context=unit_context,
        source_type="pdf",
        source_file=pdf_path.name,
        source_path=str(pdf_path.resolve()),
        outline_index=outline_index,
    )
