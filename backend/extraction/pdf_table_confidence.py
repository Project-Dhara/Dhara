"""
Deterministic (no-LLM) confidence scoring for extracted table candidates.

The OpenAI validation step in extraction.pdf_extraction is doing real
reconstruction work for some pages (mangled/transposed cells, headers glued
into the first data row, or a page where one detection strategy found
nothing at all) -- see the false-positive investigation earlier in this
pipeline's development for concrete examples. But plenty of pages are
already clean: a well-formed single-header table that both pymupdf
strategies ("lines_strict" and "text") independently agree on doesn't need
an LLM to tell us it's fine.

This module computes cheap structural signals per candidate and classifies
each page as:
  - "high"  -- accept the lines_strict candidate directly, no LLM call.
  - "llm"   -- send to the (batched) OpenAI validation step, same as before.

Originally this gated "high" on the "text" strategy candidate agreeing with
"lines_strict" (two independent tools converging = trustworthy). That
turned out not to work on this PDF: measured across real pages, agreement
ratios were ~0.0 not because cell values conflicted but because the two
strategies extract *differently-scoped* regions of the page -- e.g. shapes
like (12, 2) vs (57, 9) on the same page, where "text" pulled in
surrounding paragraph content well beyond the ruled table's boundaries.
Position-aligned comparison between two differently-bounded grids isn't a
meaningful check, so every real table ended up flagged as "disagreement."

Classification is therefore based on the lines_strict candidate's own
internal structural consistency instead: fill rate, clean single-row
header, and per-column type consistency (a real data column should be
either mostly-numeric or mostly-text, not a murky mix -- a column stuck in
the middle usually means misaligned/corrupted extraction). The "text"
candidate is no longer used as a gate at all. This is weaker evidence than
genuine cross-tool corroboration would have been -- it can't catch a
plausible-looking table with a subtly wrong number -- which is the real
trade-off of skipping the LLM: worth knowing, not just a footnote.
"""

import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

MIN_ROWS = 2
MIN_NONEMPTY_RATIO = 0.5
MIXED_TYPE_LOW = 0.2
MIXED_TYPE_HIGH = 0.8

# Captions that mark figures rather than data tables (CRS / statistical PDFs).
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


# Placeholders that are not real typed values for mixed-type detection.
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

    label = "lines_strict" if ruled[0]["method"] == "pymupdf_lines_strict" else "lines"
    return "high", f"all {label} tables pass structural checks", last_info


# Running headers / chrome on SDA-style index PDFs that should never become
# the table title (they sit above every page, not above one specific table).
_TITLE_CHROME_RE = re.compile(
    r"^(?:"
    r"sdg\s+india\s+index|"
    r"\d{4}\s*[-–—]\s*\d{2,4}|"  # 2023-24
    r"page\s+\d+|"
    r"goal\s+\d+(\.\d+)*|"
    r"www\.|"
    r"https?://"
    r")$",
    re.I,
)
# Explicit "TABLE 2.1: ..." captions — strongest signal when present.
_TABLE_CAPTION_RE = re.compile(
    r"^\s*(TABLE|FIG(?:URE)?|CHART)\s+\d+(?:\.\d+)*\s*[:.\-–—]?\s*(.+)$",
    re.I,
)
# Broader document captions (SDA / DES / vital-stats style).
# Id core mirrors pdf_header_utils._TABLE_ID_CORE_RE so "TABLE (ii)" /
# "TABLE - (I)" / "TABLE 10(I)" all count as captions (not only "TABLE-8").
_TABLE_CAPTION_ID_CORE = (
    r"(?:[A-Z0-9][\w.\-–—/]*(?:\s*\([^)]{0,48}\))?|\([^)]{1,48}\))"
)
_EXTENDED_CAPTION_RES = (
    _TABLE_CAPTION_RE,
    re.compile(
        rf"^\s*(?:TABLE|TAB\.?)\s*[:.\-–—]?\s*{_TABLE_CAPTION_ID_CORE}"
        rf"(?:\s*[:.\-–—]\s*.+)?\s*$",
        re.I,
    ),
    re.compile(
        r"^\s*(?:STATEMENT|ANNEX(?:URE)?|SCHEDULE|EXHIBIT|APPENDIX)\s*"
        r"[:.\-–—]?\s*[\w.\-–—/]+(?:\s*[:.\-–—]\s*.+)?$",
        re.I,
    ),
    re.compile(
        r"^\s*(?:FIG(?:URE)?|CHART|BOX)\s+\d+(?:\.\d+)*\s*[:.\-–—]?\s*.+$",
        re.I,
    ),
)
# Strip label words + numbering from inferred titles, e.g.
# "Statement 4.6: Distribution of infant Deaths" → "Distribution of infant Deaths".
# Separator deliberately excludes "." so "4.6" is not split mid-number.
_CAPTION_LABEL_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"TABLE|TAB\.?|STATEMENT|ANNEX(?:URE)?|SCHEDULE|EXHIBIT|APPENDIX|"
    r"FIG(?:URE)?|CHART|BOX"
    r")\b\s*"
    r"(?:[\w]+(?:[./\-][\w]+)*)?\s*"
    r"[:\-–—]\s*",
    re.I,
)
_CAPTION_LABEL_PREFIX_SPACE_RE = re.compile(
    r"^\s*(?:"
    r"TABLE|TAB\.?|STATEMENT|ANNEX(?:URE)?|SCHEDULE|EXHIBIT|APPENDIX|"
    r"FIG(?:URE)?|CHART|BOX"
    r")\b\s+"
    r"[\w]+(?:[./\-][\w]+)*\s+",
    re.I,
)
# Max vertical gap (PDF points) between caption/heading and table top.
_BBOX_TITLE_MAX_GAP_PT = 140.0


def title_needs_review(
    title: Optional[str],
    columns: Optional[List[Any]] = None,
) -> bool:
    """True when Preview should treat the table as missing a usable title.

    Aligns with the frontend ``displayTitle`` / ``tableHasMissingTitle`` rules
    so auto-accepted tables without a caption land in Review needed.
    """
    col_names = []
    for c in columns or []:
        if isinstance(c, dict):
            name = c.get("name")
        else:
            name = c
        n = _normalize_title_line(str(name or ""))
        if n:
            col_names.append(n)
    t = strip_caption_label_prefix(title) or ""
    t = _normalize_title_line(t)
    if not t:
        return True
    if _is_caption_id_only(t) or _is_column_group_banner(t):
        return True
    if _is_weak_inferred_title(t, col_names):
        return True
    if not _is_usable_inferred_title(t, col_names):
        return True
    return False


def collapse_doubled_pdf_glyphs(text: str) -> str:
    """Collapse fake-bold / doubled-glyph PDF titles (Maaiinn → Main).

    PyMuPDF often emits each painted stroke as its own character when the PDF
    fakes bold by overdrawing. Only collapse when most letters sit in
    consecutive identical pairs so normal words (Mississippi, All Ages) stay.
    """
    s = text or ""
    if len(s) < 4:
        return s
    letters = [c for c in s if c.isalpha()]
    if len(letters) < 6:
        return s
    in_pair = 0
    i = 0
    while i < len(letters):
        if i + 1 < len(letters) and letters[i].lower() == letters[i + 1].lower():
            in_pair += 2
            i += 2
        else:
            i += 1
    if in_pair / len(letters) < 0.8:
        return s
    out: list[str] = []
    i = 0
    while i < len(s):
        c = s[i]
        if (
            c.isalpha()
            and i + 1 < len(s)
            and s[i + 1].isalpha()
            and c.lower() == s[i + 1].lower()
        ):
            out.append(c)
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _normalize_title_line(line: str) -> str:
    return re.sub(r"\s+", " ", collapse_doubled_pdf_glyphs((line or "").strip()))


def strip_caption_label_prefix(title: Optional[str]) -> Optional[str]:
    """Remove leading Statement/Table/Annex/… labels from a caption title.

    Keeps the descriptive remainder when present; otherwise returns the original.
    """
    if title is None:
        return None
    s = _normalize_title_line(title)
    if not s:
        return s
    cleaned = _CAPTION_LABEL_PREFIX_RE.sub("", s, count=1).strip(" :.-–—")
    if cleaned == s or len(cleaned) < 4:
        cleaned2 = _CAPTION_LABEL_PREFIX_SPACE_RE.sub("", s, count=1).strip(" :.-–—")
        if cleaned2 and len(cleaned2) >= 4:
            cleaned = cleaned2
    if cleaned and len(cleaned) >= 4 and cleaned.lower() != s.lower():
        return cleaned
    # "TABLE 2.1: Foo" via dedicated capture group when present.
    m = _TABLE_CAPTION_RE.match(s)
    if m:
        rest = _normalize_title_line(m.group(2) or "")
        if rest and len(rest) >= 4:
            return rest
    return s


def _is_chrome_title_line(line: str) -> bool:
    s = _normalize_title_line(line)
    if not s or len(s) < 3:
        return True
    if _TITLE_CHROME_RE.match(s):
        return True
    # Very long paragraph-like lines are body text, not headings.
    if len(s) > 140:
        return True
    return False


def _is_usable_inferred_title(title: str, columns: Optional[List[str]] = None) -> bool:
    """
    Reject garbage titles: truncated wraps ("Direc-"), lone column labels,
    or header rows joined with middots. Prefer no title over a bad one.
    """
    s = _normalize_title_line(title)
    if not s or len(s) < 4:
        return False
    if _is_chrome_title_line(s):
        return False
    # PDF line-wrap leftovers: "Direc-" / "Indic-"
    if re.search(r"[–—\-]$", s):
        return False
    # Column-join fallback used to produce "Indicator · SDG Index 4 · …"
    if " · " in s or s.count("|") >= 2:
        return False

    col_names = [
        _normalize_title_line(c).lower()
        for c in (columns or [])
        if _normalize_title_line(c)
    ]
    low = s.lower()
    for c in col_names:
        if not c:
            continue
        if low == c:
            return False
        # Truncated / partial column header used as title
        if len(low) <= 16 and (c.startswith(low.rstrip("-–—")) or low.rstrip("-–—") in c):
            return False
    return True


def _is_caption_id_only(line: str) -> bool:
    """True for short TABLE/STATEMENT ids with no descriptive remainder."""
    from extraction.pdf_header_utils import _is_table_id_only

    s = _normalize_title_line(line)
    if not s:
        return False
    if _is_table_id_only(s):
        return True
    # "TABLE -8" / "Table- 3" / "TABLE (ii)" with only a short token after the kind word.
    return bool(
        re.match(
            rf"^\s*(?:TABLE|TAB\.?|STATEMENT|ANNEX(?:URE)?|SCHEDULE|EXHIBIT|APPENDIX)\s*"
            rf"[:.\-–—]?\s*{_TABLE_CAPTION_ID_CORE}\s*$",
            s,
            re.I,
        )
    )


# Leaf/header stubs that must never become the table title.
_WEAK_TITLE_TOKENS = frozenset({
    "total", "totals", "all", "male", "female", "males", "females",
    "rural", "urban", "s.no", "s.no.", "sno", "sl", "sl.", "no", "no.",
    "year", "age", "sex", "gender", "unit", "units", "particulars",
    "month", "months", "order", "local body", "birth order",
})

# Spanning column-group banners inside the ruled grid (not the page caption).
# E.g. "LEVELS OF LITERACY" sits under the top border while the real title
# ("LIVE BIRTH BY …") is printed above the table.
_COLUMN_GROUP_BANNER_RE = re.compile(
    r"^(?:"
    r"levels?\s+of\s+.+"
    r"|occupation\s+groups?"
    r"|age\s+of\s+mothers?(?:\s*\([^)]*\))?"
    r"|birth\s+order"
    r"|religion\s+of\s+(?:the\s+)?(?:families|deceased|fathers?|mothers?)"
    r"|fathers?'?\s+rel[ei]gion"
    r"|mothers?'?\s+rel[ei]gion"
    r")$",
    re.I,
)

# Geography / population-scope lines that belong with the title as a subtitle
# (TABLE-14(ii) → "…FATHER, 2001 — RURAL"; TABLE-13(vi) → "… — DELHI CANTT.").
_SCOPE_SUBTITLE_RE = re.compile(
    r"^(?:"
    r"total|rural|urban"
    r"|mcd(?:\s*\(\s*(?:[ur]|urban|rural)\s*\))?"
    r"|ndmc|delhi\s+cantt\.?|cantt\.?"
    r")$",
    re.I,
)


def _is_weak_inferred_title(title: str, columns: Optional[List[str]] = None) -> bool:
    """Reject column-header crumbs (TOTAL, MALE) and bare TABLE ids as titles."""
    s = _normalize_title_line(title)
    if not s:
        return True
    if _is_caption_id_only(s):
        return True
    low = s.lower().rstrip(".")
    if low in _WEAK_TITLE_TOKENS:
        return True
    if len(s.split()) <= 2 and low.replace(" ", "") in {
        t.replace(".", "") for t in _WEAK_TITLE_TOKENS
    }:
        return True
    # Group labels that appear in header_path but not leaf column names.
    for c in columns or []:
        cl = _normalize_title_line(c).lower()
        if cl and (low == cl or low in cl.split()):
            if len(s.split()) <= 2:
                return True
    return False


def _is_column_group_banner(line: str) -> bool:
    """True for in-grid spanning headers that must not become the table title."""
    s = _normalize_title_line(line)
    return bool(s) and bool(_COLUMN_GROUP_BANNER_RE.match(s))


def _is_scope_subtitle(line: str) -> bool:
    """Short geography/population scope under the descriptive caption."""
    s = _normalize_title_line(line)
    if not s:
        return False
    return bool(_SCOPE_SUBTITLE_RE.match(s))


def _is_stub_near_caption(cand: str, col_names: List[str]) -> bool:
    """True for short axis/header stubs between a TABLE id and the real title.

    Vital-stats PDFs often insert lines like ``Months``, ``LOCAL BODY``, or
    ``Rural / Urban / Total`` between ``TABLE-11(i)`` and the descriptive
    caption; those must not win as the title. Spanning group headers such as
    ``LEVELS OF LITERACY`` are also stubs here — they live inside the grid.
    """
    s = _normalize_title_line(cand)
    if not s:
        return True
    if _is_weak_inferred_title(s, col_names):
        return True
    if _is_column_group_banner(s):
        return True
    words = s.split()
    # Real descriptive captions are longer (e.g. "LIVE BIRTHS BY …").
    if len(words) <= 2 and len(s) < 24:
        return True
    if len(s) < 18 and len(words) < 4:
        return True
    return False


def _is_descriptive_caption_candidate(cand: str, col_names: List[str]) -> bool:
    """True when a line is strong enough to be the display title under/near a TABLE id."""
    s = _normalize_title_line(cand)
    if not s or _is_caption_id_only(s) or _is_stub_near_caption(s, col_names):
        return False
    if not _is_usable_inferred_title(s, col_names):
        return False
    if _looks_like_heading(s):
        return True
    # Long ALL-CAPS / Title Case captions that exceed the short heading word cap.
    if len(s) >= 18 and not _matches_extended_caption(s):
        letters = [c for c in s if c.isalpha()]
        if letters and sum(1 for c in letters if c.isupper()) / len(letters) >= 0.35:
            return True
    return False


def _caption_candidate_score(cand: str) -> int:
    """Prefer real captions ("… BY …, 2001") over short leftover headings."""
    s = _normalize_title_line(cand)
    if not s:
        return -10_000
    score = len(s) + 4 * len(s.split())
    if re.search(r"\bby\b", s, re.I):
        score += 50
    if re.search(r"\b20\d{2}\b", s):
        score += 25
    if _is_column_group_banner(s):
        score -= 200
    return score


def _descriptive_line_after_caption_id(
    lines: List[str],
    id_index: int,
    col_names: List[str],
) -> Optional[str]:
    """Pick the descriptive caption that sits directly under ``TABLE -8``."""
    best: Optional[str] = None
    best_score = -10_000
    # Allow several stub/header lines between the id and the real title.
    for j in range(id_index + 1, min(id_index + 12, len(lines))):
        cand = _normalize_title_line(lines[j])
        if not cand:
            continue
        if _is_caption_id_only(cand):
            continue
        if _is_stub_near_caption(cand, col_names):
            continue
        # Stop when we hit the table's own column header row.
        low = cand.lower()
        if col_names and sum(1 for c in col_names[:4] if c and c.lower() in low) >= 2:
            break
        if _is_descriptive_caption_candidate(cand, col_names):
            score = _caption_candidate_score(cand)
            if score > best_score:
                best, best_score = cand, score
    return best


def _descriptive_line_before_caption_id(
    lines: List[str],
    id_index: int,
    col_names: List[str],
) -> Optional[str]:
    """Pick a descriptive caption that sits directly above ``TABLE (ii)``."""
    best: Optional[str] = None
    best_score = -10_000
    for j in range(id_index - 1, max(-1, id_index - 12), -1):
        cand = _normalize_title_line(lines[j])
        if not cand:
            continue
        if _is_caption_id_only(cand):
            continue
        if _is_stub_near_caption(cand, col_names):
            continue
        low = cand.lower()
        if col_names and sum(1 for c in col_names[:4] if c and c.lower() in low) >= 2:
            break
        if _is_descriptive_caption_candidate(cand, col_names):
            score = _caption_candidate_score(cand)
            if score > best_score:
                best, best_score = cand, score
    return best


def _find_line_index(lines: List[str], text: str, near: int) -> int:
    target = _normalize_title_line(text)
    if not target:
        return near
    # Prefer the occurrence closest to the TABLE id.
    best_i, best_dist = near, 10_000
    for i, ln in enumerate(lines):
        if _normalize_title_line(ln) == target:
            dist = abs(i - near)
            if dist < best_dist:
                best_i, best_dist = i, dist
    return best_i


def _scope_subtitle_near(
    lines: List[str],
    id_index: int,
    title: str,
) -> Optional[str]:
    """Find RURAL / DELHI CANTT. / NDMC etc. next to the caption + TABLE id."""
    title_index = _find_line_index(lines, title, id_index)
    lo = min(id_index, title_index)
    hi = max(id_index, title_index)
    # Scope can sit just above the caption, between caption and id, or under both.
    scan = (
        list(range(max(0, lo - 3), lo))
        + list(range(lo, hi + 1))
        + list(range(hi + 1, min(hi + 4, len(lines))))
    )
    for j in scan:
        if j == id_index or j == title_index:
            continue
        cand = _normalize_title_line(lines[j])
        if _is_scope_subtitle(cand) and cand.lower() not in title.lower():
            return cand
    return None


def _descriptive_line_near_caption_id(
    lines: List[str],
    id_index: int,
    col_names: List[str],
) -> Optional[str]:
    """Prefer the strongest caption near the TABLE id; append scope subtitle."""
    after = _descriptive_line_after_caption_id(lines, id_index, col_names)
    before = _descriptive_line_before_caption_id(lines, id_index, col_names)
    if after and before:
        title = (
            after
            if _caption_candidate_score(after) >= _caption_candidate_score(before)
            else before
        )
    else:
        title = after or before
    if not title:
        return None
    scope = _scope_subtitle_near(lines, id_index, title)
    if scope:
        return f"{title} — {scope}"
    return title

def _matches_extended_caption(line: str) -> bool:
    s = _normalize_title_line(line)
    if not s:
        return False
    return any(p.match(s) for p in _EXTENDED_CAPTION_RES)


def build_pdf_outline_index(pdf_path: Union[str, Path]) -> Dict[int, List[str]]:
    """
    Map each 1-based page number to the outline/bookmark breadcrumb active on
    that page (from the PDF TOC). Used as a fallback table title when no
    caption or heading is found above the grid.
    """
    try:
        import pymupdf
    except ImportError:
        return {}

    path = Path(pdf_path)
    if not path.is_file():
        return {}

    doc = pymupdf.open(path)
    try:
        toc = doc.get_toc() or []
        n_pages = doc.page_count
    finally:
        doc.close()

    items = sorted(
        (
            (int(e[0]), _normalize_title_line(str(e[1])), int(e[2]))
            for e in toc
            if isinstance(e, (list, tuple)) and len(e) >= 3 and str(e[1]).strip()
        ),
        key=lambda x: (x[2], x[0]),
    )

    stack: Dict[int, str] = {}
    index: Dict[int, List[str]] = {}
    item_idx = 0
    for page in range(1, n_pages + 1):
        while item_idx < len(items) and items[item_idx][2] <= page:
            lvl, title, _ = items[item_idx]
            stack[lvl] = title
            for deeper in [k for k in stack if k > lvl]:
                del stack[deeper]
            item_idx += 1
        index[page] = [stack[k] for k in sorted(stack)]
    return index


def extract_page_text_blocks(doc: Any, page_num: int) -> List[Dict[str, float]]:
    """
    Positioned text lines from one PDF page. Each block:
      {text, x0, y0, x1, y1} in PDF coordinates (y grows downward).
    """
    if doc is None or page_num is None or page_num < 1:
        return []
    try:
        page = doc[page_num - 1]
        payload = page.get_text("dict") or {}
    except Exception:
        return []

    blocks_out: List[Dict[str, float]] = []
    for block in payload.get("blocks") or []:
        if block.get("type") != 0:
            continue
        for line in block.get("lines") or []:
            spans = line.get("spans") or []
            text = _normalize_title_line("".join(str(s.get("text") or "") for s in spans))
            if not text:
                continue
            bbox = line.get("bbox") or block.get("bbox")
            if not bbox or len(bbox) < 4:
                continue
            blocks_out.append({
                "text": text,
                "x0": float(bbox[0]),
                "y0": float(bbox[1]),
                "x1": float(bbox[2]),
                "y1": float(bbox[3]),
            })
    return blocks_out


def _horizontal_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _blocks_above_bbox(
    page_blocks: List[Dict[str, float]],
    bbox: List[float],
    *,
    max_gap: float = _BBOX_TITLE_MAX_GAP_PT,
) -> List[Tuple[float, Dict[str, float]]]:
    """Text lines above the table, sorted nearest-first (distance to table top)."""
    if not page_blocks or not bbox or len(bbox) < 4:
        return []
    tx0, ty0, tx1, _ty1 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    table_w = max(tx1 - tx0, 1.0)
    h_pad = max(24.0, table_w * 0.12)

    above: List[Tuple[float, Dict[str, float]]] = []
    for b in page_blocks:
        gap = ty0 - float(b["y1"])
        if gap < -4 or gap > max_gap:
            continue
        overlap = _horizontal_overlap(
            float(b["x0"]), float(b["x1"]),
            tx0 - h_pad, tx1 + h_pad,
        )
        if overlap <= 0:
            continue
        above.append((gap, b))
    above.sort(key=lambda t: (t[0], -(t[1]["x1"] - t[1]["x0"])))
    return above


def _title_from_outline_sections(
    sections: Optional[List[str]],
    columns: Optional[List[str]],
) -> Tuple[Optional[str], str]:
    if not sections:
        return None, "heuristic_none"
    filtered = [s for s in sections if s and not _is_chrome_title_line(s)]
    if not filtered:
        return None, "heuristic_none"

    deepest = filtered[-1]
    if len(filtered) >= 2 and len(deepest) < 48:
        parent = filtered[-2]
        if parent.lower() != deepest.lower():
            combo = f"{parent} — {deepest}"
            if _is_usable_inferred_title(combo, columns):
                return combo, "heuristic_pdf_outline"
    if _is_usable_inferred_title(deepest, columns):
        return deepest, "heuristic_pdf_outline"
    return None, "heuristic_none"


def _title_from_bbox_blocks(
    page_blocks: List[Dict[str, float]],
    bbox: List[float],
    col_names: List[str],
) -> Tuple[Optional[str], str, Optional[str]]:
    """Caption or heading immediately above the ruled table region.

    Returns (title, source, banner_table_id). When the nearest caption is an
    id-only line (``TABLE -8``), prefer the descriptive line under it.
    """
    above = _blocks_above_bbox(page_blocks, bbox)
    # Nearest-first search for captions; keep id + following descriptive pair.
    texts_near = [block["text"] for _gap, block in above]

    for i, text in enumerate(texts_near):
        if not _matches_extended_caption(text):
            continue
        if _is_caption_id_only(text):
            desc = _descriptive_line_near_caption_id(texts_near, i, col_names)
            if desc:
                return desc, "heuristic_bbox_caption_below_id", text
            # Bare id alone is not a display title — keep looking.
            continue
        if _is_usable_inferred_title(text, col_names) and not _is_weak_inferred_title(text, col_names):
            if _is_column_group_banner(text):
                continue
            return text, "heuristic_bbox_caption", None

    for _gap, block in above:
        text = block["text"]
        if _is_weak_inferred_title(text, col_names):
            continue
        if _is_column_group_banner(text):
            continue
        if _looks_like_heading(text) and _is_usable_inferred_title(text, col_names):
            return text, "heuristic_bbox_heading", None
    return None, "heuristic_none", None


def _title_from_page_lines(
    lines: List[str],
    col_names: List[str],
) -> Tuple[Optional[str], str, Optional[str]]:
    """Scan plain page lines for TABLE/STATEMENT captions and nearby titles.

    Returns (title, source, banner_table_id).
    """
    for i, ln in enumerate(lines):
        if not _matches_extended_caption(ln):
            continue
        if _is_caption_id_only(ln):
            desc = _descriptive_line_near_caption_id(lines, i, col_names)
            if desc:
                after = _descriptive_line_after_caption_id(lines, i, col_names)
                # Scope suffix (" — RURAL") is added by near(); compare the core.
                core = desc.split(" — ", 1)[0]
                source = (
                    "heuristic_table_caption_below_id"
                    if after and _normalize_title_line(after) == _normalize_title_line(core)
                    else "heuristic_table_caption_above_id"
                )
                return desc, source, ln
            continue
        if (
            _is_usable_inferred_title(ln, col_names)
            and not _is_weak_inferred_title(ln, col_names)
            and not _is_column_group_banner(ln)
        ):
            return ln, "heuristic_table_caption", None

    header_idx = None
    col_lower = {c.lower() for c in col_names[:3] if c}
    for i, ln in enumerate(lines):
        low = ln.lower()
        if col_lower and any(c in low for c in col_lower):
            if sum(1 for c in col_lower if c in low) >= 1:
                header_idx = i
                break
    if header_idx is not None and header_idx > 0:
        for j in range(header_idx - 1, max(-1, header_idx - 8), -1):
            candidate = lines[j]
            if candidate.lower() in col_lower:
                continue
            if _is_weak_inferred_title(candidate, col_names):
                continue
            if _is_column_group_banner(candidate):
                continue
            if _is_caption_id_only(candidate):
                desc = _descriptive_line_near_caption_id(lines, j, col_names)
                if desc:
                    return desc, "heuristic_heading_above_table", candidate
                continue
            if _looks_like_heading(candidate) and _is_usable_inferred_title(candidate, col_names):
                return candidate, "heuristic_heading_above_table", None
    return None, "heuristic_none", None


def _looks_like_heading(line: str) -> bool:
    """Heuristic: short Title Case / ALL CAPS / few words, not a sentence."""
    s = _normalize_title_line(line)
    if _is_chrome_title_line(s):
        return False
    # Truncated wrap from a column header (e.g. "Direc-") is not a heading.
    if re.search(r"[–—\-]$", s):
        return False
    words = s.split()
    # Allow longer captions used as titles (DEATHS BY CAUSE …).
    if not (1 <= len(words) <= 18):
        return False
    # Reject lines that look like the table's own column header row.
    if s.count("|") >= 2:
        return False
    # Prefer Title Case / ALL CAPS; allow mixed if short (e.g. "Target Justification").
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    upper_frac = sum(1 for c in letters if c.isupper()) / len(letters)
    if upper_frac < 0.2 and not s[:1].isupper():
        return False
    return True


def infer_title_from_page_text(
    page_text: str,
    columns: List[str],
    page_num: Optional[int] = None,
    *,
    bbox: Optional[List[float]] = None,
    page_blocks: Optional[List[Dict[str, float]]] = None,
    outline_sections: Optional[List[str]] = None,
) -> Tuple[Optional[str], str]:
    """
    Infer a display title for an auto-accepted (no-LLM) table.

    Strategy (first strong match wins):
      1. Caption/heading positioned above the table bbox (when bbox + blocks known).
      2. Extended caption patterns on the page (TABLE, STATEMENT, ANNEX, …),
         preferring the descriptive line under a bare ``TABLE -8`` id.
      3. Heading-like line above the column-header cue in plain page text.
      4. PDF outline/bookmark breadcrumb for this page (section context).
      5. None — Preview prompts the user to add a title.

    Returns (title, title_source) for debugging in Preview.
    Banner ids are attached separately via ``infer_title_meta_from_page_text``.
    """
    title, source, _banner = infer_title_meta_from_page_text(
        page_text,
        columns,
        page_num,
        bbox=bbox,
        page_blocks=page_blocks,
        outline_sections=outline_sections,
    )
    return title, source


def infer_title_meta_from_page_text(
    page_text: str,
    columns: List[str],
    page_num: Optional[int] = None,
    *,
    bbox: Optional[List[float]] = None,
    page_blocks: Optional[List[Dict[str, float]]] = None,
    outline_sections: Optional[List[str]] = None,
) -> Tuple[Optional[str], str, Optional[str]]:
    """Like ``infer_title_from_page_text`` but also returns ``banner_table_id``."""
    col_names = [_normalize_title_line(c) for c in columns if _normalize_title_line(c)]
    lines = [
        ln for ln in (_normalize_title_line(ln) for ln in (page_text or "").splitlines())
        if ln
    ]

    best: Tuple[Optional[str], str, Optional[str]] = (None, "heuristic_none", None)

    if bbox and page_blocks:
        title, source, banner = _title_from_bbox_blocks(page_blocks, bbox, col_names)
        if title and not _is_weak_inferred_title(title, col_names):
            return strip_caption_label_prefix(title), source, banner
        if banner and not best[0]:
            best = (None, source, banner)

    title, source, banner = _title_from_page_lines(lines, col_names)
    if title and not _is_weak_inferred_title(title, col_names):
        return strip_caption_label_prefix(title), source, banner or best[2]

    title, source = _title_from_outline_sections(outline_sections, col_names)
    if title and not _is_weak_inferred_title(title, col_names):
        return strip_caption_label_prefix(title), source, best[2]

    return best[0], best[1], best[2]


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
