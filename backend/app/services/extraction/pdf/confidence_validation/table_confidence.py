"""
Deterministic (no-LLM) confidence scoring for extracted table candidates.

Title/caption inference lives in title_infer; this module keeps profile/chart
classification and table_dict_from_df, and re-exports title helpers for
backward-compatible imports.
"""

import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from app.services.extraction.pdf.confidence_validation.title_infer import (
    _blocks_above_bbox,
    _caption_candidate_score,
    _descriptive_line_after_caption_id,
    _descriptive_line_before_caption_id,
    _descriptive_line_near_caption_id,
    _find_line_index,
    _horizontal_overlap,
    _is_caption_id_only,
    _is_chrome_title_line,
    _is_column_group_banner,
    _is_descriptive_caption_candidate,
    _is_scope_subtitle,
    _is_stub_near_caption,
    _is_usable_inferred_title,
    _is_weak_inferred_title,
    _looks_like_heading,
    _matches_extended_caption,
    _normalize_title_line,
    _scope_subtitle_near,
    _title_from_bbox_blocks,
    _title_from_outline_sections,
    _title_from_page_lines,
    build_pdf_outline_index,
    collapse_doubled_pdf_glyphs,
    extract_page_text_blocks,
    infer_title_from_page_text,
    infer_title_meta_from_page_text,
    strip_caption_label_prefix,
    title_needs_review,
)

MIN_ROWS = 2

MIN_NONEMPTY_RATIO = 0.5

MIXED_TYPE_LOW = 0.2

MIXED_TYPE_HIGH = 0.8

_CHART_CAPTION_RE = re.compile(
    r"\b(?:"
    r"graph\s*(?:no\.?|number|#)?\s*\d*"
    r"|chart\s*(?:no\.?|number|#)?\s*\d*"
    r"|fig(?:ure)?\s*(?:no\.?|number|#)?\s*\d*"
    r"|pie\s*chart"
    r"|bar\s*chart"
    r"|bar\s*graph"
    r")\b",
    re.I,
)

def _header_looks_numeric_fragment(name: str) -> bool:
    s = _cell_str(name)
    if not s:
        return True
    compact = re.sub(r"[\s,]", "", s)
    if not compact:
        return True
    if re.fullmatch(r"[\d.\-]+", compact):
        return True
    # Short digit-heavy crumbs from chart value labels ("83145", "27", "Col_12").
    digits = sum(ch.isdigit() for ch in compact)
    return len(compact) <= 6 and digits >= max(2, len(compact) - 1)

def _count_fat_rects_in_bbox(page: Any, bbox: Optional[List[float]]) -> int:
    """Count bar-like filled rectangles overlapping a candidate bbox."""
    if page is None or not bbox or len(bbox) < 4:
        return 0
    try:
        x0, y0, x1, y1 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    except (TypeError, ValueError):
        return 0
    fat = 0
    try:
        drawings = page.get_drawings()
    except Exception:
        return 0
    for d in drawings or []:
        r = d.get("rect")
        if r is None:
            continue
        try:
            if float(r.x1) < x0 or float(r.x0) > x1 or float(r.y1) < y0 or float(r.y0) > y1:
                continue
            rw, rh = float(r.width), float(r.height)
        except Exception:
            continue
        if rw < 8 or rh < 8:
            continue
        aspect = max(rw, rh) / max(min(rw, rh), 1e-6)
        if aspect < 6.0:
            fat += 1
    return fat

def _local_chart_caption(page: Any, bbox: Optional[List[float]]) -> bool:
    if page is None or not bbox or len(bbox) < 4:
        return False
    try:
        import pymupdf as _fitz
        clip = _fitz.Rect(
            float(bbox[0]),
            max(0.0, float(bbox[1]) - 56.0),
            float(bbox[2]),
            float(bbox[3]),
        )
        local = page.get_text("text", clip=clip) or ""
        return bool(_CHART_CAPTION_RE.search(local))
    except Exception:
        return False

def looks_like_chart_candidate(
    df: pd.DataFrame,
    *,
    page: Any = None,
    bbox: Optional[List[float]] = None,
    page_text: str = "",
) -> Tuple[bool, str]:
    """
    Detect bar/line/pie chart regions that pymupdf misreads as tables.

    Guard-only: real ruled statistical tables (sex-by-age, year×rate, …) should
    return False. Charts typically yield very wide sparse numeric grids and/or
    sit under Graph/Chart captions with filled bar rectangles.
    """
    if df is None or getattr(df, "empty", True):
        return False, ""
    try:
        cleaned = clean_dataframe_light(df)
    except Exception:
        cleaned = df
    n_rows, n_cols = cleaned.shape
    fat = _count_fat_rects_in_bbox(page, bbox)
    caption_local = _local_chart_caption(page, bbox)

    cols = [_cell_str(c) for c in cleaned.columns]
    numeric_hdr = sum(1 for c in cols if _header_looks_numeric_fragment(c))
    text_hdr = sum(
        1
        for c in cols
        if c and not _header_looks_numeric_fragment(c) and re.search(r"[A-Za-z]{3,}", c)
    )

    if n_cols < 8 and n_rows >= 3:
        # Compact grids are almost never chart false-positives. Highlighted
        # cells / decorative fills inside real statement tables (Cause of
        # Death, Sl. No., Male/Female, …) create many "fat" rects — keep those
        # when ≥2 text headers are present.
        if text_hdr >= 2:
            return False, ""
        if fat >= 8:
            return True, f"dense filled rectangles in region ({fat})"
        return False, ""
    wide_sparse = (
        (n_cols >= 20 and n_rows <= 10)
        or (n_cols >= 12 and n_cols >= max(12, int(n_rows * 5)))
    )
    header_smoke = text_hdr <= max(1, n_cols // 20) and numeric_hdr >= max(3, n_cols // 5)

    if wide_sparse and header_smoke:
        return True, (
            f"chart-like grid {n_rows}x{n_cols} "
            f"(numeric headers {numeric_hdr}/{n_cols}, text headers {text_hdr})"
        )
    if fat >= 6 and (wide_sparse or header_smoke or caption_local):
        return True, f"chart bars in region (fat_rects={fat})"
    if caption_local and (wide_sparse or header_smoke or fat >= 3):
        return True, "Graph/Chart caption over non-tabular region"
    if caption_local and n_cols >= 10 and text_hdr <= 1:
        return True, "Graph/Chart caption with label-less wide grid"
    # Page mentions Graph/Chart and this candidate is a wide numeric crumb grid.
    if page_text and _CHART_CAPTION_RE.search(page_text) and wide_sparse and header_smoke:
        return True, "page Graph/Chart caption with chart-like grid"
    return False, ""

def _cell_str(v: Any) -> str:
    if v is None:
        return ""
    # Pandas empty cells often arrive as float NaN; str(nan)=="nan" must not
    # count as a real value (or as numeric) for fill / mixed-type checks.
    if isinstance(v, float) and math.isnan(v):
        return ""
    s = re.sub(r"\s+", " ", str(v)).strip()
    if s.lower() in {"nan", "none", "<na>"}:
        return ""
    return s

def _is_numeric_cell(v: str) -> bool:
    s = v.replace(",", "").replace("*", "").rstrip("%").strip()
    if len(s) >= 3 and s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    if not s or s.lower() in {"nan", "none"} or s in {"-", "—", "NA", "N/A"}:
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False

_TYPE_PLACEHOLDERS = frozenset({
    "", "na", "n/a", "n.a.", "n.a", "nil", "null", "-", "—", "–", "--", ".",
})

def _is_type_placeholder(v: str) -> bool:
    return (v or "").strip().lower() in _TYPE_PLACEHOLDERS

_BARE_INDEX_RE = re.compile(r"^\d{1,2}$")

def _row_values_are_column_index(vals: List[str], n_cols: int) -> bool:
    """True when a row is a bare 1..N column-number strip under headers."""
    nonempty = [v for v in vals if v]
    if len(nonempty) < max(3, int(n_cols * 0.6)):
        return False
    if not all(_BARE_INDEX_RE.match(v) for v in nonempty):
        return False
    try:
        nums = [int(v) for v in nonempty]
    except ValueError:
        return False
    return bool(nums) and nums == list(range(1, len(nums) + 1))

def _df_without_leading_column_index(df: pd.DataFrame) -> pd.DataFrame:
    """Drop a leading 1..N reference strip so it does not skew mixed-type checks.

    The strip is still kept in the extracted table for Preview; profiling only
    looks at real data rows.
    """
    if df is None or getattr(df, "empty", True) or len(df) < 2:
        return df
    first = [_cell_str(v) for v in df.iloc[0].values]
    if not _row_values_are_column_index(first, int(df.shape[1])):
        return df
    out = df.iloc[1:].copy()
    try:
        for key, val in getattr(df, "attrs", {}).items():
            out.attrs[key] = val
    except Exception:
        pass
    return out.reset_index(drop=True)

_PLACEHOLDER_COL_RE = re.compile(r"^Col_\d+$", re.I)

def _is_placeholder_column_name(name: str) -> bool:
    s = (name or "").strip()
    return (not s) or bool(_PLACEHOLDER_COL_RE.match(s))

def clean_dataframe_light(df: pd.DataFrame) -> pd.DataFrame:
    """Whitespace-normalize cells, blank out empty strings, drop fully-empty
    rows and placeholder-only empty columns. Named headers with no body values
    (e.g. unused month columns) are kept so auto-accept does not collapse the
    grid and mis-label later columns."""
    meta = None
    caption = None
    banner_id = None
    try:
        meta = list(getattr(df, "attrs", {}).get("dhara_column_meta") or [])
        caption = getattr(df, "attrs", {}).get("dhara_table_caption")
        banner_id = getattr(df, "attrs", {}).get("dhara_banner_table_id")
    except Exception:
        meta = None
    cleaned = df.map(lambda v: _cell_str(v) or None)
    cleaned.columns = [_cell_str(c) or f"Col_{i + 1}" for i, c in enumerate(cleaned.columns)]
    before_cols = list(cleaned.columns)
    cleaned = cleaned.dropna(axis=0, how="all")
    keep_idx: List[int] = []
    for i, name in enumerate(before_cols):
        series = cleaned.iloc[:, i] if cleaned.shape[1] > i else None
        all_null = series is None or bool(series.isna().all())
        if all_null and _is_placeholder_column_name(str(name)):
            continue
        keep_idx.append(i)
    if keep_idx:
        cleaned = cleaned.iloc[:, keep_idx]
    elif cleaned.shape[1]:
        cleaned = cleaned.iloc[:, 0:0]
    cleaned = cleaned.reset_index(drop=True)
    if meta and len(meta) == len(before_cols):
        cleaned.attrs["dhara_column_meta"] = [meta[i] for i in keep_idx]
    elif meta:
        cleaned.attrs["dhara_column_meta"] = meta
    if caption:
        cleaned.attrs["dhara_table_caption"] = caption
    if banner_id:
        cleaned.attrs["dhara_banner_table_id"] = banner_id
    return cleaned

def profile_table(df: pd.DataFrame) -> Dict[str, Any]:
    # Ignore leading 1..N column-number strips for structural scoring — they are
    # reference rows, not typed data (would falsely trip mixed_type on labels).
    df = _df_without_leading_column_index(df)
    n_rows, n_cols = df.shape
    # Ignore all-null columns when scoring fill rate: they are often intentional
    # empty measure periods (kept for header fidelity), not extraction failure.
    active_cols = [
        i for i in range(n_cols)
        if any(_cell_str(v) for v in df.iloc[:, i].values)
    ]
    if active_cols:
        all_cells = [
            _cell_str(v)
            for i in active_cols
            for v in df.iloc[:, i].values
        ]
    else:
        all_cells = [_cell_str(v) for row in df.values for v in row]
    nonempty = [c for c in all_cells if c]
    nonempty_ratio = (len(nonempty) / len(all_cells)) if all_cells else 0.0

    columns = [str(c) for c in df.columns]
    header_has_multiline = any("\n" in c for c in columns)
    seen: set = set()
    duplicate_columns = False
    for c in columns:
        key = c.strip().lower()
        if key and key in seen:
            duplicate_columns = True
        seen.add(key)

    header_dupe_in_first_row = False
    if n_rows >= 1:
        first_row_vals = {_cell_str(v).lower() for v in df.iloc[0].values if _cell_str(v)}
        col_vals = {c.strip().lower() for c in columns if c.strip()}
        if col_vals:
            overlap = len(first_row_vals & col_vals) / len(col_vals)
            header_dupe_in_first_row = overlap >= 0.5

    # A real data column should be either mostly-numeric (a measurement) or
    # mostly-text (a label) -- not a murky middle. A column stuck between
    # MIXED_TYPE_LOW and MIXED_TYPE_HIGH numeric fraction usually means cells
    # bled into the wrong column during extraction.
    # Exception: short stub/code columns (1, a, (b), …) legitimately mix
    # digits and letters and are not misalignment.
    mixed_type_columns = 0
    for col in df.columns:
        vals = [_cell_str(v) for v in df[col].values]
        # NA / -- placeholders are absences, not a second "type".
        nonempty = [v for v in vals if v and not _is_type_placeholder(v)]
        if len(nonempty) < 3:
            continue
        if _is_stub_code_column(nonempty) or _is_row_label_stub_column(nonempty):
            continue
        numeric_frac = sum(_is_numeric_cell(v) for v in nonempty) / len(nonempty)
        if MIXED_TYPE_LOW < numeric_frac < MIXED_TYPE_HIGH:
            mixed_type_columns += 1

    return {
        "n_rows": n_rows,
        "n_cols": n_cols,
        "nonempty_ratio": round(nonempty_ratio, 3),
        "header_has_multiline": header_has_multiline,
        "duplicate_columns": duplicate_columns,
        "header_dupe_in_first_row": header_dupe_in_first_row,
        "mixed_type_columns": mixed_type_columns,
    }

_ROW_LABEL_TEXT_RE = re.compile(
    r"^(?:"
    r"not\s*stated|total|others?|above\s*\d+|below\s*\d+"
    r"|n\.?a\.?|nil|all|sub[\-\s]?total"
    r")$",
    re.I,
)

def _is_stub_code_column(nonempty: List[str]) -> bool:
    """Group/S.No.-style codes (1, a, (b)) look mixed numeric/text but are labels."""
    if len(nonempty) < 3:
        return False
    return all(len(v) <= 4 for v in nonempty)

def _is_row_label_stub_column(nonempty: List[str]) -> bool:
    """Birth-order / category stub: mostly short codes plus a few label tokens.

    e.g. 1..10, above10, Not stated, TOTAL — looks mixed numeric/text but is a
    legitimate stub column, not a misaligned measure.
    """
    if len(nonempty) < 3:
        return False
    codeish = 0
    labelish = 0
    for v in nonempty:
        s = (v or "").strip()
        if not s:
            continue
        if re.fullmatch(r"\d{1,4}", s):
            codeish += 1
            continue
        if re.fullmatch(r"above\s*\d+", s, re.I) or re.fullmatch(r"\d+\+", s):
            codeish += 1
            continue
        if _ROW_LABEL_TEXT_RE.match(s) or (len(s) <= 4 and not re.search(r"[A-Za-z]{4,}", s)):
            labelish += 1
            continue
        return False
    return codeish >= 2 and (codeish + labelish) == len(nonempty)

def _structural_bucket_for_df(df: pd.DataFrame) -> Tuple[str, str, Dict[str, Any]]:
    """Classify one cleaned DataFrame as high-confidence or needing LLM."""
    primary = clean_dataframe_light(df)
    info = profile_table(primary)

    if info["n_rows"] < MIN_ROWS or info["nonempty_ratio"] < MIN_NONEMPTY_RATIO:
        return "llm", "near-empty or sparse lines_strict candidate", info

    if info["header_has_multiline"] or info["duplicate_columns"] or info["header_dupe_in_first_row"]:
        return "llm", "structural issue (multiline/duplicate header or header glued into first row)", info

    if info["mixed_type_columns"] > 0:
        return "llm", "column(s) with a murky numeric/text mix, likely misaligned cells", info

    if any(str(c).startswith("Col_") for c in primary.columns):
        return "llm", "placeholder column header (blank in the raw table) -- real header likely lives outside the ruled region", info

    # Space-joined measure packs ("556 28 3 0") mean colspan leaves were glued.
    glued = 0
    for col in primary.columns:
        for v in primary[col].values:
            s = _cell_str(v)
            if not s or " " not in s:
                continue
            parts = s.split()
            if len(parts) >= 3 and all(
                re.fullmatch(r"[\d,]+(?:\.\d+)?", p) for p in parts
            ):
                glued += 1
                if glued >= 2:
                    return (
                        "llm",
                        "glued multi-value measure cells (column boundaries collapsed)",
                        info,
                    )

    return "high", "clean single-header table, passes all structural checks", info

def classify_page(candidates: List[Dict[str, Any]]) -> Tuple[str, str, Dict[str, Any]]:
    """Returns (bucket, reason, info). bucket is "high" or "llm".

    Every ruled-border candidate on the page (lines_strict, else lines) must
    pass structural checks for the page to be auto-accepted — otherwise a clean
    first table would hide a messy second one from LLM review.
    """
    ruled = [c for c in candidates if c["method"] == "pymupdf_lines_strict"]
    if not ruled:
        ruled = [c for c in candidates if c["method"] == "pymupdf_lines"]
    if not ruled:
        ruled = [c for c in candidates if c.get("method") in ("excel_grid", "csv_grid")]

    if not ruled:
        return "llm", "no ruled-border candidate (should not happen post-filter)", {}

    last_info: Dict[str, Any] = {}
    for c in ruled:
        df = c.get("df")
        if df is None or getattr(df, "empty", True):
            return "llm", "empty ruled-border candidate", {}
        bucket, reason, info = _structural_bucket_for_df(df)
        last_info = info
        if bucket != "high":
            return bucket, reason, info

    method0 = str(ruled[0].get("method") or "")
    if method0 in ("excel_grid", "csv_grid"):
        return "high", f"all {method0} tables pass structural checks", last_info
    label = "lines_strict" if method0 == "pymupdf_lines_strict" else "lines"
    return "high", f"all {label} tables pass structural checks", last_info

def dedupe_column_names(columns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Guarantee unique column names in the output.

    A flattened multi-level header (e.g. two "2023-24" leaf columns under
    different parent groups like "Sanctioned" / "Released") should carry its
    group in the name, but neither the deterministic (no-LLM) path nor the
    LLM always does this. Duplicate names corrupt the table for any
    downstream consumer keyed by column name, so disambiguate deterministically
    here: prefer the column's own category/header_group as a qualifier,
    falling back to a plain occurrence suffix. Does not touch already-unique
    names. Shared by both the auto-accepted (table_dict_from_df) and
    LLM-validated (_normalize_table) paths so neither can leak duplicates.
    """
    seen: Dict[str, int] = {}
    for col in columns:
        name = str(col.get("name") or "").strip()
        seen[name] = seen.get(name, 0) + 1

    counters: Dict[str, int] = {}
    for col in columns:
        name = str(col.get("name") or "").strip()
        if not name or seen.get(name, 0) <= 1:
            continue
        counters[name] = counters.get(name, 0) + 1
        if counters[name] == 1:
            continue  # first occurrence keeps the original name
        qualifier = col.get("category") or col.get("header_group")
        if qualifier and str(qualifier).strip().lower() not in name.lower():
            new_name = f"{name} ({qualifier})"
        else:
            new_name = f"{name} ({counters[name]})"
        col["name"] = new_name
        col.setdefault("human_review_needed", False)
        if not col["human_review_needed"]:
            col["human_review_needed"] = True
            col["human_review_reason"] = "ambiguous_column"
            col["input_type"] = col.get("input_type") or "inputbox"
    return columns

def table_dict_from_df(
    df: pd.DataFrame,
    *,
    page_text: str = "",
    page_num: Optional[int] = None,
    method: str = "pymupdf_lines_strict",
    bbox: Optional[List[float]] = None,
    page_blocks: Optional[List[Dict[str, float]]] = None,
    outline_sections: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build a validated-table-shaped dict directly from a clean DataFrame,
    with no LLM involved. Semantic classification fields stay null (this path
    skips meaning judgment). Title prefers an in-grid banner caption stored on
    ``df.attrs`` (TABLE id row + descriptive title inside the ruled border),
    then falls back to infer_title_from_page_text. Schema matches the LLM
    path so Preview can treat both uniformly via semantic_status."""
    cleaned = clean_dataframe_light(df)
    col_names = [str(c) for c in cleaned.columns]
    # Prefer meta already aligned to cleaned columns (clean_dataframe_light
    # drops placeholder empties by index). Falling back to the pre-clean meta
    # by position mis-labels later columns when empty named months were kept
    # or dropped — e.g. Sep–Dec values shown under Jan–Apr headers.
    meta: List[Any] = []
    try:
        cleaned_meta = list(getattr(cleaned, "attrs", {}).get("dhara_column_meta") or [])
        if cleaned_meta and len(cleaned_meta) == len(col_names):
            meta = cleaned_meta
        else:
            meta = list(getattr(df, "attrs", {}).get("dhara_column_meta") or [])
    except Exception:
        meta = []
    columns = []
    for i, name in enumerate(col_names):
        m = meta[i] if i < len(meta) and isinstance(meta[i], dict) else {}
        header_group = (str(m["header_group"]).strip() or None) if m.get("header_group") else None
        raw_path = m.get("header_path")
        header_path = None
        if isinstance(raw_path, (list, tuple)):
            header_path = [str(p).strip() for p in raw_path if str(p).strip()]
        if not header_path:
            leaf = str(m.get("name") or name)
            header_path = [header_group, leaf] if header_group else [leaf]
        columns.append({
            "name": str(m.get("name") or name),
            "header_group": header_group or (header_path[-2] if len(header_path) >= 2 else None),
            "header_path": header_path,
            "role": "unknown",
            "concept": None,
            "description": None,
            "data_type": "unknown",
            "unit": None,
            "category": None,
            "human_review_needed": False,
            "human_review_reason": None,
        })
    columns = dedupe_column_names(columns)
    in_grid_title = None
    in_grid_banner_id = None
    try:
        in_grid_title = (getattr(df, "attrs", {}).get("dhara_table_caption") or "").strip() or None
        in_grid_banner_id = (
            getattr(df, "attrs", {}).get("dhara_banner_table_id") or ""
        ).strip() or None
    except Exception:
        in_grid_title = None
        in_grid_banner_id = None
    # In-grid banners (TABLE id row + descriptive title row inside the ruled
    # border) beat page-text / outline heuristics — those look above the bbox.
    # But spanning column-group headers ("LEVELS OF LITERACY") must not win.
    banner_from_page: Optional[str] = None
    if in_grid_title and not _is_column_group_banner(in_grid_title):
        title, title_source = strip_caption_label_prefix(in_grid_title), "heuristic_in_grid_banner"
    else:
        title, title_source, banner_from_page = infer_title_meta_from_page_text(
            page_text,
            col_names,
            page_num=page_num,
            bbox=bbox,
            page_blocks=page_blocks,
            outline_sections=outline_sections,
        )
    if title:
        title = strip_caption_label_prefix(title)
    needs_title = title_needs_review(title, columns)
    empty_field = {"value": None, "human_review_needed": False, "human_review_reason": None}
    result = {
        "title": title,
        "title_source": title_source,
        "description": None,
        "classification": {
            "domain": dict(empty_field), "subject": dict(empty_field), "entity": dict(empty_field),
            "table_type": dict(empty_field), "geography": dict(empty_field), "time_period": dict(empty_field),
            "frequency": dict(empty_field), "unit": dict(empty_field),
        },
        "columns": columns,
        "rows": [[None if v is None else str(v) for v in row] for row in cleaned.values.tolist()],
        "notes": [],
        "uncertain_cells": [],
        "semantic_status": "not_classified",
        # Missing title is the one non-semantic signal that still needs a
        # steward look on the auto-accepted path (Preview "Uncertain title").
        "human_review_needed": bool(needs_title),
        "human_review_reason": "uncertain_title" if needs_title else None,
        "extraction": {"method": method or "pymupdf_lines_strict", "confidence": "high"},
        "source": "auto_high_confidence",
    }
    banner_id = in_grid_banner_id or banner_from_page
    if banner_id:
        result["banner_table_id"] = banner_id
    return result

__all__ = [
    "MIN_NONEMPTY_RATIO",
    "MIN_ROWS",
    "MIXED_TYPE_HIGH",
    "MIXED_TYPE_LOW",
    "_descriptive_line_after_caption_id",
    "_descriptive_line_near_caption_id",
    "_is_caption_id_only",
    "_is_column_group_banner",
    "_is_row_label_stub_column",
    "_is_stub_code_column",
    "_is_weak_inferred_title",
    "_matches_extended_caption",
    "_structural_bucket_for_df",
    "_title_from_page_lines",
    "build_pdf_outline_index",
    "classify_page",
    "clean_dataframe_light",
    "collapse_doubled_pdf_glyphs",
    "dedupe_column_names",
    "extract_page_text_blocks",
    "infer_title_from_page_text",
    "infer_title_meta_from_page_text",
    "looks_like_chart_candidate",
    "profile_table",
    "strip_caption_label_prefix",
    "table_dict_from_df",
    "title_needs_review",
]
