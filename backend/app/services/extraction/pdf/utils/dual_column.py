"""
Dual newspaper-style tables on one PDF page.

Some reports place two side-by-side ruled grids with the same column schema
(left stack and right stack). Reading order is top→bottom on the left half,
then top→bottom on the right. This module detects that layout, splits
candidates by geometry (or mid-page re-extract when needed), and merges
halves into one table for downstream validation.

Detection is intentionally narrow; pages that do not match keep the normal path.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pymupdf

# Optional page-text cue when geometry alone finds one wide bbox (common on scorecard pages).
_DUAL_STACK_TITLE_RES = (
    re.compile(r"performance\s+by\s+indicators", re.I),
    re.compile(r"\bindicators?\s+by\s+", re.I),
    re.compile(r"scorecard|dashboard", re.I),
)

# Vertical alignment / size similarity for two side-by-side ruled tables.
_MAX_Y0_DELTA = 50.0
_MAX_HEIGHT_RATIO = 1.35
_MAX_ROW_RATIO = 2.5
_MIN_ROWS = 5
_MAX_NCOL_DELTA = 1
_GUTTER_PT = 4.0

# Icon-font / mojibake trend glyphs in PDF text layers (do not infer trend from numeric columns).
_TREND_UP = frozenset({"\uf0e1", "↑", "▲", "⬆", "up", "Ç", "ç"})
_TREND_DOWN = frozenset({"â", "á", "↓", "▼", "⬇", "down", "È", "è"})
_TREND_FLAT = frozenset({"–", "—", "−", "‒", "same", "flat", "unchanged"})


def _header_key(name: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def _cell_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    try:
        import math

        if isinstance(v, float) and math.isnan(v):
            return None
    except Exception:
        pass
    s = str(v).strip()
    if not s or s.lower() in {"none", "nan", "null"}:
        return None
    return s


def _looks_numeric(v: Any) -> bool:
    s = _cell_str(v)
    if not s:
        return False
    s = s.replace(",", "").rstrip("%").strip()
    try:
        float(s)
        return True
    except ValueError:
        return False


def map_trend_glyph(value: Any) -> Optional[str]:
    """Map an extracted trend/direction cell → up/down/same, or None if blank/unknown.

    Uses only the cell text (icons, arrows, mojibake). Does not infer trend from
    other numeric columns.
    """
    s = _cell_str(value)
    if s is None:
        return None
    s = "".join(ch for ch in s if ord(ch) >= 32 and ord(ch) != 127).strip()
    if not s:
        return None
    low = s.lower()
    if s in _TREND_UP or low in _TREND_UP:
        return "up"
    if s in _TREND_DOWN or low in _TREND_DOWN:
        return "down"
    if s in _TREND_FLAT or low in _TREND_FLAT:
        return "same"
    if len(s) > 1:
        head = s[0]
        if head in _TREND_UP or head.lower() in _TREND_UP:
            return "up"
        if head in _TREND_DOWN or head.lower() in _TREND_DOWN:
            return "down"
        if head in _TREND_FLAT:
            return "same"
    if len(s) <= 2 and any(ord(ch) >= 0xE000 for ch in s):
        return None
    return None


# Backward-compatible name for tests/tools that imported the old symbol.
map_direction_glyph = map_trend_glyph


def _row_looks_like_real_column_header(cells: List[Optional[str]]) -> bool:
    """True when a row looks like short column labels (not a section banner or data row)."""
    keys = [_header_key(c) for c in cells if c]
    if not keys:
        return False
    blob = " ".join(keys)
    has_trend = "direction" in blob or "direc" in blob or "trend" in blob or "change" in blob
    has_measure = (
        "index" in blob
        or "indicator" in blob
        or "value" in blob
        or "metric" in blob
        or "name" in blob
        or "label" in blob
    )
    if any(c and len(c) > 40 for c in cells):
        return False
    if any(_looks_numeric(c) for c in cells):
        return False
    return has_trend or (has_measure and len(keys) >= 2)


def _resolve_column_names(
    ncol: int,
    header_cells: Sequence[Optional[str]],
    df_columns: Any,
) -> List[str]:
    """Infer column names from a header row or existing DataFrame columns."""
    cells = list(header_cells[:ncol])
    if _row_looks_like_real_column_header(cells):
        return [
            (str(c).strip() if c else "") or f"Col_{i + 1}" for i, c in enumerate(cells)
        ]

    from_pandas = [_cell_str(c) for c in list(df_columns)[:ncol]]
    if from_pandas and _row_looks_like_real_column_header(from_pandas):
        return [
            (str(c).strip() if c else "") or f"Col_{i + 1}" for i, c in enumerate(from_pandas)
        ]

    return [f"Col_{i + 1}" for i in range(ncol)]


def _trend_column_index(col_names: List[str]) -> Optional[int]:
    for i, name in enumerate(col_names):
        k = _header_key(name)
        if not k:
            continue
        if "direction" in k or k.startswith("direc") or "trend" in k or "change" in k:
            return i
    return None


def coerce_dual_stack_half_df(df: Any) -> Any:
    """
    Normalize one half of a dual-stack ruled table for vertical merge.

    PyMuPDF often promotes the wrong row to column headers (section banner vs true
    header vs first data row). When the current columns do not look like real
    headers, treat them as the first body row. Column names are taken from the
    grid when possible, otherwise ``Col_1`` … ``Col_n``.
    """
    import pandas as pd

    if df is None or getattr(df, "empty", True):
        return df

    ncol = int(df.shape[1])
    if ncol < 3 or ncol > 5:
        return df

    col_as_row = [_cell_str(c) for c in list(df.columns)]
    body_rows: List[List[Optional[str]]] = []
    if not _row_looks_like_real_column_header(col_as_row):
        body_rows.append(col_as_row)

    for _, series in df.iterrows():
        body_rows.append([_cell_str(v) for v in series.tolist()])

    col_names = _resolve_column_names(ncol, col_as_row, df.columns)
    trend_idx = _trend_column_index(col_names)

    normalized: List[List[Optional[str]]] = []
    for raw in body_rows:
        cells = list(raw[:ncol]) + [None] * max(0, ncol - len(raw))
        cells = cells[:ncol]
        if trend_idx is not None and trend_idx < len(cells):
            cells[trend_idx] = map_trend_glyph(cells[trend_idx])
        if not any(cells):
            continue
        normalized.append(cells)

    return pd.DataFrame(normalized, columns=col_names, dtype=object)


def page_text_suggests_dual_stack_layout(page_text: str) -> bool:
    if not page_text:
        return False
    return any(p.search(page_text) for p in _DUAL_STACK_TITLE_RES)


def _bbox_of(cand: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
    bb = cand.get("bbox")
    if not bb or len(bb) < 4:
        return None
    return float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])


def _side_by_side_pair(
    a: Dict[str, Any], b: Dict[str, Any]
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Return (left, right) when two ruled tables sit side by side with similar height."""
    ba, bb = _bbox_of(a), _bbox_of(b)
    if not ba or not bb:
        return None
    left, right = (a, b) if ba[0] <= bb[0] else (b, a)
    bl, br = _bbox_of(left), _bbox_of(right)
    assert bl and br
    if bl[2] > br[0] + 8:
        return None
    if abs(bl[1] - br[1]) > _MAX_Y0_DELTA:
        return None
    h_l, h_r = max(bl[3] - bl[1], 1.0), max(br[3] - br[1], 1.0)
    if max(h_l, h_r) / min(h_l, h_r) > _MAX_HEIGHT_RATIO:
        return None

    dfl, dfr = left.get("df"), right.get("df")
    if dfl is None or dfr is None:
        return None
    if abs(int(dfl.shape[1]) - int(dfr.shape[1])) > _MAX_NCOL_DELTA:
        return None
    rl, rr = int(dfl.shape[0]), int(dfr.shape[0])
    if rl < _MIN_ROWS or rr < _MIN_ROWS:
        return None
    if max(rl, rr) / max(min(rl, rr), 1) > _MAX_ROW_RATIO:
        return None
    return left, right


def partition_side_by_side_candidates(
    candidates: List[Dict[str, Any]],
) -> Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
    """
    If the page already has two side-by-side lines_strict tables, split all
    candidates into left/right groups by bbox center. Returns None when the
    layout does not match.
    """
    strict = [
        c
        for c in candidates
        if c.get("method") == "pymupdf_lines_strict"
        and c.get("df") is not None
        and _bbox_of(c) is not None
    ]
    best: Optional[Tuple[Dict[str, Any], Dict[str, Any]]] = None
    for i in range(len(strict)):
        for j in range(i + 1, len(strict)):
            pair = _side_by_side_pair(strict[i], strict[j])
            if pair:
                best = pair
                break
        if best:
            break
    if not best:
        return None

    left_s, right_s = best
    bl, br = _bbox_of(left_s), _bbox_of(right_s)
    assert bl and br
    mid_x = (bl[2] + br[0]) / 2.0

    left_cands: List[Dict[str, Any]] = []
    right_cands: List[Dict[str, Any]] = []

    def _retag(c: Dict[str, Any], side: str) -> Dict[str, Any]:
        out = dict(c)
        method = str(out.get("method") or "pymupdf")
        if not method.endswith(f"_{side}"):
            out["method"] = f"{method}_{side}"
        out["dual_half"] = side
        return out

    for c in candidates:
        bb = _bbox_of(c)
        if bb is None:
            if c.get("method") == "pymupdf_lines_strict":
                continue
            left_cands.append(_retag(c, "left"))
            continue
        cx = (bb[0] + bb[2]) / 2.0
        if cx < mid_x:
            left_cands.append(_retag(c, "left"))
        else:
            right_cands.append(_retag(c, "right"))

    if not any(c.get("method", "").startswith("pymupdf_lines_strict") for c in left_cands):
        left_cands.insert(0, _retag(left_s, "left"))
    if not any(c.get("method", "").startswith("pymupdf_lines_strict") for c in right_cands):
        right_cands.insert(0, _retag(right_s, "right"))

    if not left_cands or not right_cands:
        return None
    return left_cands, right_cands


def _extract_clipped(
    pdf_path: str, page_num: int, clip: pymupdf.Rect, side: str
) -> List[Dict[str, Any]]:
    """Run pymupdf table strategies inside a clip rectangle."""
    from app.services.extraction.pdf.utils.workers import _candidates_from_pymupdf_table

    results: List[Dict[str, Any]] = []
    doc = pymupdf.open(pdf_path)
    try:
        page = doc[page_num - 1]
        try:
            page_text = page.get_text("text") or ""
        except Exception:
            page_text = ""
        for strategy in ("lines_strict", "lines", "text"):
            try:
                found = page.find_tables(strategy=strategy, clip=clip)
            except Exception:
                continue
            for tab in found.tables:
                results.extend(
                    _candidates_from_pymupdf_table(
                        tab,
                        page_num=page_num,
                        method=f"pymupdf_{strategy}_{side}",
                        extra={"dual_half": side},
                        page=page,
                        page_text=page_text,
                    )
                )
    finally:
        doc.close()
    return results


def _clip_halves_from_midpage(
    pdf_path: str, page_num: int
) -> Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
    doc = pymupdf.open(pdf_path)
    try:
        page = doc[page_num - 1]
        mid = page.rect.width / 2.0
        left_clip = pymupdf.Rect(page.rect.x0, page.rect.y0, mid - _GUTTER_PT, page.rect.y1)
        right_clip = pymupdf.Rect(mid + _GUTTER_PT, page.rect.y0, page.rect.x1, page.rect.y1)
    finally:
        doc.close()

    left = _extract_clipped(pdf_path, page_num, left_clip, "left")
    right = _extract_clipped(pdf_path, page_num, right_clip, "right")

    def _ruled(cands):
        strict = [c for c in cands if "lines_strict" in c.get("method", "")]
        return strict or [c for c in cands if c.get("method", "").startswith("pymupdf_lines_")]

    left_strict = _ruled(left)
    right_strict = _ruled(right)
    if not left_strict or not right_strict:
        return None
    dfl, dfr = left_strict[0]["df"], right_strict[0]["df"]
    if dfl is None or dfr is None:
        return None
    if abs(int(dfl.shape[1]) - int(dfr.shape[1])) > _MAX_NCOL_DELTA:
        return None
    if int(dfl.shape[0]) < _MIN_ROWS or int(dfr.shape[0]) < _MIN_ROWS:
        return None
    return left, right


def try_dual_column_halves(
    pdf_path: str,
    page_num: int,
    candidates: List[Dict[str, Any]],
    page_text: str = "",
) -> Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
    """
    Detect a dual-stack layout; return (left_candidates, right_candidates).

    Prefer partitioning existing ruled tables. If page text suggests a dual-stack
    scorecard but only one wide bbox was found, re-extract with mid-page clips.
    """
    partitioned = partition_side_by_side_candidates(candidates)
    if partitioned:
        return partitioned

    if page_text_suggests_dual_stack_layout(page_text):
        return _clip_halves_from_midpage(pdf_path, page_num)

    return None


def _col_names(table: Dict[str, Any]) -> List[str]:
    cols = table.get("columns") or []
    names: List[str] = []
    for c in cols:
        if isinstance(c, dict):
            names.append(str(c.get("name") or ""))
        else:
            names.append(str(c))
    return names


def _align_row_to_columns(
    row: List[Any], src_names: List[str], dest_names: List[str]
) -> List[Any]:
    if len(src_names) == len(dest_names) and [
        _header_key(s) for s in src_names
    ] == [_header_key(d) for d in dest_names]:
        return list(row) + [None] * max(0, len(dest_names) - len(row))

    src_map = {_header_key(n): i for i, n in enumerate(src_names) if _header_key(n)}
    out: List[Any] = []
    for dest in dest_names:
        key = _header_key(dest)
        if key and key in src_map:
            idx = src_map[key]
            out.append(row[idx] if idx < len(row) else None)
        else:
            out.append(None)
    if dest_names and all(v is None for v in out) and len(row) == len(dest_names):
        return list(row)
    return out


def merge_reconstructed_tables(
    left: Dict[str, Any],
    right: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Vertically concatenate right under left, keeping a shared column schema.
    Reading order: left half top→bottom, then right half top→bottom.
    """
    merged = dict(left)
    left_names = _col_names(left)
    right_names = _col_names(right)

    if len(right_names) > len(left_names):
        merged["columns"] = list(right.get("columns") or [])
        dest_names = right_names
        left_rows = [
            _align_row_to_columns(r, left_names, dest_names)
            for r in (left.get("rows") or [])
        ]
        right_rows = list(right.get("rows") or [])
    else:
        dest_names = left_names
        left_rows = list(left.get("rows") or [])
        right_rows = [
            _align_row_to_columns(r, right_names, dest_names)
            for r in (right.get("rows") or [])
        ]

    merged["rows"] = left_rows + right_rows

    notes = list(merged.get("notes") or [])
    for n in right.get("notes") or []:
        if n not in notes:
            notes.append(n)
    note = (
        "ADDED: merged dual-column table halves (left stack then right stack) "
        "with shared columns."
    )
    if note not in notes:
        notes.append(note)
    merged["notes"] = notes

    unc: List[Any] = list(merged.get("uncertain_cells") or [])
    for u in right.get("uncertain_cells") or []:
        label = u if isinstance(u, str) else str(u)
        tagged = f"right-half: {label}"
        if tagged not in unc and label not in unc:
            unc.append(tagged)
    merged["uncertain_cells"] = unc

    extraction = dict(merged.get("extraction") or {})
    extraction["dual_column_merge"] = True
    extraction["method"] = extraction.get("method") or "pymupdf+llm"
    if "confidence" not in extraction:
        extraction["confidence"] = "llm_validated"
    merged["extraction"] = extraction

    if not (merged.get("title") or "").strip() and (right.get("title") or "").strip():
        merged["title"] = right.get("title")

    return merged


def half_page_text(pdf_path: str, page_num: int, side: str) -> str:
    """Raw text from the left or right half of the page (for LLM grounding)."""
    doc = pymupdf.open(pdf_path)
    try:
        page = doc[page_num - 1]
        mid = page.rect.width / 2.0
        if side == "left":
            clip = pymupdf.Rect(page.rect.x0, page.rect.y0, mid - _GUTTER_PT, page.rect.y1)
        else:
            clip = pymupdf.Rect(mid + _GUTTER_PT, page.rect.y0, page.rect.x1, page.rect.y1)
        return page.get_text("text", clip=clip) or ""
    finally:
        doc.close()
