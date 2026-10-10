"""CSV ingestion adapter — same spreadsheet upload path as Excel."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional

_PROGRESS = Optional[Callable[[str, int, str], None]]


def run_csv_upload(
    file_path: Path,
    *,
    api_key: Optional[str] = None,
    on_progress: _PROGRESS = None,
) -> Dict[int, Dict]:
    from app.services.ingestion.adapters.excel import run_spreadsheet_upload

    return run_spreadsheet_upload(
        file_path, "csv", api_key=api_key, on_progress=on_progress
    )
