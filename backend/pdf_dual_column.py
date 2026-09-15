"""
Gated handling for dual newspaper-style tables on one page
(e.g. SDG "PERFORMANCE BY INDICATORS"): left stack + right stack
with the same columns, read top→bottom left then top→bottom right.

Detection is narrow. Unmatched pages keep the normal extraction path.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import pymupdf

# Title cue for the Performance-by-Indicators dual stack layout.
_DUAL_TITLE_RE = re.compile(r"performance\s+by\s+indicators", re.I)

# Vertical alignment / size similarity for two side-by-side ruled tables.
_MAX_Y0_DELTA = 50.0
_MAX_HEIGHT_RATIO = 1.35
_MAX_ROW_RATIO = 2.5
_MIN_ROWS = 5
_MAX_NCOL_DELTA = 1
_GUTTER_PT = 4.0

# Standard 4-col schema for Performance-by-Indicators dual stacks.
INDICATOR_STACK_COLUMNS = ["Indicator", "SDG Index 4", "SDG Index 3", "Direction"]

# Glyphs pymupdf emits for the icon-font Direction column on SDA Index PDFs.
# Green up / red down / gray dash vary by extract path:
#   up   → U+F0E1 or Latin "Ç" (U+00C7)
#   down → mojibake "â" / "á" or Latin "È" (U+00C8)
#   same → en-dash; blank cells mean no arrow in the text layer (do not invent).
_DIRECTION_UP = frozenset({"\uf0e1", "↑", "▲", "⬆", "up", "Ç", "ç"})
_DIRECTION_DOWN = frozenset({"â", "á", "↓", "▼", "⬇", "down", "È", "è"})
_DIRECTION_SAME = frozenset({"–", "—", "−", "‒", "same", "flat", "unchanged"})


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


def map_direction_glyph(value: Any) -> Optional[str]:
    """Map extracted Direction cell → up/down/same, or None if blank/unknown.

    Does NOT infer from Index 4 vs Index 3 — SDG arrows mean methodological
    improvement, not numeric increase (e.g. poverty MPI falling still shows ↑).
    """
    s = _cell_str(value)
    if s is None:
        return None
    # Drop ASCII/C0/C1 controls (e.g. "È\\x03") but keep PUA icon glyphs
    # like U+F0E1 — those fail str.isprintable() and must not be stripped.
    s = "".join(ch for ch in s if ord(ch) >= 32 and ord(ch) != 127).strip()
    if not s:
        return None
    low = s.lower()
    if s in _DIRECTION_UP or low in _DIRECTION_UP:
        return "up"
    if s in _DIRECTION_DOWN or low in _DIRECTION_DOWN:
        return "down"
    if s in _DIRECTION_SAME or low in _DIRECTION_SAME:
        return "same"
    # Single-char fallback after stripping junk.
    if len(s) > 1:
        head = s[0]
        if head in _DIRECTION_UP or head.lower() in _DIRECTION_UP:
            return "up"
        if head in _DIRECTION_DOWN or head.lower() in _DIRECTION_DOWN:
            return "down"
        if head in _DIRECTION_SAME:
            return "same"
    # Private-use / odd single glyphs: leave blank rather than invent.
    if len(s) <= 2 and any(ord(ch) >= 0xE000 for ch in s):
        return None
    return None


def _row_looks_like_real_column_header(cells: List[Optional[str]]) -> bool:
    """True only for Indicator / SDG INDEX / Direc-tion style headers."""
    keys = [_header_key(c) for c in cells if c]
    if not keys:
        return False
    blob = " ".join(keys)
    has_dir = "direction" in blob or "direc" in blob or "trend" in blob
    has_index = "index" in blob or "indicator" in blob or "value" in blob
    # Real headers are short labels, not long indicator prose / SDG banners.
    long_text = any(c and len(c) > 40 for c in cells)
    if long_text:
        return False
    if any(_looks_numeric(c) for c in cells):
        return False
    return has_dir or (has_index and len(keys) >= 2)


def coerce_indicator_half_df(df: Any) -> Any:
    """
    Rebuild a dual-stack half as Indicator | SDG Index 4 | SDG Index 3 | Direction.

    pymupdf builds DataFrames with rows[0] as the header. On these pages that
    first row is usually an SDG banner (left) or a real data row (right) — so
    the right half silently lost its first indicator and its numbers. Recover
    the header-as-row whenever it does not look like a true column header.
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

    normalized: List[List[Optional[str]]] = []
    for raw in body_rows:
        # Pad / trim to 4 columns (extra cols rare; drop trailing empties).
        cells = list(raw[:4]) + [None] * max(0, 4 - len(raw))
        cells = cells[:4]
        cells[3] = map_direction_glyph(cells[3])
        # Drop fully empty rows.
        if not any(cells):
            continue
        normalized.append(cells)

    out = pd.DataFrame(normalized, columns=INDICATOR_STACK_COLUMNS, dtype=object)
    return out


def page_text_suggests_dual_indicator_stack(page_text: str) -> bool:
    return bool(page_text and _DUAL_TITLE_RE.search(page_text))


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
    # Order by left edge.
    left, right = (a, b) if ba[0] <= bb[0] else (b, a)
    bl, br = _bbox_of(left), _bbox_of(right)
    assert bl and br
    # Require a clear horizontal gap (or negligible overlap).
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
            # Keep unlocated candidates on both sides as weak context only on left.
            if c.get("method") == "pymupdf_lines_strict":
                continue
            left_cands.append(_retag(c, "left"))
            continue
        cx = (bb[0] + bb[2]) / 2.0
        if cx < mid_x:
            left_cands.append(_retag(c, "left"))
        else:
            right_cands.append(_retag(c, "right"))

    # Ensure the primary strict halves are present.
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
    """Run both pymupdf strategies inside a clip rectangle."""
    from pdf_extraction_workers import _candidates_from_pymupdf_table

    results: List[Dict[str, Any]] = []
    doc = pymupdf.open(pdf_path)
    try:
        page = doc[page_num - 1]
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
    Detect a dual-column indicator stack and return (left_candidates, right_candidates).

    Prefer partitioning existing ruled tables. If the title cue matches but
    partition fails (e.g. one wide bbox), re-extract with mid-page clips.
    """
    partitioned = partition_side_by_side_candidates(candidates)
    if partitioned:
        return partitioned

    if page_text_suggests_dual_indicator_stack(page_text):
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
    # Positional fallback when name align produced all-null but widths match.
    if dest_names and all(v is None for v in out) and len(row) == len(dest_names):
        return list(row)
    return out


def merge_reconstructed_tables(
    left: Dict[str, Any],
    right: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Vertically concatenate right under left, keeping left's column schema.
    Reading order: left half top→bottom, then right half top→bottom.
    """
    merged = dict(left)
    left_names = _col_names(left)
    right_names = _col_names(right)

    # Prefer a wider schema if right recovered Direction and left did not.
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

    # Combine uncertain cells; prefix right-half notes for clarity.
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

    # Title: keep left unless empty.
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
