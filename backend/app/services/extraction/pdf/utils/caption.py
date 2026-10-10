"""In-grid caption / banner extraction and shared cell primitives."""

from __future__ import annotations

import math
import re
from typing import Any, List, Optional, Sequence, Tuple

_ROWSPAN_STUBS = {
    "SL", "SL.", "S.NO", "S.NO.", "S NO", "S. NO.", "SL. NO.", "SL.NO.",
    "STATE", "STATES", "STATES/UTS", "STATES / UTS",
    "UT", "UTS", "INDICATOR", "INDICATORS", "NAME", "TOTAL", "ALL",
}

_COL_NUM_RE = re.compile(r"^\(\d+\)$")

_BARE_INDEX_RE = re.compile(r"^\d{1,2}$")

def _row_is_column_number_strip(row: Sequence[Any], n_cols: int) -> bool:
    """True for '(1)(2)(3)' or bare 1..N reference strips under headers."""
    non_empty = [v for v in row if _cell_str(v)]
    if len(non_empty) < 2:
        return False
    paren_hits = sum(1 for v in non_empty if _COL_NUM_RE.match(_cell_str(v)))
    if paren_hits > len(non_empty) * 0.5:
        return True
    if len(non_empty) < max(3, int(n_cols * 0.6)):
        return False
    if not all(_BARE_INDEX_RE.match(_cell_str(v)) for v in non_empty):
        return False
    try:
        nums = [int(_cell_str(v)) for v in non_empty]
    except ValueError:
        return False
    return bool(nums) and nums == list(range(1, len(nums) + 1))

_OPEN_CODE_RE = re.compile(r"^[<>]=?\s*\d+\+?$|^\d+\+$")

_UNIT_GROUP_RE = re.compile(
    r"^(?:in\s+)?(?:lakhs?|thousands?|crores?|millions?|%|percent(?:age)?)$",
    re.IGNORECASE,
)

_TABLE_BANNER_RE = re.compile(
    r"^(?:table\s*[:.\-–—]?\s*[a-z0-9][\w\s.\-–—/]*|"
    r"statement\s*[:.\-–—]?\s*\d+|"
    r"annex(?:ure)?\s*[:.\-–—]?\s*[a-z0-9]+)$",
    re.IGNORECASE,
)

_DOC_KIND_RE = (
    r"(?:TABLE|TAB\.?|STATEMENT|ANNEX(?:URE)?|SCHEDULE|EXHIBIT|APPENDIX)"
)

_TABLE_ID_TOKEN_RE = r"[A-Z0-9][\w.\-–—/]*"

_TABLE_ID_CORE_RE = (
    rf"(?:{_TABLE_ID_TOKEN_RE}(?:\s*\([^)]{{0,48}}\))?|\([^)]{{1,48}}\))"
)

_TABLE_ID_ONLY_RE = re.compile(
    rf"^{_DOC_KIND_RE}\s*[:.\-–—]?\s*{_TABLE_ID_CORE_RE}\s*$",
    re.IGNORECASE,
)

_TABLE_ID_THEN_TITLE_RE = re.compile(
    rf"^(?P<id>{_DOC_KIND_RE}\s*[:.\-–—]?\s*{_TABLE_ID_CORE_RE})"
    rf"(?:\s*[:.\-–—]\s*|\s+)(?P<title>\S.+)$",
    re.IGNORECASE,
)

_LEAF_MAX_LEN = 24

_MEASUREMENT_ABS_MIN = 100

def _cell_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    s = str(v).replace("\n", " ").strip()
    s = re.sub(r"\s+", " ", s)
    if s.lower() in {"nan", "none", "<na>"}:
        return ""
    return s

def _normalize_numeric_token(v: Any) -> str:
    """Strip footnotes/wrappers so '(10.6)' and '*(45.18)' parse as numbers."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if isinstance(v, float) and math.isnan(v):
            return ""
        return str(v)
    s = _cell_str(v).replace(",", "").replace("%", "").replace("*", "").strip()
    # Parenthetical percentages / shares in statistical PDFs.
    if len(s) >= 3 and s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    return s

def _is_numeric_cell(v: Any) -> bool:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if isinstance(v, float) and math.isnan(v):
            return False
        return True
    s = _normalize_numeric_token(v)
    if not s or s in {"-", "—", "–", "Null", "null", "NA", "N/A"}:
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False

def _numeric_abs(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return abs(float(v))
    s = _normalize_numeric_token(v)
    if not s:
        return None
    try:
        return abs(float(s))
    except ValueError:
        return None

def _is_year_code(v: Any) -> bool:
    """Four-digit calendar years used as leaf column labels (2001, 2011, …)."""
    s = _cell_str(v).replace(",", "").strip()
    if not re.fullmatch(r"\d{4}", s):
        return False
    n = _numeric_abs(v)
    return n is not None and 1800 <= n <= 2100

def _is_measurement_number(v: Any) -> bool:
    """Large counts / values that belong in data rows, not leaf header codes."""
    if _is_year_code(v):
        return False
    n = _numeric_abs(v)
    if n is None:
        return False
    if n >= _MEASUREMENT_ABS_MIN:
        return True
    # Multi-decimal measurements (150.54) and parenthetical shares (10.6) are data;
    # plain small ints remain codes.
    s = _normalize_numeric_token(v)
    if re.fullmatch(r"\d+\.\d+", s) and n >= 1:
        return True
    return False

def _is_leaf_header_token(v: Any) -> bool:
    """
    Short token suitable as a leaf column label under a spanning parent.

    Examples that match structurally: 1, 2, >8, Male, Rural, Q1, 2001, 15-19.
    Examples that do not: 0 / blank counts, 1954 as a count, 150.54, long prose.
    """
    s = _cell_str(v)
    if not s or len(s) > _LEAF_MAX_LEN:
        return False
    if _is_year_code(v):
        return True
    if _is_measurement_number(v):
        return False
    if _OPEN_CODE_RE.match(s.replace(" ", "")):
        return True
    if _is_numeric_cell(v):
        n = _numeric_abs(v)
        # Zero is almost never a column code; it is a count that leaks into headers.
        if n is None or n == 0:
            return False
        return n < _MEASUREMENT_ABS_MIN
    # Short text / hyphenated codes (Rural, 15-19, Not stated, …)
    return True

def _is_rowspan_stub(text: str) -> bool:
    u = (text or "").upper().strip()
    if not u:
        return False
    if u in _ROWSPAN_STUBS:
        return True
    if u.startswith("SL") or u.startswith("S.NO") or u.startswith("S. NO"):
        return True
    if u in {"TOTAL", "ALL"}:
        return True
    return False

def _pad_row(row: Sequence[Any], n_cols: int) -> List[Any]:
    cells = list(row)
    if len(cells) < n_cols:
        cells.extend([None] * (n_cols - len(cells)))
    return cells[:n_cols]

def _blank(row: Sequence[Any]) -> bool:
    return not any(_cell_str(v) for v in row)

def _row_is_full_width_banner(row: Sequence[Any]) -> bool:
    """
    Caption / title row that colspans the entire table (e.g. "TABLE: B-10").

    These must be skipped: horizontal fill would copy the caption into every
    column and surface it as a fake parent header_group in Preview.
    """
    cells = list(row)
    if len(cells) < 2:
        return False
    non_empty = [_cell_str(v) for v in cells if _cell_str(v)]
    if not non_empty:
        return False
    unique = {s.upper() for s in non_empty}
    if len(unique) != 1:
        return False
    label = non_empty[0].strip()
    # Classic extract: one non-empty cell, rest empty under a full colspan.
    if len(non_empty) == 1:
        return True
    # Already-filled banner: every (or most) cells repeat the same caption.
    if len(non_empty) >= max(2, int(len(cells) * 0.6)):
        return bool(_TABLE_BANNER_RE.match(label)) or len(label) >= 28
    return bool(_TABLE_BANNER_RE.match(label)) and len(non_empty) >= len(cells) * 0.5

def _row_banner_label(row: Sequence[Any]) -> Optional[str]:
    """Text of a full-width in-grid banner, or None if the row is not one."""
    if not _row_is_full_width_banner(row):
        return None
    non_empty = [_cell_str(v) for v in row if _cell_str(v)]
    return non_empty[0] if non_empty else None

def _is_table_id_only(label: str) -> bool:
    """True for short document-id banners like ``TABLE: B-6`` / ``TABLE- B-1``."""
    s = _cell_str(label)
    return bool(s) and bool(_TABLE_ID_ONLY_RE.match(s))

def _is_descriptive_in_grid_title(label: str) -> bool:
    """
    True when text looks like a descriptive table caption (not a short id,
    unit strip, or stub header word).
    """
    s = _cell_str(label)
    if not s:
        return False
    if _is_table_id_only(s):
        return False
    if _UNIT_GROUP_RE.match(s):
        return False
    if _looks_like_column_list_banner(s):
        return False
    m = _TABLE_ID_THEN_TITLE_RE.match(s)
    if m:
        s = _cell_str(m.group("title"))
        if not s:
            return False
    words = s.split()
    if len(s) < 18 and len(words) < 4:
        return False
    # Single/short stub labels that happen to colspan are not titles.
    if len(words) <= 2 and len(s) < 30:
        return False
    letter_chars = sum(1 for c in s if c.isalpha())
    if letter_chars < max(10, int(len(s) * 0.45)):
        return False
    if sum(1 for w in words if _is_numeric_cell(w)) >= max(2, len(words) // 2):
        return False
    return True

_SUBTITLE_STUB_RE = re.compile(
    r"^(?:"
    r"sl\.?\s*no\.?|s\.?\s*no\.?|sno|total|all|male|female|males|females|"
    r"mother\s*age|birth\s*order|particulars|year|age|sex"
    r")$",
    re.I,
)

def _is_in_grid_subtitle(label: str) -> bool:
    """Short scope/category banner under the main title (e.g. RELIGION-OTHERS).

    These are too short for ``_is_descriptive_in_grid_title`` but still belong
    in the display title so sibling TABLES (same B-15 caption, different
    religion) stay distinguishable.
    """
    s = _cell_str(label)
    if not s:
        return False
    if _is_table_id_only(s) or _UNIT_GROUP_RE.match(s):
        return False
    if _looks_like_column_list_banner(s):
        return False
    if _is_descriptive_in_grid_title(s):
        return True
    if _SUBTITLE_STUB_RE.match(s):
        return False
    words = s.split()
    if len(s) < 4 or len(s) > 64 or len(words) > 8:
        return False
    # Prefer label-like tokens: letters with optional hyphen/paren scope.
    letter_chars = sum(1 for c in s if c.isalpha())
    if letter_chars < 3:
        return False
    if sum(1 for w in words if _is_numeric_cell(w)) >= max(2, len(words) // 2):
        return False
    return True

def _looks_like_column_list_banner(label: str) -> bool:
    """Comma/slash-separated field lists that belong in headers, not titles."""
    s = _cell_str(label)
    if not s:
        return False
    parts = [p.strip() for p in re.split(r"[,;/|]", s) if p.strip()]
    if len(parts) < 2:
        return False
    shortish = sum(1 for p in parts if len(p) <= 40 and len(p.split()) <= 5)
    return shortish >= max(2, len(parts) - 1) and len(s) <= 160

def extract_in_grid_caption(
    rows: Optional[List[List[Any]]],
) -> dict:
    """
    Extract table id + descriptive title from leading full-width banner rows.

    Common in CRS / vital-statistics tables where ``TABLE: B-12`` is the first
    ruled row, the next full-width row is the long caption, and an optional
    subtitle banner follows (e.g. ``MOTHER EDUCATION (NOT STATED)``).

    Returns
      title            – descriptive caption (subtitles joined with " — ")
      table_id_label   – short TABLE/STATEMENT/… id when present
      rows_consumed    – body start index (row after last consumed banner); 0 if none
    """
    out: dict = {"title": None, "table_id_label": None, "rows_consumed": 0}
    if not rows:
        return out
    n_cols = max((len(r) for r in rows), default=0)
    if n_cols < 2:
        return out

    banners: List[Tuple[int, str]] = []
    for i, row in enumerate(rows[:12]):
        padded = _pad_row(row, n_cols)
        if _blank(padded):
            continue
        label = _row_banner_label(padded)
        if label:
            banners.append((i, label))
            continue
        break

    if not banners:
        return out

    def _descriptive_run(start: int) -> List[Tuple[int, str]]:
        """Consecutive descriptive / subtitle banners starting at ``start``."""
        run: List[Tuple[int, str]] = []
        for pair in banners[start:]:
            _idx, b = pair
            if _is_table_id_only(b) or _UNIT_GROUP_RE.match(b):
                break
            # Primary long caption OR short scope line (RELIGION-OTHERS, URBAN).
            if _is_descriptive_in_grid_title(b) or _is_in_grid_subtitle(b):
                run.append(pair)
                continue
            break
        return run

    def _finish(
        table_id: Optional[str],
        title_pairs: List[Tuple[int, str]],
        fallback_end_i: int,
    ) -> dict:
        out["table_id_label"] = table_id
        if title_pairs:
            # Prefer a primary caption. Do not swallow column-list banners
            # (e.g. "Scheme name, beneficiaries, budget") into the title — those
            # must remain in the body so headers/data extract correctly.
            # Allow one short subtitle (RELIGION-OTHERS / URBAN) and/or wrapped
            # title continuations under the main caption.
            kept: List[Tuple[int, str]] = []
            used_subtitle = False
            wrap_continuation = False
            for i, pair in enumerate(title_pairs):
                _idx, lab = pair
                if i == 0:
                    kept.append(pair)
                    continue
                if _looks_like_column_list_banner(lab):
                    break
                prev = kept[-1][1]
                # Mid-phrase wrap: previous banner ends with a connector word.
                if (
                    re.search(r"\b(?:FOR|AND|OF|THE|BY|WITH|TO|IN|OR|NOT|A|AN)\s*$", prev, re.I)
                    and (_is_descriptive_in_grid_title(lab) or _is_in_grid_subtitle(lab))
                ):
                    kept.append(pair)
                    wrap_continuation = True
                    continue
                short_subtitle = (
                    _is_in_grid_subtitle(lab)
                    and len(lab) <= 48
                    and lab.count(",") < 2
                    and len(lab.split()) <= 8
                )
                if short_subtitle and not used_subtitle and not wrap_continuation:
                    kept.append(pair)
                    used_subtitle = True
                    break
                # Long descriptive follow-on = wrapped title continuation.
                if _is_descriptive_in_grid_title(lab) and len(prev) >= 40:
                    kept.append(pair)
                    wrap_continuation = True
                    continue
                break
            if kept:
                primary = kept[0][1]
                rest = [lab for _i, lab in kept[1:]]
                if not rest:
                    out["title"] = primary
                elif wrap_continuation:
                    out["title"] = " ".join([primary, *rest])
                else:
                    out["title"] = " — ".join([primary, *rest])
                out["rows_consumed"] = kept[-1][0] + 1
            else:
                out["rows_consumed"] = fallback_end_i + 1
        else:
            out["rows_consumed"] = fallback_end_i + 1
        return out

    labels = [lab for _i, lab in banners]
    first = labels[0]

    if _is_table_id_only(first):
        return _finish(first, _descriptive_run(1), banners[0][0])

    combined = _TABLE_ID_THEN_TITLE_RE.match(first)
    if combined:
        title_part = _cell_str(combined.group("title"))
        if _is_descriptive_in_grid_title(title_part):
            # Treat combined cell as the first title part, then more banners.
            rest = _descriptive_run(1)
            pairs = [(banners[0][0], title_part)] + rest
            return _finish(_cell_str(combined.group("id")), pairs, banners[0][0])

    if _is_descriptive_in_grid_title(first):
        return _finish(None, _descriptive_run(0), banners[0][0])

    for i, b in enumerate(labels):
        if not _is_table_id_only(b):
            continue
        return _finish(b, _descriptive_run(i + 1), banners[i][0])

    # Leading full-width rows we couldn't classify — skip so they aren't headers.
    return _finish(None, [], banners[-1][0])

__all__ = [
    "_is_descriptive_in_grid_title",
    "_is_in_grid_subtitle",
    "_is_measurement_number",
    "_is_numeric_cell",
    "_is_table_id_only",
    "extract_in_grid_caption",
]
