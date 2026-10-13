"""Column alignment / garbled-cell / direction-column guards."""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import openai
import pandas as pd
import pymupdf

from app.services.extraction.pdf.confidence_validation.constants import (
    _DIRECTION_TOKENS,
    _EMPTY_TOKENS,
    _GARBLED_RE,
    _NUMERIC_DATA_TYPES,
)
from app.services.extraction.pdf.utils.pymupdf import (
    _best_matching_ruled_candidate,
    _llm_missing_identity_stubs,
    _llm_starts_at_sex_column,
    dedupe_candidates_by_bbox,
)

from app.services.extraction.pdf.confidence_validation.table_confidence import table_dict_from_df


def _stamp_bbox_from_candidate(table: Dict[str, Any], cand: Optional[Dict[str, Any]]) -> None:
    """Copy bbox from a ruled candidate onto a validated table dict."""
    if not cand:
        return
    bb = cand.get("bbox")
    if bb and len(bb) >= 4 and not table.get("bbox"):
        table["bbox"] = [float(x) for x in bb[:4]]


_COL_INDEX_STRIP_RE = re.compile(r"^\(\d+\)$")
_BARE_COL_INDEX_RE = re.compile(r"^\d{1,2}$")


def _row_is_column_index_strip(row: Sequence[Any]) -> bool:
    """True when a row is only (1)(2)… or bare 1..N column-index markers."""
    if not row:
        return False
    cells = [str(v).strip() if v is not None else "" for v in row]
    nonempty = [c for c in cells if c]
    if len(nonempty) < 2:
        return False
    paren = sum(1 for c in nonempty if _COL_INDEX_STRIP_RE.match(c))
    bare = sum(1 for c in nonempty if _BARE_COL_INDEX_RE.match(c))
    return paren >= max(2, len(nonempty) - 1) or bare >= max(2, int(0.8 * len(nonempty)))


def _looks_garbled(value: Any) -> bool:
    return isinstance(value, str) and bool(_GARBLED_RE.search(value))


def _rows_look_garbled(rows: List[List[Any]]) -> bool:
    return any(_looks_garbled(cell) for row in rows for cell in row)


def _cell_is_empty(value: Any) -> bool:
    if value is None:
        return True
    try:
        # pandas / numpy NaN from candidate DataFrames
        if value != value:  # noqa: PLR0124 — NaN != NaN
            return True
    except Exception:
        pass
    try:
        import math
        if isinstance(value, float) and math.isnan(value):
            return True
    except Exception:
        pass
    return str(value).strip().lower() in _EMPTY_TOKENS


def _cell_is_column_index_echo(value: Any, col_index: int) -> bool:
    """True when a cell merely repeats the 1-based column number (index-strip bleed)."""
    if _cell_is_empty(value) or col_index < 0:
        return False
    s = str(value).strip()
    expected = str(col_index + 1)
    return s == expected or s == f"({expected})"


def _cell_is_numeric(value: Any) -> Optional[bool]:
    """True/False for clearly numeric vs non-numeric; None if empty/placeholder."""
    if _cell_is_empty(value):
        return None
    s = str(value).strip().replace(",", "").replace("%", "").replace("*", "").strip()
    if len(s) >= 3 and s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    if not s or s.lower() in _EMPTY_TOKENS:
        return None
    try:
        float(s)
        return True
    except ValueError:
        return False


def _column_structural_kind(col: Dict[str, Any]) -> str:
    """ADDED: coarse structural kind for alignment checks (not semantic NMDS)."""
    name = str(col.get("name") or "").lower()
    concept = str(col.get("concept") or "").lower()
    role = str(col.get("role") or "").lower()
    dt = str(col.get("data_type") or "").lower()
    blob = f"{name} {concept}"
    if any(k in blob for k in ("direction", "trend", "change")):
        return "direction"
    if (
        re.search(r"\bs\.?\s*no\.?\b", name)
        or name in ("sno", "#", "sl.", "sl.no.", "sl no")
        or "serial" in name
    ):
        return "serial"
    if any(k in name for k in ("state", "states/uts", "states/ut", "u.t", "uts")) or concept in (
        "state", "geography", "states/uts",
    ):
        return "geo"
    # TOTAL / Grand Total are measure columns even when LLM leaves role unknown.
    # "Adjusted …" mid-year sub-headers are measures too (often wiped to dashes
    # while the index strip bleeds 7/8 into the first body row).
    if (
        name in ("total", "totals", "grand total", "all")
        or re.search(r"\b(total|totals)\b", name)
        or role == "measure"
        or dt in _NUMERIC_DATA_TYPES
        or any(
            k in name
            for k in (
                "percent", "percentage", "index score", "score", "kg/", "gva",
                "rate", "adjusted",
            )
        )
    ):
        return "measure"
    return "other"


def _format_row_span_label(row_nums_1based: List[int], nrows: int) -> str:
    """Compact 'rows 1–12' / 'all 12 data rows' / 'rows 2, 5, 7' label."""
    if not row_nums_1based:
        return "no rows"
    if len(row_nums_1based) == nrows and nrows > 0:
        return f"all {nrows} data row{'s' if nrows != 1 else ''}"
    if len(row_nums_1based) == 1:
        return f"row {row_nums_1based[0]}"
    consecutive = row_nums_1based == list(range(row_nums_1based[0], row_nums_1based[-1] + 1))
    if consecutive and len(row_nums_1based) >= 3:
        return f"rows {row_nums_1based[0]}–{row_nums_1based[-1]}"
    if len(row_nums_1based) <= 8:
        return "rows " + ", ".join(str(r) for r in row_nums_1based)
    head = ", ".join(str(r) for r in row_nums_1based[:5])
    return f"rows {head}, … ({len(row_nums_1based)} of {nrows})"


def _sample_cell_values(values: List[Any], limit: int = 3) -> str:
    samples: List[str] = []
    for v in values:
        if _cell_is_empty(v):
            continue
        s = str(v).strip()
        if len(s) > 40:
            s = s[:37] + "…"
        samples.append(s)
        if len(samples) >= limit:
            break
    return ", ".join(samples)


def _sex_crossed_into_header(name: str) -> bool:
    """True when a header looks like Male/Female×age pivoted into columns."""
    n = str(name or "")
    if not re.search(r"(?i)\b(male|female)\b", n):
        return False
    if not re.search(
        r"(?i)(<\s*\d|\d+\s*[-–—]\s*\d|>=?\s*\d|not\s*stated|total|age)",
        n,
    ):
        return False
    return True


def _detect_column_alignment_issues(
    columns: List[Dict[str, Any]], rows: List[List[Any]]
) -> List[Dict[str, Any]]:
    """ADDED: Deterministic structural check after LLM reconstruction.

    Catches shifted grids like SDG state tables where Direction up/down lands
    under States/UTs, S.No. is glued to the state name, and measure columns
    are left empty. Returns issues with pattern/name/col_index for compact
    user-facing summaries (see _summarize_alignment_issue_notes).
    """
    issues: List[Dict[str, Any]] = []
    if not columns or not rows:
        return issues

    nrows = len(rows)
    has_index_strip = bool(rows) and _row_is_column_index_strip(rows[0])
    for idx, col in enumerate(columns):
        kind = _column_structural_kind(col)
        vals = [row[idx] if idx < len(row) else None for row in rows]
        # Index-strip bleed (Total="7", Adjusted="8") is not real measure content.
        def _effectively_empty(v: Any, _idx: int = idx) -> bool:
            if _cell_is_empty(v):
                return True
            return has_index_strip and _cell_is_column_index_echo(v, _idx)

        empty_rows_1based = [r + 1 for r, v in enumerate(vals) if _effectively_empty(v)]
        non_empty = [v for v in vals if not _effectively_empty(v)]
        name = col.get("name") or f"Column {idx + 1}"
        empty_rate = 1.0 - (len(non_empty) / nrows) if nrows else 0.0
        col_pos = idx + 1

        if kind == "measure" and nrows >= 5:
            if empty_rate >= 0.7:
                issues.append({
                    "col_index": idx,
                    "name": name,
                    "kind": kind,
                    "pattern": "empty_measure",
                    "sex_age": _sex_crossed_into_header(str(name)),
                    "detail": (
                        f'Column {col_pos} ("{name}"): blank '
                        f"({_format_row_span_label(empty_rows_1based, nrows)})"
                    ),
                })
                continue
            numeric_flags = [_cell_is_numeric(v) for v in non_empty]
            judged = [f for f in numeric_flags if f is not None]
            if judged and (sum(1 for f in judged if f) / len(judged)) < 0.5:
                bad_examples: List[str] = []
                for r_i, v in enumerate(vals):
                    if _cell_is_empty(v):
                        continue
                    if _cell_is_numeric(v) is False:
                        shown = str(v).strip()
                        if len(shown) > 24:
                            shown = shown[:21] + "…"
                        bad_examples.append(f'row {r_i + 1}="{shown}"')
                        if len(bad_examples) >= 3:
                            break
                examples = f" — e.g. {'; '.join(bad_examples)}" if bad_examples else ""
                issues.append({
                    "col_index": idx,
                    "name": name,
                    "kind": kind,
                    "pattern": "non_numeric_measure",
                    "detail": (
                        f'Column {col_pos} ("{name}"): expected numbers{examples}'
                    ),
                })
            direction_hits = sum(
                1 for v in non_empty if str(v).strip().lower() in _DIRECTION_TOKENS
            )
            if non_empty and direction_hits / len(non_empty) >= 0.4:
                dir_rows = [
                    r + 1 for r, v in enumerate(vals)
                    if not _cell_is_empty(v) and str(v).strip().lower() in _DIRECTION_TOKENS
                ]
                sample = _sample_cell_values(
                    [v for v in vals if not _cell_is_empty(v)
                     and str(v).strip().lower() in _DIRECTION_TOKENS]
                )
                issues.append({
                    "col_index": idx,
                    "name": name,
                    "kind": kind,
                    "pattern": "direction_in_measure",
                    "detail": (
                        f'Column {col_pos} ("{name}"): up/down markers in '
                        f"{_format_row_span_label(dir_rows, nrows)}"
                        + (f" ({sample})" if sample else "")
                    ),
                })

        elif kind == "geo" and non_empty:
            direction_hits = sum(
                1 for v in non_empty if str(v).strip().lower() in _DIRECTION_TOKENS
            )
            if direction_hits / len(non_empty) >= 0.4:
                dir_rows = [
                    r + 1 for r, v in enumerate(vals)
                    if not _cell_is_empty(v) and str(v).strip().lower() in _DIRECTION_TOKENS
                ]
                sample = _sample_cell_values(
                    [v for v in vals if not _cell_is_empty(v)
                     and str(v).strip().lower() in _DIRECTION_TOKENS]
                )
                issues.append({
                    "col_index": idx,
                    "name": name,
                    "kind": kind,
                    "pattern": "direction_in_geo",
                    "detail": (
                        f'Column {col_pos} ("{name}"): up/down markers in '
                        f"{_format_row_span_label(dir_rows, nrows)}"
                        + (f" ({sample})" if sample else "")
                    ),
                })

        elif kind == "serial" and non_empty:
            glued_rows: List[int] = []
            glued_samples: List[str] = []
            for r_i, v in enumerate(vals):
                if _cell_is_empty(v):
                    continue
                if isinstance(v, str) and re.match(r"^\d+\s*,\s*\S", v.strip()):
                    glued_rows.append(r_i + 1)
                    if len(glued_samples) < 2:
                        shown = v.strip()
                        if len(shown) > 40:
                            shown = shown[:37] + "…"
                        glued_samples.append(shown)
            if non_empty and len(glued_rows) / len(non_empty) >= 0.3:
                examples = f" — e.g. {', '.join(glued_samples)}" if glued_samples else ""
                issues.append({
                    "col_index": idx,
                    "name": name,
                    "kind": kind,
                    "pattern": "glued_serial",
                    "detail": (
                        f'Column {col_pos} ("{name}"): serial stuck to next field'
                        f" in {_format_row_span_label(glued_rows, nrows)}{examples}"
                    ),
                })

    # Index-strip values (1..N) leaked into the first body row under measure
    # headers — classic swap signal when LLM keeps the strip but shifts cells.
    if has_index_strip and nrows >= 3 and len(columns) >= 4:
        first_body = rows[1]
        leak_idxs: List[int] = []
        for idx, col in enumerate(columns):
            if idx >= len(first_body):
                continue
            if _column_structural_kind(col) not in ("measure", "other"):
                continue
            if _cell_is_column_index_echo(first_body[idx], idx):
                leak_idxs.append(idx)
        if len(leak_idxs) >= 2:
            for idx in leak_idxs:
                if any(i.get("col_index") == idx for i in issues):
                    continue
                name = columns[idx].get("name") or f"Column {idx + 1}"
                issues.append({
                    "col_index": idx,
                    "name": name,
                    "kind": "measure",
                    "pattern": "index_value_leak",
                    "detail": (
                        f'Column {idx + 1} ("{name}"): column-index value '
                        f'"{idx + 1}" landed in the first data row'
                    ),
                })

    return issues


def _measure_numeric_fill_ratio(columns: List[Dict[str, Any]], rows: List[List[Any]]) -> float:
    """ADDED: share of non-empty measure cells that parse as numbers (0..1)."""
    total = 0
    ok = 0
    for idx, col in enumerate(columns):
        if _column_structural_kind(col) != "measure":
            continue
        for row in rows:
            v = row[idx] if idx < len(row) else None
            flag = _cell_is_numeric(v)
            if flag is None:
                continue
            total += 1
            if flag:
                ok += 1
    if total == 0:
        return 0.0
    return ok / total


def _dataframe_numeric_fill_ratio(df: pd.DataFrame) -> float:
    """ADDED: rough numeric density for a pymupdf candidate DataFrame."""
    if df is None or df.empty:
        return 0.0
    total = 0
    ok = 0
    for col in df.columns:
        for v in df[col].tolist():
            flag = _cell_is_numeric(v)
            if flag is None:
                continue
            total += 1
            if flag:
                ok += 1
    if total == 0:
        return 0.0
    return ok / total


def _candidate_restores_blank_measures(
    columns: List[Dict[str, Any]],
    issues: List[Dict[str, Any]],
    cand_df: Optional[pd.DataFrame],
) -> bool:
    """True when the ruled grid has numeric values in measure cols the LLM wiped.

    Global fill ratios stay high when only TOTAL is dashes — compare those
    blank columns directly instead of requiring cand_fill >> llm_fill.

    Also accepts sparse restores (Vital Stats: mostly NA + one footer TOTAL)
    once the leading 1..N index strip is ignored. Columns that are blank in
    *both* grids (e.g. Adjusted) are ignored so they don't block a restore.
    """
    blank_idxs = [
        int(i["col_index"])
        for i in issues
        if i.get("pattern") == "empty_measure" and int(i.get("col_index", -1)) >= 0
    ]
    if not blank_idxs or cand_df is None or cand_df.empty:
        return False
    # Same-width grids only — avoid remapping when structure differs.
    if int(cand_df.shape[1]) != len(columns):
        return False
    skip_first = bool(len(cand_df)) and _row_is_column_index_strip(
        cand_df.iloc[0].tolist()
    )
    restored_any = False
    for idx in blank_idxs:
        if idx >= int(cand_df.shape[1]):
            return False
        col_vals = cand_df.iloc[:, idx].tolist()
        if skip_first:
            col_vals = col_vals[1:]
        nonempty = [v for v in col_vals if not _cell_is_empty(v)]
        if not nonempty:
            # Candidate is also blank here — nothing to restore; don't block.
            continue
        numeric = sum(1 for v in nonempty if _cell_is_numeric(v) is True)
        if numeric < 1:
            return False
        # Dense restore (literacy TOTAL wiped to dashes).
        dense_ok = (
            len(nonempty) >= max(3, int(0.35 * len(col_vals)))
            and numeric / len(nonempty) >= 0.7
        )
        # Sparse restore: footer figure under NA/-- body (still better than blank).
        sparse_ok = numeric >= 1 and numeric / len(nonempty) >= 0.5
        if not (dense_ok or sparse_ok):
            return False
        restored_any = True
    return restored_any


def _table_body_fill_ratio(columns: List[Dict[str, Any]], rows: List[List[Any]]) -> float:
    """Share of non-empty cells in the LLM reconstruction (0..1)."""
    if not columns or not rows:
        return 0.0
    ncol = len(columns)
    total = 0
    filled = 0
    for row in rows:
        for i in range(ncol):
            total += 1
            v = row[i] if i < len(row) else None
            if not _cell_is_empty(v):
                filled += 1
    return filled / total if total else 0.0


def _dataframe_body_fill_ratio(df: pd.DataFrame) -> float:
    """Share of non-empty cells in a candidate DataFrame (0..1)."""
    if df is None or getattr(df, "empty", True):
        return 0.0
    total = 0
    filled = 0
    for row in df.values.tolist():
        for v in row:
            total += 1
            if not _cell_is_empty(v):
                filled += 1
    return filled / total if total else 0.0


def _empty_row_fraction(rows: List[List[Any]]) -> float:
    if not rows:
        return 0.0
    empty = 0
    for row in rows:
        if not row or all(_cell_is_empty(v) for v in row):
            empty += 1
    return empty / len(rows)


def _row_is_placeholder_only(row: Sequence[Any]) -> bool:
    """True when every cell is empty or a dash/NA placeholder."""
    if not row:
        return True
    for v in row:
        if _cell_is_empty(v):
            continue
        s = str(v).strip().lower()
        if s in {"-", "—", "–", "--", "na", "n/a", "n.a.", "n.a", "nil", "."}:
            continue
        return False
    return True


def _count_substantive_data_rows(
    rows: Sequence[Sequence[Any]],
) -> int:
    """Count real data rows (skip column-index strips and placeholder-only rows)."""
    n = 0
    for row in rows:
        if not row:
            continue
        if _row_is_column_index_strip(row):
            continue
        if _row_is_placeholder_only(row):
            continue
        n += 1
    return n


def _dataframe_substantive_row_count(df: pd.DataFrame) -> int:
    if df is None or getattr(df, "empty", True):
        return 0
    return _count_substantive_data_rows(df.values.tolist())


def _best_lines_strict_candidate(candidates: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """Prefer lines_strict; fall back to looser lines (not text) when strict missed.

    Among ruled candidates, prefer wider grids with decent numeric fill so a
    collapsed 4-col LLM reconstruction is rebuilt from the full ~15-col grid
    rather than a sparse fragment.
    """
    if not candidates:
        return None
    strict = [c for c in candidates if c.get("method") == "pymupdf_lines_strict" and c.get("df") is not None]
    lines = [c for c in candidates if c.get("method") == "pymupdf_lines" and c.get("df") is not None]
    pool = strict or lines
    if not pool:
        return None
    return max(
        pool,
        key=lambda c: (
            int(c["df"].shape[1]),
            int(c["df"].shape[0]) * int(c["df"].shape[1]),
            _dataframe_numeric_fill_ratio(c["df"]),
        ),
    )


def _is_direction_like_column(col: Dict[str, Any]) -> bool:
    """ADDED: true when name/concept is Direction / Trend / Change."""
    name = str(col.get("name") or "").lower()
    concept = str(col.get("concept") or "").lower()
    return any(k in name or k in concept for k in ("direction", "trend", "change"))


def _candidate_evidences_direction_column(
    candidates: Optional[List[Dict[str, Any]]],
    page_text: str = "",
) -> bool:
    """ADDED: whether the source extraction (or page text headers) already
    shows a Direction/Trend column. Used to refuse LLM-invented Direction cols."""
    if candidates:
        for cand in candidates:
            df = cand.get("df")
            if df is None or df.empty:
                continue
            for col in df.columns:
                name = str(col).lower()
                if any(k in name for k in ("direction", "trend", "change")):
                    return True
            # Icon-only Direction often lands as an unnamed last column of
            # garbled glyphs / up-down tokens while other columns are numeric.
            if df.shape[1] >= 2:
                last_vals = df.iloc[:, -1].tolist()
                non_empty = [v for v in last_vals if not _cell_is_empty(v)]
                if non_empty:
                    dir_like = sum(
                        1 for v in non_empty
                        if str(v).strip().lower() in _DIRECTION_TOKENS or _looks_garbled(v)
                    )
                    if dir_like / len(non_empty) >= 0.4:
                        return True
    # Header-looking cue in raw text (standalone / spaced like a column title).
    if page_text and re.search(
        r"(?i)(?:^|[\n\r\t|])\s*(direction|trend)\s*(?:$|[\n\r\t|])",
        page_text,
    ):
        return True
    return False


def _strip_ungrounded_direction_columns(
    table: Dict[str, Any],
    candidates: Optional[List[Dict[str, Any]]] = None,
    page_text: str = "",
) -> Dict[str, Any]:
    """ADDED: Remove Direction/Trend/Change columns the LLM invented when the
    source table has no such column. Keep current up/down dropdown logic only
    when Direction is evidenced by pymupdf candidates (or a clear header in
    page text)."""
    columns = table.get("columns") or []
    dir_idxs = [i for i, c in enumerate(columns) if _is_direction_like_column(c)]
    if not dir_idxs:
        return table
    if _candidate_evidences_direction_column(candidates, page_text):
        return table

    keep_idxs = [i for i in range(len(columns)) if i not in set(dir_idxs)]
    table["columns"] = [columns[i] for i in keep_idxs]
    table["rows"] = [
        [row[i] if i < len(row) else None for i in keep_idxs]
        for row in (table.get("rows") or [])
    ]
    notes = list(table.get("notes") or [])
    note = (
        "ADDED: removed Direction/Trend column(s) not present in the source "
        "table (LLM must not invent this column)."
    )
    if note not in notes:
        notes.append(note)
    # Drop stale notes that claim Direction was mapped when we just removed it.
    notes = [
        n for n in notes
        if not (isinstance(n, str) and "direction column" in n.lower() and "mapped" in n.lower())
    ]
    table["notes"] = notes
    return table


def _list_column_names(names: List[str], limit: int = 6) -> str:
    clean = [str(n).strip() or "unnamed" for n in names]
    if len(clean) <= limit:
        return ", ".join(clean)
    shown = ", ".join(clean[: limit - 1])
    return f"{shown}, +{len(clean) - (limit - 1)} more"


def _summarize_alignment_issue_notes(issues: List[Dict[str, Any]]) -> List[str]:
    """Collapse many similar alignment issues into a few short steward notes."""
    if not issues:
        return []

    notes: List[str] = []
    empty = [i for i in issues if i.get("pattern") == "empty_measure"]
    other = [i for i in issues if i.get("pattern") != "empty_measure"]

    if empty:
        names = [
            str(i.get("name") or f"Column {(i.get('col_index') or 0) + 1}")
            for i in empty
        ]
        sex_age = any(i.get("sex_age") for i in empty)
        if len(empty) == 1:
            note = f"Blank value column: {names[0]}."
        else:
            note = f"Blank value columns ({len(empty)}): {_list_column_names(names)}."
        if sex_age:
            note += " Sex looks mixed into age headers — use M/F as row labels instead."
        notes.append(note)

    for issue in other:
        detail = str(issue.get("detail") or "").strip()
        if detail:
            notes.append(detail)
        else:
            notes.append(_format_alignment_issue_note(issue))

    return notes


def _format_alignment_issue_note(issue: Dict[str, Any]) -> str:
    """Fallback single-issue note (prefer _summarize_alignment_issue_notes)."""
    detail = str(issue.get("detail") or "").strip()
    if detail:
        return detail
    name = str(issue.get("name") or "Column").strip() or "Column"
    idx = int(issue.get("col_index", -1))
    if idx < 0:
        return f'Issue in column "{name}".'
    return f'Column {idx + 1} ("{name}"): needs review.'


def _uncertain_note_is_alignment_mismatch(note: Any) -> bool:
    """True for alignment-guard notes (legacy codes or human-readable wording)."""
    s = str(note or "").lower()
    if not s:
        return False
    if "column_alignment_mismatch" in s:
        return True
    if "added guard" in s and ("alignment" in s or "mismatch" in s):
        return True
    markers = (
        "values may sit under the wrong header",
        "values may be shifted under the wrong headers",
        "column headers and values did not line up",
        "rebuilt from the pdf",
        "multi-level headers may have been collapsed",
        "leading s.no./name columns were dropped",
        "sparse reconstruction",
        "title or caption line may have been treated as column headers",
        "column layout check found",
        "looks like a value column but is mostly empty",
        "looks like a value column but most cells are not numbers",
        "serial numbers appear stuck to the next column",
        "serial stuck to next field",
        "contains up/down trend markers",
        "every cell is blank",
        "blank value column",
        "expected numbers",
        "sex looks mixed into age headers",
        "up/down markers in",
    )
    return any(m in s for m in markers)


def _apply_column_alignment_guard(
    table: Dict[str, Any],
    candidates: Optional[List[Dict[str, Any]]] = None,
    used_candidates: Optional[set] = None,
) -> Dict[str, Any]:
    """ADDED: Post-LLM robustness pass for shifted/mismatched column grids.

    1) Detect columns whose values don't match their declared kind.
    2) Flag those columns + uncertain_cells with column_alignment_mismatch.
    3) If the LLM grid looks severely misaligned and a pymupdf candidate has
       clearly better numeric fill, fall back to that candidate's cells while
       keeping the LLM title / description / classification when present.
    """
    columns = table.get("columns") or []
    rows = table.get("rows") or []
    issues = _detect_column_alignment_issues(columns, rows)

    # Prefer a shape-matched unused ruled candidate (multi-table pages) over a
    # single global "best fill" pick that would always reclaim table #1.
    matched_cand, matched_idx = _best_matching_ruled_candidate(
        table, candidates, used_candidates
    )
    # Prefer the widest ruled grid for structure checks — shape-matching alone
    # latches onto a Sex+measures fragment that mirrors a stub-dropping LLM.
    wide_cand = _best_lines_strict_candidate(candidates) if candidates else None
    best_cand = matched_cand or wide_cand
    structure_cand = wide_cand or matched_cand
    if structure_cand is not None:
        cand_ncols = int(structure_cand["df"].shape[1])
        if cand_ncols >= 2 and len(columns) >= max(6, cand_ncols * 2):
            issues.append({
                "col_index": -1, "name": "(table structure)", "kind": "structure",
                "pattern": "structure",
                "detail": (
                    f"Too many columns ({len(columns)} vs ~{cand_ncols} in the PDF grid) "
                    "— a title/caption may have been treated as headers."
                ),
            })
        elif cand_ncols >= 4 and len(columns) <= max(2, cand_ncols // 2):
            issues.append({
                "col_index": -1, "name": "(table structure)", "kind": "structure",
                "pattern": "structure",
                "detail": (
                    f"Too few columns ({len(columns)} vs ~{cand_ncols} in the PDF grid) "
                    "— multi-level headers may have been collapsed."
                ),
            })
        elif (
            cand_ncols >= len(columns) + 2
            and _llm_missing_identity_stubs(table, structure_cand)
        ):
            issues.append({
                "col_index": -1, "name": "(table structure)", "kind": "structure",
                "pattern": "structure",
                "detail": (
                    f"Too few columns ({len(columns)} vs ~{cand_ncols} in the PDF grid) "
                    "— leading S.No./Name columns were dropped from the reconstruction."
                ),
            })
        else:
            # Same width but hollow body: LLM kept headers/S.No. labels while
            # dropping most measure rows (blank mid-table, values dumped at end).
            llm_body = _table_body_fill_ratio(columns, rows)
            cand_body = _dataframe_body_fill_ratio(structure_cand["df"])
            empty_frac = _empty_row_fraction(rows)
            if (
                len(rows) >= 8
                and cand_body >= 0.25
                and (
                    (empty_frac >= 0.35 and cand_body > llm_body + 0.12)
                    or (llm_body <= 0.18 and cand_body > llm_body + 0.18)
                )
            ):
                issues.append({
                    "col_index": -1, "name": "(table structure)", "kind": "structure",
                    "pattern": "structure",
                    "detail": (
                        f"Sparse reconstruction ({empty_frac:.0%} empty rows, "
                        f"body fill {llm_body:.0%} vs PDF grid {cand_body:.0%}) "
                        "— most values were dropped or crammed into trailing rows."
                    ),
                })
            else:
                # LLM dropped whole data rows (e.g. footer TOTAL) or left
                # placeholder-only ghosts while the ruled grid is complete.
                llm_n = _count_substantive_data_rows(rows)
                cand_n = _dataframe_substantive_row_count(structure_cand["df"])
                blank_measure_hit = any(
                    i.get("pattern") == "empty_measure" for i in issues
                )
                # +2 alone is enough; +1 also fires when a measure col is blank
                # (Vital Stats: missing TOTAL row with wiped Total column).
                if cand_n >= 4 and (
                    cand_n >= llm_n + 2
                    or (blank_measure_hit and cand_n >= llm_n + 1)
                ):
                    issues.append({
                        "col_index": -1, "name": "(table structure)", "kind": "structure",
                        "pattern": "structure",
                        "detail": (
                            f"Missing data rows ({llm_n} kept vs ~{cand_n} in the PDF grid) "
                            "— a TOTAL/summary or mid-table block was dropped."
                        ),
                    })

    if not issues:
        return table

    issue_idxs = {i["col_index"] for i in issues}
    for idx, col in enumerate(columns):
        if idx not in issue_idxs:
            continue
        col["human_review_needed"] = True
        col["human_review_reason"] = "column_alignment_mismatch"
        if col.get("input_type") is None:
            col["input_type"] = "inputbox"
            col["input_options"] = None

    notes = list(table.get("notes") or [])
    uncertain = list(table.get("uncertain_cells") or [])
    for note in _summarize_alignment_issue_notes(issues):
        if note not in uncertain:
            uncertain.append(note)
    summary = (
        f"Column layout check found {len(issues)} issue(s); "
        "values may be shifted under the wrong headers."
    )
    if summary not in notes:
        notes.append(summary)

    severe = any(i["kind"] in ("geo", "serial", "structure") for i in issues) or sum(
        1 for i in issues if i["kind"] == "measure"
    ) >= 2
    # A single wiped measure column (e.g. TOTAL → all "—") is enough to rebuild
    # when the ruled candidate still has dense numbers.
    has_blank_measure = any(i.get("pattern") == "empty_measure" for i in issues)

    has_structure_issue = any(i["kind"] == "structure" for i in issues)

    fallback_used = False
    if (severe or has_blank_measure) and candidates:
        cand, cand_idx = matched_cand, matched_idx
        # Structure repairs (dropped stubs / collapsed headers) must use the
        # widest ruled grid, not a fragment that matches the LLM's wrong width.
        if (has_structure_issue or has_blank_measure) and wide_cand is not None:
            cand = wide_cand
            cand_idx = None
            if candidates:
                for i, c in enumerate(candidates):
                    if c is cand:
                        cand_idx = i
                        break
        if cand is None:
            cand = _best_lines_strict_candidate(candidates)
            cand_idx = None
            if cand is not None and candidates:
                for i, c in enumerate(candidates):
                    if c is cand:
                        cand_idx = i
                        break
        if cand is not None:
            llm_fill = _measure_numeric_fill_ratio(columns, rows)
            cand_fill = _dataframe_numeric_fill_ratio(cand["df"])
            # Structure mismatch (e.g. 4 LLM cols vs ~15 grid): always prefer the
            # wider ruled grid. Sparse F-row stubs drag fill down without meaning
            # the candidate is wrong; don't require cand_fill >= 0.5 in that case.
            restores_blank = has_blank_measure and _candidate_restores_blank_measures(
                columns, issues, cand.get("df")
            )
            take_fallback = has_structure_issue or restores_blank or (
                has_blank_measure and cand_fill >= 0.35 and cand_fill > llm_fill + 0.12
            ) or (
                cand_fill >= 0.5 and cand_fill > llm_fill + 0.25
            )
            if take_fallback:
                fallback = table_dict_from_df(
                    cand["df"],
                    method=str(cand.get("method") or "pymupdf_lines_strict"),
                )
                table["columns"] = fallback["columns"]
                table["rows"] = fallback["rows"]
                _stamp_bbox_from_candidate(table, cand)
                table["extraction"] = {
                    "method": f"pymupdf_fallback_after_llm<{cand.get('method')}>",
                    "confidence": "alignment_guard_fallback",
                }
                fallback_note = (
                    "Rebuilt from the PDF ruled grid after column layout mismatch "
                    f"(grid fill {cand_fill:.0%}; earlier reconstruction {llm_fill:.0%}). "
                    "Verify values sit under the right headers."
                )
                notes.append(fallback_note)
                uncertain.append(fallback_note)
                fallback_used = True
                table["_skip_structure_attach"] = True
                if used_candidates is not None and cand_idx is not None:
                    used_candidates.add(cand_idx)
                # Re-detect on fallback grid (usually clean); keep prior notes.
                issues = _detect_column_alignment_issues(table["columns"], table["rows"])
                if not any(i.get("pattern") == "empty_measure" for i in issues):
                    # Drop stale "Blank value column: TOTAL" notes the rebuild fixed.
                    def _is_blank_col_note(n: Any) -> bool:
                        return isinstance(n, str) and n.lower().startswith("blank value column")
                    notes = [n for n in notes if not _is_blank_col_note(n)]
                    uncertain = [u for u in uncertain if not _is_blank_col_note(u)]
                    # Keep the rebuild explanation.
                    if fallback_note not in notes:
                        notes.append(fallback_note)
                    if fallback_note not in uncertain:
                        uncertain.append(fallback_note)
                if issues:
                    for idx, col in enumerate(table["columns"]):
                        if idx in {i["col_index"] for i in issues}:
                            col["human_review_needed"] = True
                            col["human_review_reason"] = "column_alignment_mismatch"
                            if col.get("input_type") is None:
                                col["input_type"] = "inputbox"

    if not fallback_used:
        # Ensure at least one column carries the reason for derive_* rollup.
        if not any(c.get("human_review_reason") == "column_alignment_mismatch" for c in table["columns"]):
            if table["columns"]:
                table["columns"][0]["human_review_needed"] = True
                table["columns"][0]["human_review_reason"] = "column_alignment_mismatch"
                table["columns"][0]["input_type"] = table["columns"][0].get("input_type") or "inputbox"

    table["notes"] = notes
    table["uncertain_cells"] = uncertain
    return table
