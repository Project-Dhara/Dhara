"""
Repair vertically stacked / rotated column-header labels in PDF tables.

Government crop / census tables often draw leaf headers (Autumn, Maize, …)
rotated 90° or as one upright glyph per line inside a tall narrow cell.
PyMuPDF ``Table.extract()`` then yields empty cells, reversed words,
space-separated letters (``A n t u m n``), or newline-broken words
(``Sl.\\nN\\no.``, ``Grand\\ntotal``). This module rebuilds those header
cells before multi-level header detection runs.

Important: page-geometry rebuild must be gated. Merged (colspan) header
cells have wide bboxes that swallow neighbouring text / body numbers, so
blind ``get_text`` rebuilds can *corrupt* already-correct labels like
``Paddy``. Prefer normalizing the extract cell; only fall back to page
geometry when the cell is empty or clearly stacked/letter-spaced.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.extraction.pdf.utils.caption import (
    _cell_str,
    _is_measurement_number,
    _is_numeric_cell,
    _pad_row,
    _row_is_column_number_strip,
)

# Steward-facing note when rotated/stacked headers were rebuilt (or still shaky).
VERTICAL_HEADER_REVIEW_NOTE = (
    "Some column headers were rotated or stacked in the PDF — "
    "we rebuilt those labels. Please confirm they match the source."
)

VERTICAL_HEADER_STILL_BAD_NOTE = (
    "Some column headers still look rotated or letter-spaced after automatic "
    "repair. Please fix the names so they match the PDF."
)

# Common leaf / group tokens in Indian statistical crop & vital-stats tables.
_KNOWN_HEADER_FRAGMENTS = (
    "autumn", "winter", "summer", "total", "grand", "paddy", "wet", "dry",
    "grains", "cereals", "millets", "pulses", "maize", "wheat", "bajra",
    "ragi", "cholam", "jowar", "jower", "gram", "tur", "redgram", "district",
    "koovaraku", "koovaragu", "thina", "chama", "finger", "millet", "sugar",
    "pepper", "ginger", "turmeric", "cardamom", "cardamum", "arecanut",
    "male", "female", "rural", "urban", "birth", "death", "year", "month",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "sl", "no", "name",
    "forest", "fallow", "geographical",
)

_VOWELS = set("aeiouAEIOU")
_STACKED_TOKEN_RE = re.compile(r"^[A-Za-z0-9/%.*]+$")
_SL_NO_BROKEN_RE = re.compile(
    r"^S\.?\s*l\.?\s*N\s*o\.?\.?$",
    re.IGNORECASE,
)
# Reject rebuilds that swallowed body digits / watermarks.
_MAX_HEADER_LEN = 64


def _tokens(text: str) -> List[str]:
    return [t for t in re.split(r"\s+", str(text or "").strip()) if t]


def looks_like_stacked_letter_cell(text: Any) -> bool:
    """True when a cell looks like one letter (or digraph) per line/token."""
    raw = str(text or "").strip()
    if not raw:
        return False
    # Prefer newline evidence before _cell_str collapses whitespace.
    parts = [p for p in re.split(r"[\n\r]+", raw) if p.strip()]
    if len(parts) >= 3:
        short = sum(1 for p in parts if len(p.strip()) <= 2)
        if short >= max(3, int(len(parts) * 0.7)):
            return True
    toks = _tokens(raw.replace("\n", " "))
    if len(toks) < 3:
        return False
    short = sum(
        1 for t in toks
        if len(t) <= 2 and _STACKED_TOKEN_RE.match(t)
    )
    return short >= max(3, int(len(toks) * 0.7))


def looks_like_newline_broken_words(text: Any) -> bool:
    """True for vertical word wraps like ``Grand\\ntotal`` or ``Sl.\\nN\\no.``."""
    raw = str(text or "").strip()
    if "\n" not in raw and "\r" not in raw:
        return False
    if looks_like_stacked_letter_cell(raw):
        return True
    parts = [p.strip() for p in re.split(r"[\n\r]+", raw) if p.strip()]
    if len(parts) < 2:
        return False
    # Each fragment is a short word / stub — not a full paragraph.
    return all(1 <= len(p) <= 24 for p in parts) and sum(len(p) for p in parts) <= _MAX_HEADER_LEN


def is_plausible_header_label(text: Any) -> bool:
    """False for digit-heavy / watermark / colspan-bleed garbage."""
    s = re.sub(r"\s+", " ", str(text or "").replace("\n", " ")).strip()
    if not s:
        return False
    if len(s) > _MAX_HEADER_LEN:
        return False
    letters = sum(1 for c in s if c.isalpha())
    digits = sum(1 for c in s if c.isdigit())
    if digits and letters and digits >= max(3, int(letters * 0.35)):
        return False
    # Long run of digits with almost no spaces (body bleed).
    if re.search(r"\d{6,}", s):
        return False
    if letters < 1 and not re.fullmatch(r"[\d().\-\s/%]+", s):
        return False
    return True


def score_header_label(text: str) -> float:
    """Higher is more likely a natural header label (vs reversed / spaced letters)."""
    s = re.sub(r"\s+", " ", str(text or "").strip())
    if not s:
        return -1.0
    if not is_plausible_header_label(s):
        return -2.0

    letters = [c for c in s if c.isalpha()]
    if not letters:
        # Bare numbers / index strips are fine but not "repaired" labels.
        return 0.15 if re.fullmatch(r"[\d().\-\s]+", s) else 0.0

    score = 0.0
    toks = _tokens(s)
    # Heavy penalty: letter-spaced "A n t u m n"
    if len(toks) >= 3 and sum(1 for t in toks if len(t) == 1) >= len(toks) - 1:
        score -= 1.5
    else:
        score += min(len(letters), 12) * 0.05

    vowel_ratio = sum(1 for c in letters if c in _VOWELS) / len(letters)
    # Natural English/Indic-latin labels cluster ~0.25–0.55 vowels.
    score += 1.0 - abs(vowel_ratio - 0.38) * 2.0

    low = s.lower()
    # Whole-word / bounded fragment match — avoid scoring "…Autumn…" inside garbage.
    for frag in _KNOWN_HEADER_FRAGMENTS:
        if re.search(rf"(?<![a-z0-9]){re.escape(frag)}(?![a-z0-9])", low):
            score += 0.55
            break

    # Prefer starting with a letter (not a stray glyph).
    if s[0].isalpha():
        score += 0.15
    # Penalty for many internal spaces in a short label.
    if len(letters) <= 14 and s.count(" ") >= 2:
        score -= 0.35
    # Broken "Sl. N o." is worse than "Sl. No."
    if re.search(r"\bN\s+o\.?\b", s) and re.search(r"\bSl\.?\b", s, re.I):
        score -= 0.4
    return score


def collapse_stacked_header_cell(text: Any) -> str:
    """Join stacked single-character header glyphs; pick forward vs reverse."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    if not looks_like_stacked_letter_cell(raw):
        return normalize_multiline_header_cell(raw)

    parts = [p.strip() for p in re.split(r"[\n\r]+", raw) if p.strip()]
    if len(parts) < 3:
        parts = _tokens(raw.replace("\n", " "))
    # Drop empty / whitespace-only fragments (tabs from bad fixtures, etc.).
    parts = [p for p in parts if p and not p.isspace()]
    if not parts:
        return ""
    # Keep short tokens only; longer tokens stay as words in the join.
    forward = "".join(parts)
    reverse = "".join(reversed(parts))
    # Also try space-joined words when some parts are digraphs ("Sl", "No").
    forward_spaced = " ".join(parts) if any(len(p) > 1 for p in parts) else forward
    reverse_spaced = (
        " ".join(reversed(parts)) if any(len(p) > 1 for p in parts) else reverse
    )
    candidates = [forward, reverse, forward_spaced, reverse_spaced]
    # Deduplicate while preserving order.
    seen = set()
    uniq: List[str] = []
    for c in candidates:
        c = re.sub(r"\s+", " ", c).strip()
        if not c or c in seen:
            continue
        seen.add(c)
        uniq.append(c)
    return max(uniq, key=score_header_label)


def normalize_multiline_header_cell(text: Any) -> str:
    """Join newline-broken header words; fix common ``Sl. No.`` splits."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    if looks_like_stacked_letter_cell(raw):
        return collapse_stacked_header_cell(raw)

    parts = [p.strip() for p in re.split(r"[\n\r]+", raw) if p.strip()]
    if len(parts) >= 2:
        joined = " ".join(parts)
    else:
        joined = raw.replace("\n", " ").replace("\r", " ")
    joined = re.sub(r"\s+", " ", joined).strip()

    # ``Sl. N o.`` / ``Sl. No`` / ``S l. N o.`` → ``Sl. No.``
    compact = re.sub(r"\s+", "", joined)
    if _SL_NO_BROKEN_RE.match(compact) or re.match(
        r"^S\.?l\.?\s*N\s*o\.?\.?$", joined, re.I
    ):
        return "Sl. No."
    joined = re.sub(r"\bSl\.?\s+N\s+o\.?\b", "Sl. No.", joined, flags=re.I)
    joined = re.sub(r"\bS\.\s*No\.?\b", "S. No.", joined, flags=re.I)
    return joined


def cell_needs_vertical_repair(text: Any) -> bool:
    """Whether extract text should be normalized / optionally rebuilt."""
    raw = str(text or "").strip()
    if not raw:
        return True
    if looks_like_stacked_letter_cell(raw):
        return True
    if looks_like_newline_broken_words(raw):
        return True
    # Already-flattened awkward serial: "Sl. N o."
    norm = re.sub(r"\s+", " ", raw.replace("\n", " "))
    if re.search(r"\bSl\.?\s+N\s+o\.?\b", norm, re.I):
        return True
    return False


def _row_is_dataish(row: Sequence[Any], n_cols: int) -> bool:
    padded = _pad_row(row, n_cols)
    non_empty = [v for v in padded if _cell_str(v)]
    if len(non_empty) < max(2, int(n_cols * 0.25)):
        return False
    measures = sum(1 for v in non_empty if _is_measurement_number(v))
    nums = sum(1 for v in non_empty if _is_numeric_cell(v))
    if measures >= 2:
        return True
    if nums >= max(3, int(len(non_empty) * 0.55)) and not _row_is_column_number_strip(
        padded, n_cols
    ):
        return True
    return False


def header_band_row_count(rows: Sequence[Sequence[Any]]) -> int:
    """Rows from the top that still look like headers / index strips."""
    if not rows:
        return 0
    n_cols = max((len(r) for r in rows), default=0)
    if n_cols == 0:
        return 0
    # Cap: never treat more than half the table as header, or 8 rows.
    limit = min(len(rows), max(3, min(8, len(rows) // 2 + 1)))
    band = 0
    for i in range(limit):
        if _row_is_dataish(rows[i], n_cols):
            break
        band = i + 1
    # Always keep at least the first row when present.
    return max(band, 1 if rows else 0)


def _cell_bbox_from_table(tab: Any, row_idx: int, col_idx: int) -> Optional[Tuple[float, float, float, float]]:
    try:
        rows = getattr(tab, "rows", None) or []
        if row_idx < 0 or row_idx >= len(rows):
            return None
        cells = getattr(rows[row_idx], "cells", None) or []
        if col_idx < 0 or col_idx >= len(cells):
            return None
        cell = cells[col_idx]
        if cell is None:
            return None
        return (float(cell[0]), float(cell[1]), float(cell[2]), float(cell[3]))
    except Exception:
        return None


def _clip_is_wide_merged(clip: Tuple[float, float, float, float]) -> bool:
    """True for colspan-wide header cells — unsafe for page-text rebuild."""
    x0, y0, x1, y1 = clip
    width = max(x1 - x0, 1.0)
    height = max(y1 - y0, 1.0)
    # Wet/Dry/Paddy parents are short and very wide; leaf vertical cells are tall.
    return width >= height * 2.2 or width >= 120.0


def _chars_in_clip(page: Any, clip: Tuple[float, float, float, float]) -> List[Dict[str, Any]]:
    """Collect characters (or span fallbacks) whose centres lie inside the clip."""
    import pymupdf

    x0, y0, x1, y1 = clip
    # Tight pad — loose pads pull neighbouring columns / body digits.
    pad = 0.75
    rect = pymupdf.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
    out: List[Dict[str, Any]] = []
    try:
        raw = page.get_text("rawdict", clip=rect) or {}
    except Exception:
        raw = {}
    for block in raw.get("blocks") or []:
        if block.get("type") != 0:
            continue
        for line in block.get("lines") or []:
            direction = line.get("dir") or (1.0, 0.0)
            dx = float(direction[0])
            dy = float(direction[1])
            for span in line.get("spans") or []:
                chars = span.get("chars")
                if chars:
                    for ch in chars:
                        c = str(ch.get("c") or "")
                        if not c or c.isspace():
                            continue
                        bb = ch.get("bbox") or span.get("bbox") or (0, 0, 0, 0)
                        cx = (float(bb[0]) + float(bb[2])) / 2.0
                        cy = (float(bb[1]) + float(bb[3])) / 2.0
                        if not (x0 - pad <= cx <= x1 + pad and y0 - pad <= cy <= y1 + pad):
                            continue
                        out.append({
                            "c": c,
                            "x0": float(bb[0]),
                            "y0": float(bb[1]),
                            "x1": float(bb[2]),
                            "y1": float(bb[3]),
                            "dx": dx,
                            "dy": dy,
                        })
                else:
                    text = str(span.get("text") or "")
                    if not text.strip():
                        continue
                    bb = span.get("bbox") or (0, 0, 0, 0)
                    cx = (float(bb[0]) + float(bb[2])) / 2.0
                    cy = (float(bb[1]) + float(bb[3])) / 2.0
                    if not (x0 - pad <= cx <= x1 + pad and y0 - pad <= cy <= y1 + pad):
                        continue
                    out.append({
                        "c": text,
                        "x0": float(bb[0]),
                        "y0": float(bb[1]),
                        "x1": float(bb[2]),
                        "y1": float(bb[3]),
                        "dx": dx,
                        "dy": dy,
                    })
    return out


def _is_vertical_char_set(chars: Sequence[Dict[str, Any]], clip: Tuple[float, float, float, float]) -> bool:
    if not chars:
        return False
    vert_dir = sum(1 for ch in chars if abs(ch["dy"]) > abs(ch["dx"]) + 1e-6)
    if vert_dir >= max(1, int(len(chars) * 0.5)):
        return True
    x0, y0, x1, y1 = clip
    width = max(x1 - x0, 1.0)
    height = max(y1 - y0, 1.0)
    # Tall narrow cell with many short glyphs stacked by y.
    if height >= width * 1.35 and len(chars) >= 3:
        single = sum(1 for ch in chars if len(str(ch["c"])) <= 2)
        if single >= max(3, int(len(chars) * 0.65)):
            return True
    return False


def rebuild_cell_text_from_page(
    page: Any,
    clip: Tuple[float, float, float, float],
) -> str:
    """Rebuild a cell string from page text, honouring vertical runs."""
    if _clip_is_wide_merged(clip):
        return ""
    chars = _chars_in_clip(page, clip)
    if not chars:
        return ""

    if not _is_vertical_char_set(chars, clip):
        # Horizontal: top-to-bottom, left-to-right within similar y.
        chars_sorted = sorted(chars, key=lambda ch: (round(ch["y0"], 1), ch["x0"]))
        parts = [str(ch["c"]) for ch in chars_sorted]
        text = re.sub(r"\s+", " ", "".join(parts)).strip()
        return text if is_plausible_header_label(text) else ""

    # Vertical: try bottom→top (common for 90° CCW labels) and top→bottom.
    by_y_asc = sorted(chars, key=lambda ch: (ch["y0"], ch["x0"]))
    by_y_desc = list(reversed(by_y_asc))
    # Also sort along the dominant writing direction when dir is vertical.
    avg_dy = sum(ch["dy"] for ch in chars) / len(chars)
    if avg_dy < -0.2:
        # Text progresses upward.
        primary = by_y_desc
        secondary = by_y_asc
    elif avg_dy > 0.2:
        primary = by_y_asc
        secondary = by_y_desc
    else:
        primary = by_y_desc
        secondary = by_y_asc

    candidates = [
        "".join(str(ch["c"]) for ch in primary),
        "".join(str(ch["c"]) for ch in secondary),
        " ".join(str(ch["c"]) for ch in primary),
        " ".join(str(ch["c"]) for ch in secondary),
    ]
    # Collapse accidental spaces between single letters after join.
    cleaned: List[str] = []
    for c in candidates:
        c1 = re.sub(r"\s+", " ", c).strip()
        if c1:
            cleaned.append(c1)
        if looks_like_stacked_letter_cell(c1):
            collapsed = collapse_stacked_header_cell(c1)
            if collapsed:
                cleaned.append(collapsed)
        else:
            normalized = normalize_multiline_header_cell(c1)
            if normalized:
                cleaned.append(normalized)
    cleaned = [c for c in cleaned if c and is_plausible_header_label(c)]
    if not cleaned:
        return ""
    return max(cleaned, key=score_header_label)


def _pick_better_cell(existing: Any, *alts: str) -> Tuple[Any, bool]:
    """Choose the best-scoring label among existing + alternatives."""
    base = str(existing) if existing is not None else ""
    options = [base] + [a for a in alts if a]
    # Always consider normalized / collapsed forms of whatever we have.
    options.append(normalize_multiline_header_cell(base))
    if looks_like_stacked_letter_cell(base):
        options.append(collapse_stacked_header_cell(base))
    scored = []
    seen = set()
    for opt in options:
        s = re.sub(r"\s+", " ", str(opt or "").replace("\n", " ")).strip()
        if not s or s in seen:
            continue
        if not is_plausible_header_label(s) and s != re.sub(r"\s+", " ", base.replace("\n", " ")).strip():
            # Never promote implausible rebuilds over anything.
            continue
        seen.add(s)
        scored.append((score_header_label(s), s))
    if not scored:
        return existing, False
    scored.sort(key=lambda t: t[0], reverse=True)
    best_score, best = scored[0]
    base_norm = re.sub(r"\s+", " ", base.replace("\n", " ")).strip()
    base_score = score_header_label(base_norm) if base_norm else -1.0

    # Empty / implausible base: take any plausible improvement.
    if not base_norm or not is_plausible_header_label(base_norm):
        if best and is_plausible_header_label(best) and best != base_norm:
            return best, True
        return existing, False

    if best == base_norm:
        # Still allow newline → space normalization for display.
        normalized = normalize_multiline_header_cell(base)
        if normalized and normalized != base and normalized == best:
            return best, True
        return existing, False

    # Require a clear win; never replace a clean single-line label with a longer one.
    if "\n" not in base and "\r" not in base and not looks_like_stacked_letter_cell(base):
        if not cell_needs_vertical_repair(base) and is_plausible_header_label(base_norm):
            # Only allow pure normalization (Sl. N o. → Sl. No.).
            if normalize_multiline_header_cell(base_norm) == best and best != base_norm:
                return best, True
            return existing, False

    if best_score < base_score + 0.2:
        if cell_needs_vertical_repair(base) and best != base_norm and is_plausible_header_label(best):
            return best, True
        return existing, False
    return best, True


def repair_vertical_header_rows(
    rows: List[List[Any]],
    *,
    page: Any = None,
    tab: Any = None,
) -> Tuple[List[List[Any]], Dict[str, Any]]:
    """
    Repair rotated / stacked header cells in the top header band.

    Returns (new_rows, meta) where meta includes ``repaired_cells`` count and
    ``repaired`` bool for callers that want to stamp a review note.
    """
    if not rows:
        return rows, {"repaired": False, "repaired_cells": 0}

    n_cols = max(len(r) for r in rows)
    band = header_band_row_count(rows)
    out = [_pad_row(r, n_cols) for r in rows]
    repaired_cells = 0

    # Optional second extract with opposite vertical reading direction.
    alt_rows: Optional[List[List[Any]]] = None
    if tab is not None:
        try:
            alt_rows = tab.extract(vertical_ttb=True)
        except TypeError:
            # Older kwargs surface — ignore.
            alt_rows = None
        except Exception:
            alt_rows = None

    for r in range(band):
        # Never "repair" the 1..N / 3..25 index strip under headers.
        if _row_is_column_number_strip(out[r], n_cols):
            continue
        for c in range(n_cols):
            current = out[r][c]
            if not cell_needs_vertical_repair(current):
                # Still allow mild normalization only (rare).
                normalized = normalize_multiline_header_cell(current)
                cur_flat = re.sub(r"\s+", " ", str(current or "").replace("\n", " ")).strip()
                if normalized and normalized != cur_flat and is_plausible_header_label(normalized):
                    if score_header_label(normalized) >= score_header_label(cur_flat) + 0.15:
                        out[r][c] = normalized
                        repaired_cells += 1
                continue

            alts: List[str] = []
            # Primary: normalize / collapse the extract string (safe).
            alts.append(normalize_multiline_header_cell(current))
            if looks_like_stacked_letter_cell(current):
                alts.append(collapse_stacked_header_cell(current))

            # Secondary: alternate extract reading direction (cell-scoped).
            if alt_rows is not None and r < len(alt_rows) and c < len(alt_rows[r]):
                alt = alt_rows[r][c]
                if alt is not None and str(alt).strip():
                    alts.append(normalize_multiline_header_cell(alt))
                    if looks_like_stacked_letter_cell(alt):
                        alts.append(collapse_stacked_header_cell(alt))

            # Tertiary: page geometry — only when still empty / letter-stacked
            # after normalize, and never on wide colspan parent cells.
            normalized_now = normalize_multiline_header_cell(current)
            still_bad = (
                not _cell_str(normalized_now)
                or looks_like_stacked_letter_cell(normalized_now)
                or not is_plausible_header_label(normalized_now)
            )
            if still_bad and page is not None and tab is not None:
                clip = _cell_bbox_from_table(tab, r, c)
                if clip is not None and not _clip_is_wide_merged(clip):
                    rebuilt = rebuild_cell_text_from_page(page, clip)
                    if rebuilt and is_plausible_header_label(rebuilt):
                        alts.append(rebuilt)

            picked, changed = _pick_better_cell(current, *alts)
            if changed:
                out[r][c] = picked
                repaired_cells += 1

    meta = {
        "repaired": repaired_cells > 0,
        "repaired_cells": repaired_cells,
        "header_band_rows": band,
    }
    return out, meta


def headers_still_look_stacked(column_names: Sequence[Any]) -> bool:
    """True when any column name still looks like stacked / letter-spaced glyphs."""
    for name in column_names or []:
        raw = str(name or "")
        if looks_like_stacked_letter_cell(raw):
            return True
        if re.search(r"\bSl\.?\s+N\s+o\.?\b", raw, re.I):
            return True
        # Path-style names from flatten: "Wet Paddy / A u t u m n"
        for part in re.split(r"\s*/\s*", raw):
            if looks_like_stacked_letter_cell(part):
                return True
    return False


def df_had_vertical_header_repair(df: Any) -> bool:
    try:
        return bool(getattr(df, "attrs", {}).get("dhara_vertical_headers_repaired"))
    except Exception:
        return False


__all__ = [
    "VERTICAL_HEADER_REVIEW_NOTE",
    "VERTICAL_HEADER_STILL_BAD_NOTE",
    "cell_needs_vertical_repair",
    "collapse_stacked_header_cell",
    "df_had_vertical_header_repair",
    "header_band_row_count",
    "headers_still_look_stacked",
    "is_plausible_header_label",
    "looks_like_newline_broken_words",
    "looks_like_stacked_letter_cell",
    "normalize_multiline_header_cell",
    "rebuild_cell_text_from_page",
    "repair_vertical_header_rows",
    "score_header_label",
]
