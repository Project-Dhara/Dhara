"""
Deterministic (no-LLM) confidence scoring for extracted table candidates.

The OpenAI validation step in sda_india_pdf_extraction.py is doing real
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

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

MIN_ROWS = 2
MIN_NONEMPTY_RATIO = 0.5
MIXED_TYPE_LOW = 0.2
MIXED_TYPE_HIGH = 0.8


def _cell_str(v: Any) -> str:
    return "" if v is None else re.sub(r"\s+", " ", str(v)).strip()


def _is_numeric_cell(v: str) -> bool:
    s = v.replace(",", "").rstrip("%").strip()
    if not s or s in {"-", "—", "NA", "N/A"}:
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def clean_dataframe_light(df: pd.DataFrame) -> pd.DataFrame:
    """Whitespace-normalize cells, blank out empty strings, drop fully-empty
    rows/columns. Pure Python cleanup -- no LLM, no restructuring."""
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
    cleaned = cleaned.dropna(axis=0, how="all").dropna(axis=1, how="all")
    cleaned = cleaned.reset_index(drop=True)
    if meta and len(meta) == len(before_cols):
        kept = set(str(c) for c in cleaned.columns)
        cleaned.attrs["dhara_column_meta"] = [
            meta[i] for i, name in enumerate(before_cols) if str(name) in kept
        ]
    elif meta:
        cleaned.attrs["dhara_column_meta"] = meta
    if caption:
        cleaned.attrs["dhara_table_caption"] = caption
    if banner_id:
        cleaned.attrs["dhara_banner_table_id"] = banner_id
    return cleaned


def profile_table(df: pd.DataFrame) -> Dict[str, Any]:
    n_rows, n_cols = df.shape
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
        nonempty = [v for v in vals if v]
        if len(nonempty) < 3:
            continue
        if _is_stub_code_column(nonempty):
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


def _is_stub_code_column(nonempty: List[str]) -> bool:
    """Group/S.No.-style codes (1, a, (b)) look mixed numeric/text but are labels."""
    if len(nonempty) < 3:
        return False
    return all(len(v) <= 4 for v in nonempty)


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
_EXTENDED_CAPTION_RES = (
    _TABLE_CAPTION_RE,
    re.compile(
        r"^\s*(?:TABLE|TAB\.?)\s*[:.\-–—]?\s*[A-Z0-9][\w.\-–—/]*(?:\s*[:.\-–—]\s*.+)?$",
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
# Max vertical gap (PDF points) between caption/heading and table top.
_BBOX_TITLE_MAX_GAP_PT = 140.0


def _normalize_title_line(line: str) -> str:
    return re.sub(r"\s+", " ", (line or "").strip())


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
) -> Tuple[Optional[str], str]:
    """Caption or heading immediately above the ruled table region."""
    for _gap, block in _blocks_above_bbox(page_blocks, bbox):
        text = block["text"]
        if _matches_extended_caption(text) and _is_usable_inferred_title(text, col_names):
            return text, "heuristic_bbox_caption"
    for _gap, block in _blocks_above_bbox(page_blocks, bbox):
        text = block["text"]
        if _looks_like_heading(text) and _is_usable_inferred_title(text, col_names):
            return text, "heuristic_bbox_heading"
    return None, "heuristic_none"


def _title_from_page_lines(
    lines: List[str],
    col_names: List[str],
) -> Tuple[Optional[str], str]:
    for ln in lines:
        if _matches_extended_caption(ln) and _is_usable_inferred_title(ln, col_names):
            return ln, "heuristic_table_caption"

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
            if _looks_like_heading(candidate) and _is_usable_inferred_title(candidate, col_names):
                return candidate, "heuristic_heading_above_table"
    return None, "heuristic_none"


def _looks_like_heading(line: str) -> bool:
    """Heuristic: short Title Case / ALL CAPS / few words, not a sentence."""
    s = _normalize_title_line(line)
    if _is_chrome_title_line(s):
        return False
    # Truncated wrap from a column header (e.g. "Direc-") is not a heading.
    if re.search(r"[–—\-]$", s):
        return False
    words = s.split()
    if not (1 <= len(words) <= 12):
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

    Strategy (first match wins):
      1. Caption/heading positioned above the table bbox (when bbox + blocks known).
      2. Extended caption patterns on the page (TABLE, STATEMENT, ANNEX, …).
      3. Heading-like line above the column-header cue in plain page text.
      4. PDF outline/bookmark breadcrumb for this page (section context).
      5. None — Preview prompts the user to add a title.

    Returns (title, title_source) for debugging in Preview.
    """
    col_names = [_normalize_title_line(c) for c in columns if _normalize_title_line(c)]
    lines = [
        ln for ln in (_normalize_title_line(ln) for ln in (page_text or "").splitlines())
        if ln
    ]

    if bbox and page_blocks:
        title, source = _title_from_bbox_blocks(page_blocks, bbox, col_names)
        if title:
            return title, source

    title, source = _title_from_page_lines(lines, col_names)
    if title:
        return title, source

    title, source = _title_from_outline_sections(outline_sections, col_names)
    if title:
        return title, source

    return None, "heuristic_none"


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
    meta = []
    try:
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
    if in_grid_title:
        title, title_source = in_grid_title, "heuristic_in_grid_banner"
    else:
        title, title_source = infer_title_from_page_text(
            page_text,
            col_names,
            page_num=page_num,
            bbox=bbox,
            page_blocks=page_blocks,
            outline_sections=outline_sections,
        )
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
        # human_review_needed is always False here, not merely defaulted: this
        # flag means "an existing AI decision needs a human look," and this
        # path has made no semantic decisions at all yet to review -- it is
        # NOT a signal that classification hasn't happened (that's
        # semantic_status's job). See derive_human_review_needed for the
        # equivalent (and only other) place this flag gets computed.
        "human_review_needed": False,
        "human_review_reason": None,
        "extraction": {"method": method or "pymupdf_lines_strict", "confidence": "high"},
        "source": "auto_high_confidence",
    }
    if in_grid_banner_id:
        result["banner_table_id"] = in_grid_banner_id
    return result
