"""Excel / CSV upload ingestion adapter.

Upload path uses ``app.services.ingestion`` grid ingest + shared extraction validation.
Catalogue wizard Excel extract (``app.services.ingestion.wizard.extractor.TableExtractor``)
is a **separate** contract and must not be merged silently.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional

from app.services.ingestion.contracts import SourceType

_PROGRESS = Optional[Callable[[str, int, str], None]]


def run_spreadsheet_upload(
    file_path: Path,
    source_type: SourceType,
    *,
    api_key: Optional[str] = None,
    on_progress: _PROGRESS = None,
) -> Dict[int, Dict]:
    from app.services.ingestion.spreadsheet_pipeline import run_spreadsheet_upload_pipeline

    return run_spreadsheet_upload_pipeline(
        file_path,
        source_type,
        api_key=api_key,
        on_progress=on_progress,
    )
