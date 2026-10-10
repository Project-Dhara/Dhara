"""Title / caption inference for PDF table candidates."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

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

_TABLE_CAPTION_RE = re.compile(
    r"^\s*(TABLE|FIG(?:URE)?|CHART)\s+\d+(?:\.\d+)*\s*[:.\-–—]?\s*(.+)$",
    re.I,
)

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
    from app.services.extraction.pdf.utils.header_utils import _is_table_id_only

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

_WEAK_TITLE_TOKENS = frozenset({
    "total", "totals", "all", "male", "female", "males", "females",
    "rural", "urban", "s.no", "s.no.", "sno", "sl", "sl.", "no", "no.",
    "year", "age", "sex", "gender", "unit", "units", "particulars",
    "month", "months", "order", "local body", "birth order",
})

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

__all__ = [
    "_descriptive_line_after_caption_id",
    "_descriptive_line_near_caption_id",
    "_is_caption_id_only",
    "_is_column_group_banner",
    "_is_weak_inferred_title",
    "_matches_extended_caption",
    "_title_from_page_lines",
    "build_pdf_outline_index",
    "collapse_doubled_pdf_glyphs",
    "extract_page_text_blocks",
    "infer_title_from_page_text",
    "infer_title_meta_from_page_text",
    "strip_caption_label_prefix",
    "title_needs_review",
]
