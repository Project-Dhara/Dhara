"""
PyMuPDF PDF table extraction (data ingestion).

Page scan → worker pool table detection → ruled-border filter → dual-column merge.
Produces ``pages_grouped``, ``page_text``, and ``outline_index`` for ``PreValidationInput``.

Confidence + LLM validation: ``app.services.extraction.pdf.confidence_validation``.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
import pymupdf

from app.services.llm_prompts import CPU_WORKERS, TEXT_MIN_CHARS
from app.services.extraction.pdf.utils.workers import extract_pymupdf_chunk


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ── Stage 1: classify pages ──────────────────────────────────────────────

def classify_pages(pdf_path: Path, min_chars: int = TEXT_MIN_CHARS) -> tuple[List[int], Dict[int, str]]:
    doc = pymupdf.open(pdf_path)
    text_pages: List[int] = []
    page_text: Dict[int, str] = {}
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text")
        if len(text.strip()) >= min_chars:
            text_pages.append(i)
            page_text[i] = text
    doc.close()
    return text_pages, page_text


# ── Stage 2: extract tables ──────────────────────────────────────────────

def chunk_list(lst: List[int], n_chunks: int, seed: int = 0) -> List[List[int]]:
    """Shuffle (deterministically) then split into n_chunks contiguous pieces.

    This PDF's expensive-to-parse pages recur at a near-constant spacing
    (~16 pages apart -- one per state/section, presumably). Plain round-robin
    chunking (lst[i::n]) resonates with any such periodic pattern: on one
    real run, 7 of the 8 slowest pages in the whole document all landed on
    the same worker because their positions in the page list all happened to
    share the same remainder mod 8. Shuffling first breaks any alignment
    between a periodic cost pattern and the chunk boundaries, however many
    workers are used."""
    import random

    n_chunks = max(1, min(n_chunks, len(lst)))
    if not lst:
        return []
    shuffled = lst[:]
    random.Random(seed).shuffle(shuffled)
    size = (len(shuffled) + n_chunks - 1) // n_chunks
    return [shuffled[i:i + size] for i in range(0, len(shuffled), size)]


def extract_all_tables(pdf_path: Path, pages: List[int], n_workers: int = CPU_WORKERS,
                        progress_cb: Optional[Callable[[int, int], None]] = None) -> List[Dict[str, Any]]:
    """Runs extract_pymupdf_chunk over `pages` across a process pool.

    If a worker dies (e.g. OOM-killed), ProcessPoolExecutor marks *every*
    pending/in-flight future as failed, not just the chunk that actually
    crashed -- otherwise-healthy workers' results are lost too. So on a
    BrokenProcessPool we retry just the pages that didn't complete, using
    fewer workers (halving each time) to reduce the memory pressure that
    likely caused the crash, instead of silently returning partial tables."""
    total_pages = len(pages)
    all_tables: List[Dict[str, Any]] = []
    remaining = list(pages)
    workers = max(1, n_workers)
    attempt = 0
    max_attempts = 4

    while remaining and attempt < max_attempts:
        attempt += 1
        chunks = chunk_list(remaining, workers)
        if not chunks:
            break

        pool_broke = False
        with ProcessPoolExecutor(max_workers=len(chunks)) as pool:
            futures = {pool.submit(extract_pymupdf_chunk, str(pdf_path), chunk): chunk for chunk in chunks}
            for future in as_completed(futures):
                chunk = futures[future]
                try:
                    all_tables.extend(future.result())
                    remaining = [p for p in remaining if p not in chunk]
                except BrokenProcessPool as e:
                    pool_broke = True
                    log(f"[extract] process pool crashed on chunk {chunk[0]}-{chunk[-1]} "
                        f"(likely OOM): {e}")
                except Exception as e:
                    log(f"[extract] chunk {chunk[0]}-{chunk[-1]} failed: {e}")
                    remaining = [p for p in remaining if p not in chunk]
                if progress_cb:
                    progress_cb(total_pages - len(remaining), total_pages)

        if not remaining:
            break
        if not pool_broke:
            # Per-chunk failures, not a pool crash -- retrying won't help.
            break
        if workers == 1:
            log(f"[extract] process pool crashed with a single worker; giving up on "
                f"{len(remaining)} remaining page(s)")
            break
        workers = max(1, workers // 2)
        log(f"[extract] retrying {len(remaining)} remaining page(s) with {workers} worker(s)")

    return all_tables


def group_by_page(tables: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    pages: Dict[int, List[Dict[str, Any]]] = {}
    for t in tables:
        pages.setdefault(t["page"], []).append(t)
    return dict(sorted(pages.items()))

def filter_candidate_pages(pages_grouped: Dict[int, List[Dict[str, Any]]]) -> Dict[int, List[Dict[str, Any]]]:
    """Keep pages that have at least one ruled-border hit (lines_strict or lines).

    Drops text-only false positives (prose misread as tables) while retaining
    real grids whose lines are too light/partial for lines_strict alone.
    Also drops chart/figure false positives (wide numeric crumb grids).
    """
    from app.services.extraction.pdf.confidence_validation.table_confidence import (
        looks_like_chart_candidate,
    )

    out: Dict[int, List[Dict[str, Any]]] = {}
    for page_num, candidates in pages_grouped.items():
        kept = [
            c for c in candidates
            if not looks_like_chart_candidate(c.get("df"), bbox=c.get("bbox"))[0]
        ]
        if any(
            str(c.get("method") or "") in ("pymupdf_lines_strict", "pymupdf_lines")
            for c in kept
        ):
            out[page_num] = kept
    return out


_METHOD_RANK = {
    "pymupdf_lines_strict": 0,
    "pymupdf_lines": 1,
    "pymupdf_text": 2,
}


def _bbox_iou(a: Optional[List[float]], b: Optional[List[float]]) -> float:
    """Intersection-over-union for [x0,y0,x1,y1] boxes; 0 if either missing."""
    if not a or not b or len(a) < 4 or len(b) < 4:
        return 0.0
    ax0, ay0, ax1, ay1 = (float(a[0]), float(a[1]), float(a[2]), float(a[3]))
    bx0, by0, bx1, by1 = (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _bbox_overlap_frac(a: Optional[List[float]], b: Optional[List[float]]) -> float:
    """intersection / min(area) — catches a tall text bbox covering a ruled table."""
    if not a or not b or len(a) < 4 or len(b) < 4:
        return 0.0
    ax0, ay0, ax1, ay1 = (float(a[0]), float(a[1]), float(a[2]), float(a[3]))
    bx0, by0, bx1, by1 = (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    denom = min(area_a, area_b)
    return inter / denom if denom > 0 else 0.0


def _bboxes_same_table(a: Optional[List[float]], b: Optional[List[float]]) -> bool:
    return _bbox_iou(a, b) >= 0.55 or _bbox_overlap_frac(a, b) >= 0.65


def _candidate_grid_score(cand: Dict[str, Any]) -> Tuple[int, int, int]:
    """Rank overlapping strategy hits: more columns win, then more cells, then method."""
    df = cand.get("df")
    if df is None or getattr(df, "empty", True):
        return (0, 0, 0)
    n_rows, n_cols = int(df.shape[0]), int(df.shape[1])
    method = str(cand.get("method") or "")
    method_bonus = max(0, 3 - _METHOD_RANK.get(method, 9))
    return (n_cols, n_rows * n_cols, method_bonus)


def _is_substantially_richer(challenger: Dict[str, Any], incumbent: Dict[str, Any]) -> bool:
    """True when challenger is clearly the full table and incumbent a fragment.

    Common failure: lines_strict returns only the stub/label columns while
    lines recovers the full month/measure grid; the stub bbox sits inside the
    full table so naive method-rank dedupe kept the fragment.
    """
    sc = _candidate_grid_score(challenger)
    si = _candidate_grid_score(incumbent)
    if sc[0] >= si[0] + 3 and sc[1] > si[1]:
        return True
    if sc[0] > si[0] and sc[1] >= max(si[1] * 2, si[1] + 20):
        return True
    if sc[0] == si[0] and sc[1] >= si[1] * 2 + 10:
        return True
    return False


def dedupe_candidates_by_bbox(
    candidates: List[Dict[str, Any]],
    *,
    iou_threshold: float = 0.55,
) -> List[Dict[str, Any]]:
    """Collapse strategy duplicates of the same physical table.

    Prefer lines_strict > lines > text when bboxes heavily overlap *and* the
    grids are similarly rich. If a later strategy recovers a substantially
    wider/larger grid whose bbox nests the earlier hit, keep the richer one
    (fragment lines_strict must not eclipse a full lines table). Distinct
    tables on different y-bands stay intact. Drops a spanning pymupdf_text
    blob that covers ruled tables (LLM mix-and-match source).
    """
    if not candidates:
        return []
    ordered = sorted(
        enumerate(candidates),
        key=lambda ic: (
            _METHOD_RANK.get(str(ic[1].get("method") or ""), 9),
            (ic[1].get("bbox") or [0, 0, 0, 0])[1],
            ic[0],
        ),
    )
    kept: List[Dict[str, Any]] = []
    for _, cand in ordered:
        bb = cand.get("bbox")
        method = str(cand.get("method") or "")
        # Text strategy that overlaps already-kept ruled regions = merge artifact
        # unless it is the only hit (handled below via richness).
        if method == "pymupdf_text" and kept:
            ruled_hits = sum(
                1 for prev in kept
                if str(prev.get("method") or "").startswith("pymupdf_lines")
                and _bboxes_same_table(bb, prev.get("bbox"))
            )
            if ruled_hits >= 1:
                continue
        conflicts = [
            i for i, prev in enumerate(kept)
            if _bboxes_same_table(bb, prev.get("bbox"))
        ]
        if not conflicts:
            kept.append(cand)
            continue
        best_i = max(conflicts, key=lambda i: _candidate_grid_score(kept[i]))
        best_prev = kept[best_i]
        if _is_substantially_richer(cand, best_prev):
            for i in sorted(conflicts, reverse=True):
                kept.pop(i)
            kept.append(cand)
        # Else keep the incumbent (already preferred by method order / richness).
    kept.sort(key=lambda c: ((c.get("bbox") or [0, 0, 0, 0])[1], _METHOD_RANK.get(str(c.get("method") or ""), 9)))
    return kept


def _ruled_candidates(candidates: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if not candidates:
        return []
    return [
        c for c in candidates
        if str(c.get("method") or "") in ("pymupdf_lines_strict", "pymupdf_lines")
        and c.get("df") is not None
        and not getattr(c["df"], "empty", True)
    ]


def _distinct_ruled_candidates(candidates: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    return dedupe_candidates_by_bbox(_ruled_candidates(candidates))



def _norm_header_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _candidate_column_meta(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Lightweight column meta for stub-key detection during extract scoring."""
    return [{"name": str(c), "header_path": [str(c)]} for c in df.columns]


def _dataframe_numeric_fill_ratio(df: pd.DataFrame) -> float:
    if df is None or getattr(df, "empty", True):
        return 0.0
    cells = 0
    numeric = 0
    for col in df.columns:
        for v in df[col].tolist():
            cells += 1
            s = str(v).strip() if v is not None else ""
            if not s or s.lower() in {"none", "nan", "null"}:
                continue
            try:
                float(s.replace(",", "").rstrip("%"))
                numeric += 1
            except ValueError:
                pass
    return numeric / cells if cells else 0.0

def _score_candidate_for_table_shape(
    table: Dict[str, Any],
    cand: Dict[str, Any],
) -> float:
    df = cand.get("df")
    if df is None or getattr(df, "empty", True):
        return float("-inf")
    n_cols = len(table.get("columns") or [])
    n_rows = len(table.get("rows") or [])
    n_cand = int(df.shape[1])
    delta = n_cand - n_cols
    # When the LLM dropped leading S.No./Name stubs and starts at Sex, a wider
    # ruled grid is the real table — do not prefer a same-width fragment.
    if delta >= 2 and (
        _llm_starts_at_sex_column(table.get("columns") or [])
        or _llm_missing_identity_stubs(table, cand)
    ):
        score = -abs(delta) * 1.5 + float(delta) * 5.0
    else:
        score = -abs(delta) * 12.0
    score -= abs(int(df.shape[0]) - n_rows) * 0.4
    score += _dataframe_numeric_fill_ratio(df) * 2.0
    if cand.get("method") == "pymupdf_lines_strict":
        score += 0.25
    elif cand.get("method") == "pymupdf_lines":
        score += 0.1
    return score


_STUB_HEADER_RE = re.compile(
    r"(s\.?\s*no\.?|sl\.?\s*no\.?|^sno$|name of|disease|particulars|"
    r"^name$|^cause$|^indicator$|^description$)",
    re.I,
)
_SEX_HEADER_NAME_RE = re.compile(r"^(sex|gender)$", re.I)


def _llm_starts_at_sex_column(columns: List[Dict[str, Any]]) -> bool:
    if not columns:
        return False
    name = str(columns[0].get("name") or "").strip()
    return bool(_SEX_HEADER_NAME_RE.match(name))


def _candidate_leading_stub_keys(cand: Dict[str, Any]) -> List[str]:
    df = cand.get("df")
    if df is None or getattr(df, "empty", True):
        return []
    meta = _candidate_column_meta(df)
    keys: List[str] = []
    for i in range(min(3, int(df.shape[1]))):
        m = meta[i] if i < len(meta) else {}
        leaf = str(m.get("name") or df.columns[i] or "").strip()
        path = m.get("header_path") or []
        blob = " ".join([str(p) for p in (path if isinstance(path, (list, tuple)) else [])] + [leaf])
        if _STUB_HEADER_RE.search(blob) or _STUB_HEADER_RE.search(leaf):
            key = _norm_header_key(leaf)
            if key:
                keys.append(key)
    return keys


def _llm_missing_identity_stubs(
    table: Dict[str, Any],
    cand: Dict[str, Any],
) -> bool:
    """True when the ruled grid has S.No./Name stubs the LLM omitted."""
    df = cand.get("df")
    if df is None or getattr(df, "empty", True):
        return False
    llm_cols = table.get("columns") or []
    n_llm = len(llm_cols)
    n_cand = int(df.shape[1])
    if n_cand < n_llm + 1:
        return False
    llm_keys = {_norm_header_key(c.get("name")) for c in llm_cols if c.get("name")}
    stub_keys = _candidate_leading_stub_keys(cand)
    if stub_keys:
        def _covered(sk: str) -> bool:
            return sk in llm_keys or any(sk in lk or lk in sk for lk in llm_keys if lk)
        missing = [sk for sk in stub_keys if not _covered(sk)]
        if missing:
            return True
    # Heuristic: LLM grid starts at Sex while candidate is wider by ≥2.
    return n_cand >= n_llm + 2 and _llm_starts_at_sex_column(llm_cols)


def _best_matching_ruled_candidate(
    table: Dict[str, Any],
    candidates: Optional[List[Dict[str, Any]]],
    used: Optional[set] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[int]]:
    """Pick unused ruled candidate whose shape best matches this LLM table."""
    if not candidates:
        return None, None
    used = used if used is not None else set()
    best: Optional[Tuple[float, int, Dict[str, Any]]] = None
    for i, c in enumerate(candidates):
        if i in used:
            continue
        if str(c.get("method") or "") not in ("pymupdf_lines_strict", "pymupdf_lines"):
            continue
        score = _score_candidate_for_table_shape(table, c)
        if best is None or score > best[0]:
            best = (score, i, c)
    if best is None:
        return None, None
    return best[2], best[1]


def _pick_dual_column_strict_half(cands: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Choose the ruled half to merge from a side's candidates.

    A page can also contain an unrelated wide lines_strict table whose bbox
    center falls in the left/right half. Prefer 3–5 column stacks with the
    most rows; never take the first lines_strict blindly.
    """
    strict = [
        c
        for c in cands
        if "lines_strict" in str(c.get("method") or "")
        and c.get("df") is not None
        and not getattr(c["df"], "empty", True)
    ]
    scored: List[Tuple[int, Dict[str, Any]]] = []
    for c in strict:
        ncol = int(c["df"].shape[1])
        nrow = int(c["df"].shape[0])
        if 3 <= ncol <= 5 and nrow >= 5:
            scored.append((nrow, c))
    if scored:
        return max(scored, key=lambda item: item[0])[1]
    return None


def resolve_dual_column_pages(
    pdf_path: Path,
    pages_grouped: Dict[int, List[Dict[str, Any]]],
    page_text: Optional[Dict[int, str]] = None,
) -> Dict[int, List[Dict[str, Any]]]:
    """
    Post-extract (no prompt / no change to find_tables strategies): when a page
    is a dual newspaper-style stack (left + right ruled tables with the same
    columns), vertically concatenate right under left into one candidate so
    Preview / LLM see all rows — not only the left half.

    Uses ``dual_column``: partition by bbox when possible; if page text suggests
    a dual-stack layout but only one wide table was found, re-extract with
    mid-page clips for that page only.
    """
    from app.services.extraction.pdf.utils import dual_column as _dual

    page_text = page_text or {}
    resolved: Dict[int, List[Dict[str, Any]]] = {}
    for page_num, candidates in pages_grouped.items():
        halves = _dual.try_dual_column_halves(
            str(pdf_path),
            page_num,
            candidates,
            page_text.get(page_num, ""),
        )
        if not halves:
            resolved[page_num] = candidates
            continue

        left_cands, right_cands = halves
        left_s = _pick_dual_column_strict_half(left_cands)
        right_s = _pick_dual_column_strict_half(right_cands)
        if left_s is None or right_s is None:
            resolved[page_num] = candidates
            continue

        # Recover header-as-first-data-row on each half, then stack right under left.
        left_df = _dual.coerce_dual_stack_half_df(left_s["df"])
        right_df = _dual.coerce_dual_stack_half_df(right_s["df"])
        if left_df is None or right_df is None or left_df.empty or right_df.empty:
            resolved[page_num] = candidates
            continue
        # Mismatched widths / duplicate labels (e.g. a wide scorecard pulled in
        # as one "half") must not reach pd.concat — that raises InvalidIndexError.
        if int(left_df.shape[1]) != int(right_df.shape[1]):
            log(
                f"  page {page_num}: dual-column skip — column count mismatch "
                f"({left_df.shape[1]} vs {right_df.shape[1]})"
            )
            resolved[page_num] = candidates
            continue
        left_df = left_df.reset_index(drop=True).copy()
        right_df = right_df.reset_index(drop=True).copy()
        # Force unique, aligned names so concat never reindexes on dup labels.
        col_names = [str(c) if c is not None else f"Col_{i + 1}" for i, c in enumerate(left_df.columns)]
        seen: Dict[str, int] = {}
        unique_names: List[str] = []
        for name in col_names:
            n = seen.get(name, 0)
            unique_names.append(name if n == 0 else f"{name}_{n + 1}")
            seen[name] = n + 1
        left_df.columns = unique_names
        right_df.columns = unique_names
        merged_df = pd.concat([left_df, right_df], ignore_index=True)
        n_left, n_right = int(left_df.shape[0]), int(right_df.shape[0])
        log(
            f"  page {page_num}: dual-column merge — "
            f"{n_left} left + {n_right} right → {int(merged_df.shape[0])} rows"
        )
        resolved[page_num] = [
            {
                "page": page_num,
                "method": "pymupdf_lines_strict",
                "df": merged_df,
                "bbox": None,
                "dual_column_merged": True,
                "dual_column_halves": {"left_rows": n_left, "right_rows": n_right},
            }
        ]
    return resolved


def run_pdf_extraction(
    pdf_path: Path,
    on_progress: Optional[Callable[[str, int, str], None]] = None,
) -> Tuple[Dict[int, List[Dict[str, Any]]], Dict[int, str], Dict[int, List[str]]]:
    """PyMuPDF extraction only: page scan → table candidates (no confidence / LLM)."""

    def progress(stage: str, percent: int, message: str) -> None:
        log(message)
        if on_progress:
            on_progress(stage, percent, message)

    progress("classify", 2, f"Scanning {pdf_path.name} for text-bearing pages")
    text_pages, page_text = classify_pages(pdf_path)
    progress("classify", 10, f"{len(text_pages)} text-bearing page(s) found")

    progress("extract", 10, f"Extracting tables from {len(text_pages)} page(s)")
    all_tables = extract_all_tables(
        pdf_path,
        text_pages,
        progress_cb=lambda done, total: progress(
            "extract", 10 + int(35 * done / total), f"Extracted {done}/{total} page(s)"
        ),
    )
    progress("extract", 45, f"{len(all_tables)} table candidate(s) found")

    pages_grouped = filter_candidate_pages(group_by_page(all_tables))
    pages_grouped = resolve_dual_column_pages(pdf_path, pages_grouped, page_text)
    from app.services.extraction.pdf.confidence_validation.table_confidence import (
        build_pdf_outline_index,
    )
    outline_index = build_pdf_outline_index(pdf_path)
    return pages_grouped, page_text, outline_index
