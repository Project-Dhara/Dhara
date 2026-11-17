"""Bridge layout-driven Excel/CSV extraction → ``PreValidationInput``.

Keeps the downstream confidence-validation contract unchanged: each table is a
candidate dict with a pandas ``df``, ``method`` in {excel_grid, csv_grid}, and
optional ``dhara_table_caption`` attrs for title inference.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import List, Optional

import pandas as pd

from app.services.ingestion.contracts import PagesGrouped, PreValidationInput, UnitContextText
from app.services.ingestion.layout_table_extractor import (
    Config,
    ExtractedTable,
    extract_file,
)

logger = logging.getLogger(__name__)

# Match existing ingest method tags so confidence_split / table_confidence
# continue to treat these as spreadsheet candidates.
METHOD_BY_SOURCE = {
    "excel": "excel_grid",
    "csv": "csv_grid",
}

# App path: do not shell out to LibreOffice (upload jobs already load data_only).
_DEFAULT_CFG = Config(recalc_missing_cached=False)


def _column_meta_from_header_paths(
    columns: list,
    header_paths: list,
) -> list:
    """Map layout ``header_paths`` → ``dhara_column_meta`` for Preview.

    Validation / stamp expect leaf ``name`` + ``header_path`` lists. MultiIndex
    column objects must never reach Preview — ``str(('Births', 'Male'))`` is
    what stewards were seeing in the header row.
    """
    meta: list = []
    for i, col in enumerate(columns):
        raw = header_paths[i] if i < len(header_paths) else ()
        path = [str(p).strip() for p in (raw or ()) if str(p).strip()]
        if not path:
            leaf = str(col or "").strip() or f"Col_{i + 1}"
            path = [leaf]
        leaf = path[-1]
        meta.append(
            {
                "name": leaf,
                "header_group": path[-2] if len(path) >= 2 else None,
                "header_path": path,
            }
        )
    return meta


def _candidate_dataframe(table: ExtractedTable) -> Optional[pd.DataFrame]:
    """Wide frame for validation with flat string column labels.

    Always use ``data_only()`` (already flattened via ``flatten_names``). Do not
    pass MultiIndex columns into the confidence pipeline — those serialize as
    Python tuple literals in Preview. Multilevel structure is preserved on
    ``df.attrs['dhara_column_meta']`` from layout ``header_paths``.
    """
    try:
        # Preview should mirror the sheet body: section banners, column-number
        # index rows (1,2,3…), and total/subtotal rows (detected structurally —
        # not by fixed labels). ``data_only`` still drops only non-body kinds
        # when totals are off; here we keep the full classified body for review.
        df = table.data_only(
            include_totals=True,
            keep_meta=False,
            include_sections=True,
            include_index=True,
        )
    except Exception:
        logger.exception("failed building dataframe for %s", table.table_id)
        return None
    if df is None or getattr(df, "empty", True):
        return None
    # Layout extractors may emit pandas NA / NaN; pipeline + JSONB persist need None.
    try:
        attrs = dict(getattr(df, "attrs", {}) or {})

        def _plain(v):
            if v is None:
                return None
            try:
                if v is pd.NA:
                    return None
            except Exception:
                pass
            try:
                if isinstance(v, float) and pd.isna(v):
                    return None
                if not isinstance(v, (list, dict, tuple)) and bool(pd.isna(v)):
                    return None
            except (TypeError, ValueError):
                pass
            return v

        safe = pd.DataFrame(
            {
                col: pd.Series([_plain(v) for v in df[col].tolist()], dtype="object")
                for col in df.columns
            }
        )
        safe.attrs.update(attrs)
        df = safe
    except Exception:
        logger.exception("failed sanitizing NA cells for %s", table.table_id)
    try:
        paths = list(table.header_paths or [])
        cols = list(df.columns)
        if paths and len(paths) == len(cols):
            df.attrs["dhara_column_meta"] = _column_meta_from_header_paths(cols, paths)
    except Exception:
        logger.exception("failed attaching column meta for %s", table.table_id)
    # Title for in-grid banner preference during title inference.
    title = (table.title or "").strip()
    if title:
        try:
            df.attrs["dhara_table_caption"] = title
        except Exception:
            pass
    return df


def _unit_context(table: ExtractedTable, filename: str) -> str:
    lines: List[str] = []
    title = (table.title or "").strip()
    if title:
        lines.append(title)
    for note in table.notes or []:
        text = str(note or "").strip()
        if text:
            lines.append(text)
    if filename:
        lines.append(f"Source file: {filename}")
    sheet = (table.sheet or "").strip()
    if sheet:
        lines.append(f"Sheet: {sheet}")
    return "\n".join(lines) if lines else (filename or sheet or "spreadsheet")


def tables_to_pre_validation(
    tables: List[ExtractedTable],
    *,
    source_type: str,
    filename: str,
) -> PreValidationInput:
    method = METHOD_BY_SOURCE.get(source_type, "excel_grid")
    pages_grouped: PagesGrouped = {}
    unit_context: UnitContextText = {}
    unit = 0
    for table in tables:
        # Prefer the upload filename over tempfile paths used during bytes ingest.
        if filename:
            table.source_file = filename
        df = _candidate_dataframe(table)
        if df is None:
            continue
        unit += 1
        sheet = (table.sheet or "").strip() or (
            Path(filename).stem if filename else ("csv" if source_type == "csv" else "")
        )
        pages_grouped[unit] = [
            {
                "page": unit,
                "method": method,
                "df": df,
                "bbox": None,
                "sheet": sheet,
                "source_file": filename,
            }
        ]
        unit_context[unit] = _unit_context(table, filename)
    return PreValidationInput(
        pages_grouped=pages_grouped,
        unit_context=unit_context,
        source_type=source_type,  # type: ignore[arg-type]
        source_file=filename,
    )


def extract_tables_from_path(
    path: Path,
    *,
    cfg: Optional[Config] = None,
) -> List[ExtractedTable]:
    return extract_file(path, cfg or _DEFAULT_CFG)


def extract_tables_from_bytes(
    content: bytes,
    filename: str,
    *,
    cfg: Optional[Config] = None,
) -> List[ExtractedTable]:
    """Write bytes to a temp file with the right suffix, then extract."""
    suffix = Path(filename or "").suffix.lower()
    if suffix not in {".xlsx", ".xlsm", ".xltx", ".xltm", ".xls", ".csv", ".tsv", ".txt"}:
        # Guess from content / callers — excel ingest passes .xlsx names usually.
        suffix = ".csv" if (filename or "").lower().endswith(".csv") else ".xlsx"
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        tables = extract_tables_from_path(tmp_path, cfg=cfg)
        for t in tables:
            t.source_file = filename or t.source_file
        return tables
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass


def ingest_with_layout_extractor(
    *,
    source_type: str,
    filename: str = "",
    content: Optional[bytes] = None,
    path: Optional[Path] = None,
    cfg: Optional[Config] = None,
) -> PreValidationInput:
    if path is not None:
        tables = extract_tables_from_path(Path(path), cfg=cfg)
        name = filename or Path(path).name
    elif content is not None:
        tables = extract_tables_from_bytes(content, filename or "upload.xlsx", cfg=cfg)
        name = filename or "upload.xlsx"
    else:
        raise ValueError("content or path is required")
    return tables_to_pre_validation(tables, source_type=source_type, filename=name)
