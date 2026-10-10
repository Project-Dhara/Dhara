"""Validate PDF upload paths before PyMuPDF extraction."""

from __future__ import annotations

from pathlib import Path


def prepare_pdf_source(path: Path) -> Path:
    """Ensure the upload is a readable PDF path for the extraction stage."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a .pdf file, got {path.suffix!r}")
    return path
