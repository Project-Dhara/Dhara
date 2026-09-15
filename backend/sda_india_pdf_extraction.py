"""
Run: python sda_india_pdf_extraction.py [--pages N] [--limit N]
"""

import argparse
import json
import os
import re
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import openai
import pandas as pd
import pymupdf
from dotenv import load_dotenv

from pdf_extraction_workers import extract_pymupdf_chunk
from pdf_table_confidence import (
    build_pdf_outline_index,
    classify_page,
    dedupe_column_names,
    extract_page_text_blocks,
    table_dict_from_df,
)

load_dotenv(Path(__file__).parent / ".env")

PDF_PATH = Path(__file__).parent.parent / "SDA_INDIA_0.pdf"
OUTPUT_DIR = Path(__file__).parent / "data" / "sda_india_extraction"

TEXT_MIN_CHARS = 20
CPU_WORKERS = 3 #Changed from min(os.cpu_count() or 4, 8), since pc has only 8gb RAM.
OPENAI_MODEL = "gpt-4o-mini"
OPENAI_WORKERS = 6
BATCH_SIZE = 5 
# Bumped from 2500/4000 -> each table's response now also carries a
# "classification" block and per-column role/concept/description/data_type/
# unit/category, not just title+columns+rows -- same single call per
# page/batch, just a fatter response payload.
MAX_TOKENS_PER_PAGE = 5000
SINGLE_PAGE_MAX_TOKENS = 7000
RAW_TEXT_CHARS_PER_PAGE_BATCHED = 1500


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
    """
    return {
        page_num: candidates
        for page_num, candidates in pages_grouped.items()
        if any(
            str(c.get("method") or "") in ("pymupdf_lines_strict", "pymupdf_lines")
            for c in candidates
        )
    }


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


def _score_candidate_for_table_shape(
    table: Dict[str, Any],
    cand: Dict[str, Any],
) -> float:
    df = cand.get("df")
    if df is None or getattr(df, "empty", True):
        return float("-inf")
    n_cols = len(table.get("columns") or [])
    n_rows = len(table.get("rows") or [])
    score = -abs(int(df.shape[1]) - n_cols) * 12.0
    score -= abs(int(df.shape[0]) - n_rows) * 0.4
    score += _dataframe_numeric_fill_ratio(df) * 2.0
    if cand.get("method") == "pymupdf_lines_strict":
        score += 0.25
    elif cand.get("method") == "pymupdf_lines":
        score += 0.1
    return score


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
    center falls in the left/right half. Prefer 3–5 column stacks (indicator
    layout) with the most rows; never take the first lines_strict blindly.
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

    Uses pdf_dual_column: prefer partitioning existing bbox candidates; if the
    page title says "Performance by Indicators" but only one wide table was
    found, fall back to mid-page clip re-detect for that page only.
    """
    import pdf_dual_column as _dual

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
        left_df = _dual.coerce_indicator_half_df(left_s["df"])
        right_df = _dual.coerce_indicator_half_df(right_s["df"])
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


def split_by_confidence(
    pages_grouped: Dict[int, List[Dict[str, Any]]],
    page_text: Optional[Dict[int, str]] = None,
    *,
    pdf_path: Optional[Path] = None,
    outline_index: Optional[Dict[int, List[str]]] = None,
):
    """Runs the deterministic (no-LLM) classifier per page. Returns:
      high_results   -- {page_num: {"tables": [...]}} accepted directly, no LLM
      llm_pages      -- {page_num: candidates} still needing the OpenAI step
      reason_counts  -- {reason: count} for the "llm" bucket, for visibility into why

    For high-confidence pages, titles are inferred from page_text, positioned
    text above the table bbox, extended caption patterns, and PDF outline —
    see pdf_table_confidence.infer_title_from_page_text.
    """
    page_text = page_text or {}
    outline_index = outline_index or {}
    high_results: Dict[int, Dict[str, Any]] = {}
    llm_pages: Dict[int, List[Dict[str, Any]]] = {}
    reason_counts: Dict[str, int] = {}

    doc = None
    if pdf_path and Path(pdf_path).is_file():
        doc = pymupdf.open(pdf_path)
    page_blocks_cache: Dict[int, List[Dict[str, float]]] = {}

    try:
        for page_num, candidates in pages_grouped.items():
            # Collapse lines_strict/lines/text clones of the same bbox before
            # classifying or sending to the LLM (avoids mix-and-match).
            candidates = dedupe_candidates_by_bbox(candidates)
            bucket, reason, _info = classify_page(candidates)
            if bucket == "high":
                if doc is not None and page_num not in page_blocks_cache:
                    page_blocks_cache[page_num] = extract_page_text_blocks(doc, page_num)
                page_blocks = page_blocks_cache.get(page_num)
                outline_sections = outline_index.get(page_num, [])

                # Keep every distinct ruled table on the page.
                has_strict = any(c.get("method") == "pymupdf_lines_strict" for c in candidates)
                ruled_methods = {"pymupdf_lines_strict"} if has_strict else {"pymupdf_lines"}
                # If strict missed a second physical table that only `lines` saw,
                # still include non-overlapping lines tables.
                tables = []
                taken_bboxes: List[List[float]] = []
                ordered = [
                    c for c in candidates
                    if c.get("method") in ruled_methods
                ] + (
                    [c for c in candidates if c.get("method") == "pymupdf_lines"]
                    if has_strict else []
                )
                seen = set()
                for c in ordered:
                    cid = id(c)
                    if cid in seen:
                        continue
                    seen.add(cid)
                    df = c.get("df")
                    if df is None or getattr(df, "empty", True):
                        continue
                    bb = c.get("bbox")
                    if bb and any(_bboxes_same_table(bb, prev) for prev in taken_bboxes):
                        continue
                    bbox_f = None
                    if bb and len(bb) >= 4:
                        bbox_f = [float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])]
                    table = table_dict_from_df(
                        df,
                        page_text=page_text.get(page_num, ""),
                        page_num=page_num,
                        method=str(c.get("method") or "pymupdf_lines_strict"),
                        bbox=bbox_f,
                        page_blocks=page_blocks,
                        outline_sections=outline_sections,
                    )
                    table["page"] = page_num
                    if bbox_f:
                        table["bbox"] = bbox_f
                    tables.append(table)
                    if bb:
                        taken_bboxes.append(bb)
                high_results[page_num] = {"tables": tables}
            else:
                llm_pages[page_num] = candidates
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
    finally:
        if doc is not None:
            doc.close()

    return high_results, llm_pages, reason_counts


# ── Stage 3: OpenAI validation / restructuring ───────────────────────────

def df_to_text(df: pd.DataFrame, max_rows: int = 40) -> str:
    return df.head(max_rows).to_csv(index=False, header=False)


# Shared across the single-page and batched prompts (build_validation_prompt /
# build_batch_validation_prompt) so the two jobs -- reconstruct, then classify
# -- are worded identically everywhere they're asked for, in one LLM call.
TASK_A_RECONSTRUCTION_RULES = """TASK A -- RECONSTRUCT THE TABLE:
- Reconcile the candidate extractions into ONE clean, correct table per distinct table on the page.
- Count the DISTINCT physical tables from ruled-border candidates (pymupdf_lines_strict /
  pymupdf_lines) that have different vertical positions / captions. You MUST emit that many
  separate tables in "tables" (one object each). Do NOT merge two ruled candidates — or their
  rows — into a single output table unless the raw text makes clear they are literally one table
  split by a page/column break (same header, no new caption in between). When in doubt, keep
  them as separate tables; a pymupdf_text candidate that spans multiple captions is a
  whitespace-alignment artifact, not evidence that the underlying tables should be combined.
- NEVER invent a value that isn't present in at least one candidate or the raw text.
- Prefer whichever candidate got a given row/column right; you may combine cells from different
  candidates that describe the SAME physical table (same bbox / same caption), not across tables.
- If candidates disagree on a cell and you can't tell which is right from the raw text, keep the
  pymupdf_lines_strict (or pymupdf_lines) value and add a note in "uncertain_cells".
- Flatten multi-row / merged headers into ONE name per physical data column. Do NOT promote a
  spanning group label into its own extra column.
  Example — source header grid:
      Year | In Lakhs (spans 2 cols) | *Birth Rate
           | Mid Year Population | No. of Births |
    Correct columns (4): ["Year", "Mid Year Population as on 1st July (In Lakhs)",
    "No. of Births (In Lakhs)", "*Birth Rate"]
    WRONG (5 phantom columns): ["Year", "In Lakhs", "Birth Rate", "Mid Year Population", "No. of Births"]
  Every data row length MUST equal len(columns); values stay under their leaf headers.
- Column names in the output MUST be unique. If the same leaf header (e.g. a year, "Male"/"Female",
  or a repeated sub-metric) appears under two different parent groups, you MUST fold the parent group
  into the name so the two columns read differently (e.g. "2023-24 (Sanctioned)" and
  "2023-24 (Released)", or "Male (Institutional Births)" and "Male (Non-Institutional Births)").
  Never emit two columns with the identical name.
- SECTION / CATEGORY HEADER ROWS: a row that only has a value in the first 1-2 columns (e.g. a letter
  or index like "A"/"B" plus a group label like "Vital Rates (per 1000)") and is blank in every measure
  column is a section heading for the rows below it, not a data point to discard. Keep it as its own
  row with the group label in place and null in the other columns -- do NOT silently drop it (that loses
  the grouping context for every row underneath) and do NOT invent values to fill it in.
- Preserve a title/description if one is visible in the raw text.
- SYMBOLIC / ICON CELLS (especially Direction / Trend / Change columns):
  PDF extractors often emit private-use or icon-font glyphs for green/red trend arrows instead of real text.
  ONLY when a Direction / Trend / Change column is already present in the candidates or clearly visible
  as a table header in the raw text:
    * Interpret upward / green / "increase" arrows as the cell value "up"
    * Interpret downward / red / "decrease" arrows as the cell value "down"
    * Write "up" or "down" in the reconstructed "rows" (never leave the raw arrow glyph / tofu / �).
    * Every row MUST include that Direction/Trend cell — the rows array length must equal the columns
      array length. Do not declare a Direction column and then omit that cell from the row.
    * If you cannot tell whether an arrow is up or down, still put your best guess ("up" or "down") in the
      cell, add a note in "uncertain_cells", and flag the column for human review (see Task B input_type).
  Do NOT invent, append, or fill a Direction / Trend / Change column when none exists in the source
  table. If the table has no such column, omit it entirely (do not invent up/down values)."""

TASK_B_CLASSIFICATION_RULES = """TASK B -- UNDERSTAND THE TABLE (initial semantic classification only):
After reconstructing a table, determine what it appears to mean, using the page text, table title, headers,
extracted values, and any notes/footnotes as context.

At table level, identify where possible: domain, subject, entity, table_type, geography, time_period,
frequency, unit. Each of these is an object:
  {"value": ..., "human_review_needed": true|false, "input_type": "dropdown"|"inputbox"|null,
   "input_options": [...]|null, "human_review_reason": "..."|null}
-- see the human_review_needed / input_type rules below.

At column level, for each column identify:
- "role": one of "identifier", "dimension", "measure", "attribute", "unknown"
- "concept": the semantic concept the column represents (e.g. "State", "Population", "Primary Health Centre")
- "description": a short description of the column
- "data_type": one of "string", "integer", "decimal", "date", "boolean", "categorical", "unknown"
- "unit": the unit of measurement if applicable, else null
- "category": a sub-category/grouping value if applicable (e.g. a "Male" column's category is "Male"), else null
- "human_review_needed": true|false
- "input_type": "dropdown" | "inputbox" | null  -- UI hint for how a human should correct this field/column
- "input_options": array of allowed strings when input_type is "dropdown", else null
- "human_review_reason": "..."|null -- see the rules below

Examples:
- "State" -> role: dimension, concept: State, data_type: categorical,
  human_review_needed: false, input_type: null, input_options: null, human_review_reason: null
- "PHC ID" -> role: identifier, concept: Primary Health Centre, data_type: string,
  human_review_needed: false, input_type: null, input_options: null, human_review_reason: null
- "Male" -> role: measure, concept: Population, category: Male, data_type: integer,
  human_review_needed: false, input_type: null, input_options: null, human_review_reason: null
- "Total" -> role: measure, concept: Population, data_type: integer,
  human_review_needed: false, input_type: null, input_options: null, human_review_reason: null
- "PHC" (ambiguous abbreviation, could mean several things) -> concept: Primary Health Centre (best guess),
  human_review_needed: true, input_type: "inputbox", input_options: null,
  human_review_reason: "uncertain_concept"
- "Direction" / "Trend" (ONLY if that column is already in the source table; values shown as up/down
  arrows in the PDF) -> role: attribute, concept: Direction,
  data_type: categorical, rows use "up"|"down",
  human_review_needed: true, input_type: "dropdown", input_options: ["up", "down"],
  human_review_reason: "garbled_extracted_value"
  (or "uncertain_extraction" if the arrow was ambiguous). Even when every arrow was confidently mapped,
  still set human_review_needed: true and input_type: "dropdown" for Direction-like columns so a human
  can confirm via dropdown rather than free-text. Never add this column when it is absent from the table.

human_review_needed / input_type / human_review_reason rules (both for each classification field above, and for each column):
- Give your best semantic interpretation always -- never leave a field empty just because you're unsure;
  put your best guess in "value"/the column fields, and use human_review_needed to flag the uncertainty
  instead of refusing to answer.
- Set human_review_needed=true ONLY when there is MEANINGFUL uncertainty or ambiguity a human should
  resolve -- e.g. a column name/abbreviation that could plausibly mean more than one thing, a table title
  that doesn't clearly indicate its subject, a role you genuinely can't determine (role: "unknown"), OR a
  Direction/Trend-like column whose values came from icon/arrow glyphs (always reviewable via dropdown).
- When human_review_needed=true you MUST also set input_type:
    * "dropdown" -- the correct value is one of a small fixed set (Direction/Trend -> ["up","down"];
      yes/no; similar binary/ternary categorical choices). Always include "input_options" as that list.
    * "inputbox" -- the human should type free text (ambiguous labels, garbled names, open concepts).
      Set "input_options" to null.
- When human_review_needed=false, set input_type: null and input_options: null.
- Do NOT set human_review_needed=true just because an OPTIONAL field is simply not present in the source
  (e.g. frequency or unit legitimately don't apply to this table) -- in that case use value: null,
  human_review_needed: false, input_type: null, input_options: null, human_review_reason: null.
  Missing-and-not-applicable is not the same as uncertain-and-ambiguous.
- When human_review_needed=true, human_review_reason MUST be exactly one of these standardized values
  (do not invent your own wording):
    "uncertain_extraction"    -- the extracted value itself may be wrong, incomplete, or hard to read
    "conflicting_extraction"  -- two extraction candidates disagree and you had to pick one
    "garbled_extracted_value" -- the extracted text contains corrupted/mojibake/encoding-broken characters
                                  OR icon-font arrow glyphs that were interpreted as up/down
    "uncertain_semantic_role" -- you cannot confidently tell what role this column/field plays
    "uncertain_concept"       -- the name/abbreviation could plausibly mean more than one real-world concept
    "ambiguous_column"        -- some other column-level ambiguity not covered by the above
- When human_review_needed=false, human_review_reason MUST be null.
- Also add a brief note in "notes" explaining the uncertainty (e.g. "column 'PHC' -- could be Primary Health
  Centre or another facility type, please confirm"; or "Direction column used arrow icons; mapped to up/down").
- Do NOT hallucinate standards, codes, entities, units, or dates that aren't supported by the page.
- Do NOT attempt harmonization, do NOT map to any external standard/code list (e.g. NMDS/LGD/NCO), and do NOT
  group this table with any other table. That happens in a later stage, not here."""

TABLE_SCHEMA_EXAMPLE = """{
  "tables": [
    {
      "title": "...",
      "description": "...",
      "classification": {
        "domain": {"value": "...", "human_review_needed": false, "input_type": null, "input_options": null, "human_review_reason": null},
        "subject": {"value": "...", "human_review_needed": false, "input_type": null, "input_options": null, "human_review_reason": null},
        "entity": {"value": "...", "human_review_needed": false, "input_type": null, "input_options": null, "human_review_reason": null},
        "table_type": {"value": "...", "human_review_needed": false, "input_type": null, "input_options": null, "human_review_reason": null},
        "geography": {"value": "...", "human_review_needed": false, "input_type": null, "input_options": null, "human_review_reason": null},
        "time_period": {"value": "...", "human_review_needed": false, "input_type": null, "input_options": null, "human_review_reason": null},
        "frequency": {"value": null, "human_review_needed": false, "input_type": null, "input_options": null, "human_review_reason": null},
        "unit": {"value": "...", "human_review_needed": false, "input_type": null, "input_options": null, "human_review_reason": null}
      },
      "columns": [
        {
          "name": "...", "role": "identifier | dimension | measure | attribute | unknown",
          "concept": "...", "description": "...",
          "data_type": "string | integer | decimal | date | boolean | categorical | unknown",
          "unit": "...", "category": "...",
          "human_review_needed": false, "input_type": null, "input_options": null, "human_review_reason": null
        }
      ],
      "rows": [["...", "..."], ["...", "..."]],
      "notes": [],
      "uncertain_cells": ["row 3, col 'Total': pymupdf_lines_strict=120 vs pymupdf_text=170, kept lines_strict"]
    }
  ]
}
Do not include a top-level "human_review_needed" on the table object -- that final flag is computed
deterministically from the field/column flags and uncertain_cells afterward, not by you.
When human_review_needed is true, always pair it with input_type ("dropdown" or "inputbox") as shown above.
Do not include a Direction/Trend column in columns/rows unless it is present in the source table."""


CLASSIFICATION_FIELDS = ("domain", "subject", "entity", "table_type", "geography", "time_period", "frequency", "unit")

# Standardized human_review_reason values, in table-level tie-break priority
# order (most specific/actionable first). Field- and column-level reasons are
# never coerced to this priority -- each keeps its own reason; this ordering
# is only used to pick ONE reason for the table-level rollup when several
# different reasons are present underneath it.
#
# ADDED: "column_alignment_mismatch" -- deterministic post-LLM check when
# reconstructed cells clearly don't match their column (e.g. up/down under
# States/UTs, S.No. glued to a name, measure columns mostly empty). Higher
# priority than generic uncertain_extraction so the UI surfaces it first.
REVIEW_REASONS = (
    "garbled_extracted_value",
    "column_alignment_mismatch",
    "conflicting_extraction",
    "uncertain_extraction",
    "uncertain_semantic_role",
    "uncertain_concept",
    "ambiguous_column",
)
_REASON_PRIORITY = {reason: i for i, reason in enumerate(REVIEW_REASONS)}

# Private-use-area glyphs (icon fonts with no real Unicode mapping -- e.g. the
# trend-arrow symbols seen in this PDF's SDG tables) and common mojibake
# sequences from a text/encoding mismatch. Matches the kind of corruption
# described in the "garbled_extracted_value" case, not just any odd character.
_GARBLED_RE = re.compile("[\ue000-\uf8ff\ufffd]|[\u00c0-\u00ff][\u0080-\u00bf]")

# ADDED: tokens that belong in Direction/Trend columns, used to detect when
# those values landed in the wrong column after LLM reconstruction.
_DIRECTION_TOKENS = frozenset({"up", "down", "↑", "↓"})
_NUMERIC_DATA_TYPES = frozenset({
    "integer", "int", "decimal", "float", "double", "number", "numeric",
    "percentage", "percent", "pct",
})
_EMPTY_TOKENS = frozenset({"", "null", "none", "na", "n/a", "-", "–", "—", "."})


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


def _cell_is_numeric(value: Any) -> Optional[bool]:
    """True/False for clearly numeric vs non-numeric; None if empty/placeholder."""
    if _cell_is_empty(value):
        return None
    s = str(value).strip().replace(",", "").replace("%", "").strip()
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
    if (
        role == "measure"
        or dt in _NUMERIC_DATA_TYPES
        or any(k in name for k in ("percent", "percentage", "index score", "score", "kg/", "gva", "rate"))
    ):
        return "measure"
    return "other"


def _detect_column_alignment_issues(
    columns: List[Dict[str, Any]], rows: List[List[Any]]
) -> List[Dict[str, Any]]:
    """ADDED: Deterministic structural check after LLM reconstruction.

    Catches shifted grids like SDG state tables where Direction up/down lands
    under States/UTs, S.No. is glued to the state name, and measure columns
    are left empty. Returns a list of {col_index, name, detail} issues.
    """
    issues: List[Dict[str, Any]] = []
    if not columns or not rows:
        return issues

    nrows = len(rows)
    for idx, col in enumerate(columns):
        kind = _column_structural_kind(col)
        vals = [row[idx] if idx < len(row) else None for row in rows]
        non_empty = [v for v in vals if not _cell_is_empty(v)]
        name = col.get("name") or f"col_{idx}"
        empty_rate = 1.0 - (len(non_empty) / nrows) if nrows else 0.0

        if kind == "measure" and nrows >= 5:
            if empty_rate >= 0.7:
                issues.append({
                    "col_index": idx, "name": name, "kind": kind,
                    "detail": f"measure column mostly empty ({empty_rate:.0%} blank)",
                })
                continue
            numeric_flags = [_cell_is_numeric(v) for v in non_empty]
            judged = [f for f in numeric_flags if f is not None]
            if judged and (sum(1 for f in judged if f) / len(judged)) < 0.5:
                issues.append({
                    "col_index": idx, "name": name, "kind": kind,
                    "detail": "measure column values are mostly non-numeric",
                })
            direction_hits = sum(
                1 for v in non_empty if str(v).strip().lower() in _DIRECTION_TOKENS
            )
            if non_empty and direction_hits / len(non_empty) >= 0.4:
                issues.append({
                    "col_index": idx, "name": name, "kind": kind,
                    "detail": "measure column contains Direction up/down tokens",
                })

        elif kind == "geo" and non_empty:
            direction_hits = sum(
                1 for v in non_empty if str(v).strip().lower() in _DIRECTION_TOKENS
            )
            if direction_hits / len(non_empty) >= 0.4:
                issues.append({
                    "col_index": idx, "name": name, "kind": kind,
                    "detail": "States/geo column filled with Direction up/down values",
                })

        elif kind == "serial" and non_empty:
            # e.g. "1, Andhra Pradesh" -- serial number glued to the next field
            glued = sum(
                1 for v in non_empty
                if isinstance(v, str) and re.match(r"^\d+\s*,\s*\S", v.strip())
            )
            if glued / len(non_empty) >= 0.3:
                issues.append({
                    "col_index": idx, "name": name, "kind": kind,
                    "detail": "S.No./serial values look glued to the next column",
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


def _best_lines_strict_candidate(candidates: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """Prefer lines_strict; fall back to looser lines (not text) when strict missed."""
    if not candidates:
        return None
    strict = [c for c in candidates if c.get("method") == "pymupdf_lines_strict" and c.get("df") is not None]
    lines = [c for c in candidates if c.get("method") == "pymupdf_lines" and c.get("df") is not None]
    pool = strict or lines
    if not pool:
        return None
    return max(pool, key=lambda c: _dataframe_numeric_fill_ratio(c["df"]))


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
    best_cand = matched_cand or (
        _best_lines_strict_candidate(candidates) if candidates else None
    )
    if best_cand is not None:
        cand_ncols = int(best_cand["df"].shape[1])
        if cand_ncols >= 2 and len(columns) >= max(6, cand_ncols * 2):
            issues.append({
                "col_index": -1, "name": "(table structure)", "kind": "structure",
                "detail": f"reconstructed {len(columns)} columns vs {cand_ncols} in the "
                          "ruled-border candidate -- likely a title/caption line misread as headers",
            })
        elif cand_ncols >= 4 and len(columns) <= max(2, cand_ncols // 2):
            issues.append({
                "col_index": -1, "name": "(table structure)", "kind": "structure",
                "detail": f"reconstructed only {len(columns)} columns vs {cand_ncols} in the "
                          "ruled-border candidate -- likely a multi-level header collapsed too far, "
                          "losing a real column split (e.g. per-year values)",
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
    for issue in issues:
        note = (
            f"column_alignment_mismatch: col {issue['col_index']} "
            f"{issue['name']!r} -- {issue['detail']}"
        )
        if note not in uncertain:
            uncertain.append(note)
    summary = (
        "ADDED guard: reconstructed table failed column-alignment checks "
        f"({len(issues)} column(s)); values may be shifted across headers."
    )
    if summary not in notes:
        notes.append(summary)

    severe = any(i["kind"] in ("geo", "serial", "structure") for i in issues) or sum(
        1 for i in issues if i["kind"] == "measure"
    ) >= 2

    has_structure_issue = any(i["kind"] == "structure" for i in issues)

    fallback_used = False
    if severe and candidates:
        cand, cand_idx = matched_cand, matched_idx
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
            if has_structure_issue or (cand_fill >= 0.5 and cand_fill > llm_fill + 0.25):
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
                    "ADDED guard: replaced LLM rows/columns with "
                    f"{cand.get('method')} candidate after alignment mismatch "
                    f"(candidate numeric fill {cand_fill:.0%} vs LLM {llm_fill:.0%})."
                )
                notes.append(fallback_note)
                uncertain.append(fallback_note)
                fallback_used = True
                table["_skip_structure_attach"] = True
                if used_candidates is not None and cand_idx is not None:
                    used_candidates.add(cand_idx)
                # Re-detect on fallback grid (usually clean); keep prior notes.
                issues = _detect_column_alignment_issues(table["columns"], table["rows"])
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


def _coerce_reason(raw: Any) -> Optional[str]:
    """Validates a human_review_reason against REVIEW_REASONS. If the model
    returned something close but non-standard, infer the nearest standard
    reason by keyword; if nothing matches, return None so the caller can
    degrade that flag to "no review needed" rather than surface an
    unexplained, unactionable flag."""
    if raw in REVIEW_REASONS:
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.lower()
    if "garbl" in s or "corrupt" in s or "encoding" in s or "mojibake" in s:
        return "garbled_extracted_value"
    # ADDED: map free-text alignment wording to the new standard reason.
    if "align" in s or "mismatch" in s or "shifted" in s or "wrong column" in s:
        return "column_alignment_mismatch"
    if "conflict" in s or "disagree" in s:
        return "conflicting_extraction"
    if "role" in s:
        return "uncertain_semantic_role"
    if "concept" in s or "meaning" in s:
        return "uncertain_concept"
    if "extraction" in s or "extract" in s:
        return "uncertain_extraction"
    if "ambig" in s:
        return "ambiguous_column"
    return None


def _normalize_review_flag(human_review_needed: Any, human_review_reason: Any) -> tuple[bool, Optional[str]]:
    """Normalizes one (human_review_needed, human_review_reason) pair.
    human_review_needed=false always forces reason to null. A true flag
    without a reason we can validate/infer is NOT trusted as-is -- an
    unexplained review flag isn't actionable for the frontend, so it's
    downgraded to (false, null) rather than passed through."""
    if not human_review_needed:
        return False, None
    reason = _coerce_reason(human_review_reason)
    if reason is None:
        return False, None
    return True, reason


def _normalize_input_ui(needed: bool, input_type: Any, input_options: Any) -> tuple[Optional[str], Optional[List[str]]]:
    """Keeps LLM input_type / input_options only when review is needed."""
    if not needed:
        return None, None
    kind = str(input_type or "").strip().lower()
    if kind in ("dropdown", "select"):
        opts = input_options if isinstance(input_options, list) else None
        cleaned = [str(o) for o in (opts or []) if o is not None and str(o).strip()]
        return "dropdown", cleaned or None
    if kind in ("inputbox", "input", "text", "textbox"):
        return "inputbox", None
    return "inputbox", None


def _normalize_field(field: Any) -> Dict[str, Any]:
    """Normalizes one classification field to {"value", "human_review_needed",
    "input_type", "input_options", "human_review_reason"}. Tolerates the model
    returning a bare scalar instead of the object shape (treated as the value,
    no review flag) or omitting the field entirely (defaults null/false/null)."""
    if isinstance(field, dict):
        needed, reason = _normalize_review_flag(field.get("human_review_needed", False), field.get("human_review_reason"))
        input_type, input_options = _normalize_input_ui(needed, field.get("input_type"), field.get("input_options"))
        return {
            "value": field.get("value"),
            "human_review_needed": needed,
            "input_type": input_type,
            "input_options": input_options,
            "human_review_reason": reason,
        }
    # Bare scalar (string/null) instead of the object shape -- keep the value.
    return {
        "value": field,
        "human_review_needed": False,
        "input_type": None,
        "input_options": None,
        "human_review_reason": None,
    }


def _normalize_table(table: Dict[str, Any]) -> Dict[str, Any]:
    """Fills in defaults for any optional field the LLM omitted or returned
    in an unexpected shape, so a malformed/partial response degrades
    gracefully (null/"unknown"/false) instead of crashing the batch or
    leaving downstream consumers to KeyError on a missing field."""
    cls = table.get("classification")
    cls = cls if isinstance(cls, dict) else {}

    columns = []
    for c in table.get("columns") or []:
        if isinstance(c, str):
            # Model ignored the object schema and returned a bare name -- keep
            # the name, mark everything else unknown rather than dropping it.
            columns.append({
                "name": c, "role": "unknown", "concept": None, "description": None,
                "data_type": "unknown", "unit": None, "category": None,
                "human_review_needed": False, "input_type": None, "input_options": None,
                "human_review_reason": None,
            })
        elif isinstance(c, dict):
            needed, reason = _normalize_review_flag(c.get("human_review_needed", False), c.get("human_review_reason"))
            input_type, input_options = _normalize_input_ui(needed, c.get("input_type"), c.get("input_options"))
            # Direction-like columns: default to up/down dropdown when the model
            # flagged review but omitted input_type / options.
            name_l = str(c.get("name") or "").lower()
            concept_l = str(c.get("concept") or "").lower()
            if needed and input_type is None and any(
                k in name_l or k in concept_l for k in ("direction", "trend", "change")
            ):
                input_type, input_options = "dropdown", ["up", "down"]
            # Preserve multi-level header meta when present (alignment-guard
            # fallback / post-stamp attach). Do not invent it here.
            header_group = c.get("header_group")
            if header_group is not None:
                header_group = str(header_group).strip() or None
            raw_path = c.get("header_path")
            header_path = None
            if isinstance(raw_path, (list, tuple)):
                header_path = [str(p).strip() for p in raw_path if str(p).strip()]
            col_out = {
                "name": c.get("name", ""),
                "role": c.get("role") or "unknown",
                "concept": c.get("concept"),
                "description": c.get("description"),
                "data_type": c.get("data_type") or "unknown",
                "unit": c.get("unit"),
                "category": c.get("category"),
                "human_review_needed": needed,
                "input_type": input_type,
                "input_options": input_options,
                "human_review_reason": reason,
            }
            if header_path:
                col_out["header_path"] = header_path
                col_out["header_group"] = header_group or (
                    header_path[-2] if len(header_path) >= 2 else None
                )
            elif header_group:
                col_out["header_group"] = header_group
            columns.append(col_out)

    # Pad / trim every row to match column count. The model often declares a
    # Direction/Trend column but omits that cell from each row array, which
    # leaves the UI with a header and no bordered cells underneath.
    ncols = len(columns)
    rows: List[List[Any]] = []
    for raw in table.get("rows") or []:
        if not isinstance(raw, list):
            rows.append([None] * ncols)
            continue
        row = list(raw[:ncols])
        while len(row) < ncols:
            row.append(None)
        rows.append(row)

    columns = dedupe_column_names(columns)

    return {
        "title": table.get("title"),
        "description": table.get("description"),
        "classification": {field: _normalize_field(cls.get(field)) for field in CLASSIFICATION_FIELDS},
        "columns": columns,
        "rows": rows,
        "notes": table.get("notes") or [],
        "uncertain_cells": table.get("uncertain_cells") or [],
    }


def derive_human_review_needed(table: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """Computes the FINAL table-level (human_review_needed, human_review_reason)
    deterministically from explicit signals -- never trusts an LLM-provided
    table-level flag directly (the prompt is told not to emit one at all).

    Two different kinds of uncertainty feed into this, kept conceptually
    separate but both able to trigger the table-level flag:
      - data reconstruction uncertainty -> uncertain_cells non-empty, or a
        row value that looks corrupted/mojibake (garbled_extracted_value),
        or ADDED column_alignment_mismatch from the post-LLM grid guard
      - semantic classification uncertainty -> a classification field or
        column marked human_review_needed=true (each keeping its own
        reason), or a column whose role genuinely couldn't be determined
        (role == "unknown" -> uncertain_semantic_role, material to
        understanding the table regardless of whether the model itself
        flagged it)

    When multiple reasons are present, REVIEW_REASONS' order picks ONE for
    the table-level rollup -- the underlying field/column reasons are left
    untouched, so the frontend can still show exactly which field or column
    needs attention and why.

    Tables that simply haven't been semantically classified yet (the
    deterministic high-confidence/no-LLM path) are NOT "needing review" --
    that status is tracked separately via semantic_status. Absence of
    optional metadata (frequency/unit/description unknown) does not, by
    itself, trigger review either -- see the prompt's human_review_needed
    rules for why the model is told not to flag those."""
    if table.get("semantic_status") != "classified":
        return False, None

    reasons_present: set = set()

    uncertain_cells = table.get("uncertain_cells") or []
    rows = table.get("rows") or []
    if uncertain_cells:
        if any("column_alignment_mismatch" in str(note) for note in uncertain_cells):
            # ADDED: notes written by _apply_column_alignment_guard.
            reasons_present.add("column_alignment_mismatch")
        if any(_looks_garbled(note) for note in uncertain_cells) or _rows_look_garbled(rows):
            reasons_present.add("garbled_extracted_value")
        elif any(" vs " in str(note) for note in uncertain_cells):
            # Matches this pipeline's own uncertain_cells note format (see
            # TASK_A_RECONSTRUCTION_RULES / uncertain_cells example) --
            # "row X, col Y: candidateA=... vs candidateB=...".
            reasons_present.add("conflicting_extraction")
        elif "column_alignment_mismatch" not in reasons_present:
            reasons_present.add("uncertain_extraction")
    elif _rows_look_garbled(rows):
        # Garbled values can show up even without an explicit uncertain_cells
        # note, e.g. a private-use-area glyph both candidates agreed on.
        reasons_present.add("garbled_extracted_value")

    classification = table.get("classification") or {}
    for f in classification.values():
        if isinstance(f, dict) and f.get("human_review_needed") and f.get("human_review_reason"):
            reasons_present.add(f["human_review_reason"])

    for col in table.get("columns", []):
        if col.get("human_review_needed") and col.get("human_review_reason"):
            reasons_present.add(col["human_review_reason"])
        if col.get("role") == "unknown":
            reasons_present.add("uncertain_semantic_role")

    if not reasons_present:
        return False, None

    reason = min(reasons_present, key=lambda r: _REASON_PRIORITY.get(r, len(REVIEW_REASONS)))
    return True, reason


def _norm_header_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


# Trailing unit tokens that pymupdf often flattens onto a leaf name
# ("North DMC\n%" → "North DMC %") and then get re-attached as phantom cols.
_UNIT_SUFFIX_RE = re.compile(
    r"(?:\s*%|\s+(?:pct|percent(?:age)?|\bin\s+(?:lakhs?|thousands?|crores?|millions?)))$",
    re.IGNORECASE,
)
_UNIT_LEAF_RE = re.compile(
    r"^(?:%|pct|percent(?:age)?|(?:in\s+)?(?:lakhs?|thousands?|crores?|millions?))$",
    re.IGNORECASE,
)


def _strip_unit_suffix(value: Any) -> str:
    """'north dmc %' / 'north dmc percent' → 'north dmc'."""
    s = _norm_header_key(value)
    if not s:
        return ""
    stripped = _UNIT_SUFFIX_RE.sub("", s).strip()
    return stripped or s


def _header_alias_keys(value: Any, path: Any = None) -> set:
    """Match keys for a header, including unit-suffix and parent/leaf variants."""
    keys: set = set()
    leaf = _norm_header_key(value)
    if leaf:
        keys.add(leaf)
        keys.add(_strip_unit_suffix(leaf))

    path_clean: List[str] = []
    if isinstance(path, (list, tuple)):
        path_clean = [str(p).strip() for p in path if str(p).strip()]
    if path_clean:
        last = path_clean[-1]
        keys.add(_norm_header_key(last))
        keys.add(_strip_unit_suffix(last))
        # Leaf is only "%" / "percent" → identity is the parent agency name.
        if len(path_clean) >= 2 and _UNIT_LEAF_RE.match(last):
            keys.add(_norm_header_key(path_clean[-2]))
        if len(path_clean) >= 2:
            joined = f"{path_clean[-2]} {path_clean[-1]}"
            dashed = f"{path_clean[-2]} - {path_clean[-1]}"
            keys.add(_norm_header_key(joined))
            keys.add(_strip_unit_suffix(joined))
            keys.add(_norm_header_key(dashed))
            keys.add(_strip_unit_suffix(dashed))
            keys.add(_norm_header_key(" / ".join(path_clean)))
    return {k for k in keys if k}


def _candidate_is_duplicate_of_columns(
    m: Dict[str, Any],
    fallback_name: str,
    columns: List[Dict[str, Any]],
) -> bool:
    """True when candidate header is a unit-suffixed clone of an LLM column."""
    path = _header_path_from_meta(m, fallback_name)
    leaf = str(m.get("name") or fallback_name or "").strip()
    cand_keys = _header_alias_keys(leaf, path)
    if not cand_keys:
        return False
    for col in columns:
        existing = _header_alias_keys(col.get("name"), col.get("header_path"))
        if cand_keys & existing:
            return True
    return False


def _candidate_column_meta(df: pd.DataFrame) -> List[Dict[str, Any]]:
    try:
        meta = list(getattr(df, "attrs", {}).get("dhara_column_meta") or [])
    except Exception:
        meta = []
    if meta:
        return [m if isinstance(m, dict) else {} for m in meta]
    # Fallback: single-level leaves from column names only.
    return [
        {"name": str(c), "header_group": None, "header_path": [str(c)]}
        for c in df.columns
    ]


def _header_path_from_meta(m: Dict[str, Any], fallback_name: str) -> List[str]:
    raw = m.get("header_path")
    if isinstance(raw, (list, tuple)):
        path = [str(p).strip() for p in raw if str(p).strip()]
        if path:
            return path
    leaf = str(m.get("name") or fallback_name).strip() or fallback_name
    group = m.get("header_group")
    group_s = str(group).strip() if group is not None else ""
    if group_s and group_s.lower() != leaf.lower():
        return [group_s, leaf]
    return [leaf] if leaf else [fallback_name or ""]


def _table_already_has_multilevel_headers(table: Dict[str, Any]) -> bool:
    for col in table.get("columns") or []:
        path = col.get("header_path")
        if isinstance(path, (list, tuple)) and len([p for p in path if str(p).strip()]) >= 2:
            return True
        if col.get("header_group"):
            return True
    return False


def _score_candidate_for_llm_table(table: Dict[str, Any], cand: Dict[str, Any]) -> float:
    df = cand.get("df")
    if df is None:
        return float("-inf")
    llm_cols = table.get("columns") or []
    meta = _candidate_column_meta(df)
    n_llm = len(llm_cols)
    n_cand = int(df.shape[1])
    score = 0.0
    score -= abs(n_llm - n_cand) * 3.0
    if n_llm == n_cand:
        score += 12.0
    llm_keys = {_norm_header_key(c.get("name")) for c in llm_cols if c.get("name")}
    cand_keys: set = set()
    for i, name in enumerate(df.columns):
        cand_keys.add(_norm_header_key(name))
        m = meta[i] if i < len(meta) else {}
        if m.get("name"):
            cand_keys.add(_norm_header_key(m.get("name")))
        path = m.get("header_path") or []
        if isinstance(path, (list, tuple)) and path:
            cand_keys.add(_norm_header_key(path[-1]))
            # Flattened "Parent - Leaf" style LLM names.
            if len(path) >= 2:
                cand_keys.add(_norm_header_key(f"{path[-2]} - {path[-1]}"))
                cand_keys.add(_norm_header_key(f"{path[-2]} {path[-1]}"))
    overlap = len(llm_keys & cand_keys)
    score += overlap * 2.5
    if cand.get("method") in ("pymupdf_lines_strict", "pymupdf_lines"):
        score += 1.5
    # Prefer richer numeric fill when otherwise tied.
    score += min(2.0, _dataframe_numeric_fill_ratio(df))
    return score


def _pick_candidate_for_llm_table(
    table: Dict[str, Any],
    candidates: Optional[List[Dict[str, Any]]],
    used: Optional[set] = None,
) -> Optional[Dict[str, Any]]:
    if not candidates:
        return None
    used = used if used is not None else set()
    pool = [
        (i, c) for i, c in enumerate(candidates)
        if i not in used and c.get("df") is not None and not getattr(c["df"], "empty", True)
    ]
    if not pool:
        # Allow reuse if every candidate was already claimed (multi-table pages
        # with fewer candidates than LLM tables).
        pool = [
            (i, c) for i, c in enumerate(candidates)
            if c.get("df") is not None and not getattr(c["df"], "empty", True)
        ]
    if not pool:
        return None
    best_i, best = max(pool, key=lambda ic: _score_candidate_for_llm_table(table, ic[1]))
    if _score_candidate_for_llm_table(table, best) < -20:
        return None
    used.add(best_i)
    return best



def _header_leaves_fuzzy_match(a: Any, b: Any) -> bool:
    """True when leaves are the same or one is a prefixed variant of the other.

    Structural only: 'Age <1' ↔ '<1', 'Birth Weight M' ↔ 'M'. Avoids treating
    LLM renames as distinct columns during candidate↔LLM alignment.
    """
    aa = _norm_header_key(a)
    bb = _norm_header_key(b)
    if not aa or not bb:
        return False
    if aa == bb:
        return True
    # Prefer longer containment with a word/token boundary so '1' does not
    # match '15-24', but 'age <1' / '<1' and 'age 1-4' / '1-4' do.
    if len(aa) >= len(bb):
        longer, shorter = aa, bb
    else:
        longer, shorter = bb, aa
    if len(shorter) < 1:
        return False
    if longer.endswith(" " + shorter) or longer.startswith(shorter + " "):
        return True
    # Tight codes like '<1', '>=70', '1-4' often appear after a dimension word
    # with no extra punctuation: 'age<1' after aggressive normalize is rare,
    # but 'age 1-4' already handled above.
    return False


def _map_meta_indices_to_llm_columns(
    columns: List[Dict[str, Any]],
    meta: List[Dict[str, Any]],
    df: pd.DataFrame,
) -> List[Optional[int]]:
    """For each LLM column, index into candidate meta (or None)."""
    n_llm = len(columns)
    n_meta = len(meta)
    if n_llm == n_meta:
        return list(range(n_llm))

    # Build lookup from normalized leaf / flattened / unit-stripped keys -> meta index.
    # Prefer earlier meta columns when aliases collide (e.g. "North DMC" before "North DMC %").
    key_to_meta: Dict[str, int] = {}
    meta_leaves: List[str] = []
    for i, m in enumerate(meta):
        leaf = str(m.get("name") or (df.columns[i] if i < len(df.columns) else "")).strip()
        meta_leaves.append(leaf)
        path = _header_path_from_meta(m, leaf)
        for k in _header_alias_keys(leaf, path):
            if k and k not in key_to_meta:
                key_to_meta[k] = i

    mapping: List[Optional[int]] = [None] * n_llm
    used_meta: set = set()
    for i, col in enumerate(columns):
        aliases = _header_alias_keys(col.get("name"), col.get("header_path"))
        mi = None
        for k in aliases:
            cand = key_to_meta.get(k)
            if cand is not None and cand not in used_meta:
                mi = cand
                break
        if mi is None:
            # Fuzzy: LLM often prefixes dimension words ('Age <1' vs '<1').
            llm_leaf = str(col.get("name") or "").strip()
            for cand_i, cand_leaf in enumerate(meta_leaves):
                if cand_i in used_meta:
                    continue
                if _header_leaves_fuzzy_match(llm_leaf, cand_leaf):
                    mi = cand_i
                    break
        if mi is not None:
            mapping[i] = mi
            used_meta.add(mi)

    matched = sum(1 for m in mapping if m is not None)
    # Widths nearly equal but names diverged → positional identity beats a
    # failed name map that would later splice two full grids together.
    if (
        abs(n_llm - n_meta) <= 2
        and matched < max(2, int(min(n_llm, n_meta) * 0.5))
        and min(n_llm, n_meta) >= 4
    ):
        return [i if i < n_meta else None for i in range(n_llm)]

    # Residual pairing: after exact/fuzzy hits, map leftover LLM columns onto
    # leftover meta columns in order (e.g. 'Cause of Death' ↔ 'NAME OF THE DISEASE'
    # when age bands already matched). Prevents restore+append doubling.
    unmatched_llm = [i for i, m in enumerate(mapping) if m is None]
    unused_meta = [i for i in range(n_meta) if i not in used_meta]
    if unmatched_llm and unused_meta and abs(len(unmatched_llm) - len(unused_meta)) <= 2:
        for llm_i, meta_i in zip(unmatched_llm, unused_meta):
            mapping[llm_i] = meta_i
            used_meta.add(meta_i)

    # Fill remaining by position when widths match after partial matches.
    if n_llm == n_meta:
        for i in range(n_llm):
            if mapping[i] is None and i not in used_meta:
                mapping[i] = i
                used_meta.add(i)
    return mapping


def _restore_body_merge_empties_from_df(table: Dict[str, Any], df: pd.DataFrame) -> None:
    """Re-introduce empty continuation cells so Preview can rowspan/colspan.

    The ruled pymupdf grid is the source of truth for merge structure. LLM
    reconstruction often fills those holes by forward-filling the parent value
    or inventing placeholders (0). Clear any LLM value where the candidate cell
    is empty inside a sparse (merge-bearing) column.

    Row counts may differ (LLM drops a '(1)(2)(3)' index row, etc.) — align by
    row key before comparing cells.
    """
    columns = table.get("columns") or []
    rows = table.get("rows") or []
    if not rows or df.shape[1] != len(columns):
        return

    cand_vals = df.values.tolist()
    if df.shape[0] == len(rows):
        cand = [list(r) for r in cand_vals]
    else:
        row_map = _align_llm_rows_to_candidate(rows, df)
        cand = []
        width = df.shape[1]
        for r_i in range(len(rows)):
            ci = row_map[r_i] if r_i < len(row_map) else None
            if ci is None or ci >= len(cand_vals):
                cand.append([None] * width)
            else:
                cand.append(list(cand_vals[ci]))

    nrows = len(rows)
    sparse_cols: List[int] = []
    for c in range(df.shape[1]):
        empty = sum(
            1 for r in range(nrows)
            if _cell_is_empty(cand[r][c] if c < len(cand[r]) else None)
        )
        if empty >= 1 and empty >= nrows * 0.12 and empty < nrows:
            sparse_cols.append(c)
    if not sparse_cols:
        return

    for r in range(nrows):
        row = list(rows[r])
        changed = False
        for c in sparse_cols:
            if c >= len(cand[r]) or c >= len(row):
                continue
            if not _cell_is_empty(cand[r][c]):
                continue
            if _cell_is_empty(row[c]):
                continue
            # Candidate empty ⇒ rowspan continuation; drop LLM fill/placeholder.
            row[c] = None
            changed = True
        if changed:
            rows[r] = row
    table["rows"] = rows


def _stamp_header_meta_on_column(col: Dict[str, Any], m: Dict[str, Any]) -> None:
    fallback = str(col.get("name") or "")
    path = _header_path_from_meta(m, fallback)
    if not path:
        return
    col["header_path"] = path
    col["header_group"] = path[-2] if len(path) >= 2 else None
    leaf = path[-1]
    llm_name = str(col.get("name") or "").strip()
    if leaf and (not llm_name or _norm_header_key(llm_name) != _norm_header_key(leaf)):
        if len(path) >= 2 and (
            " - " in llm_name
            or _norm_header_key(llm_name) == _norm_header_key(f"{path[-2]} {leaf}")
            or _norm_header_key(path[-2]) in _norm_header_key(llm_name)
        ):
            col["name"] = leaf


def _column_from_candidate_meta(m: Dict[str, Any], fallback_name: str = "") -> Dict[str, Any]:
    path = _header_path_from_meta(m, fallback_name or str(m.get("name") or "Col"))
    leaf = path[-1] if path else (fallback_name or "Col")
    return {
        "name": leaf,
        "header_group": path[-2] if len(path) >= 2 else None,
        "header_path": path,
        "role": "unknown",
        "concept": None,
        "description": None,
        "data_type": "unknown",
        "unit": None,
        "category": None,
        "human_review_needed": False,
        "input_type": None,
        "input_options": None,
        "human_review_reason": None,
    }


def _align_llm_rows_to_candidate(
    llm_rows: List[List[Any]],
    df: pd.DataFrame,
) -> List[Optional[int]]:
    """Map each LLM row index -> candidate row index (or None)."""
    cand_rows = df.values.tolist()
    n_llm, n_cand = len(llm_rows), len(cand_rows)
    if n_llm == n_cand:
        return list(range(n_llm))
    if n_cand == 0:
        return [None] * n_llm

    cand_by_key: Dict[str, int] = {}
    for i, row in enumerate(cand_rows):
        if not row:
            continue
        key = _norm_header_key(row[0])
        if key and key not in cand_by_key:
            cand_by_key[key] = i

    aligned: List[Optional[int]] = []
    matched = 0
    for row in llm_rows:
        key = _norm_header_key(row[0] if row else "")
        ci = cand_by_key.get(key)
        if ci is not None:
            matched += 1
        aligned.append(ci)
    if matched >= max(1, int(n_llm * 0.6)):
        return aligned
    return [i if i < n_cand else None for i in range(n_llm)]


def _merge_missing_candidate_columns(
    table: Dict[str, Any],
    df: pd.DataFrame,
    meta: List[Dict[str, Any]],
    mapping: List[Optional[int]],
) -> None:
    """Insert candidate columns the LLM dropped (e.g. trailing rowspan header).

    Walks candidate columns in order; keeps LLM semantics for matched columns
    and synthesizes missing ones from the pymupdf grid + dhara_column_meta.

    Must NOT splice a full candidate grid onto a renamed LLM grid when name
    matching failed — that doubles columns (e.g. '<1…TOTAL' + 'Age <1…').
    """
    columns = list(table.get("columns") or [])
    rows = [list(r) if isinstance(r, list) else [] for r in (table.get("rows") or [])]
    if not columns or not meta:
        return

    meta_to_llm = {
        meta_i: llm_i
        for llm_i, meta_i in enumerate(mapping)
        if meta_i is not None
    }
    matched = len(meta_to_llm)
    match_ratio = matched / max(len(columns), 1)

    missing_meta = []
    for i in range(len(meta)):
        if i in meta_to_llm:
            continue
        fallback = str(df.columns[i]) if i < len(df.columns) else ""
        # pymupdf often emits a second leaf like "North DMC %" beside "North DMC"
        # after flattening a multiline unit. The LLM already kept the real column —
        # do not restore the unit-suffixed clone.
        if _candidate_is_duplicate_of_columns(meta[i], fallback, columns):
            continue
        missing_meta.append(i)
    if not missing_meta:
        return

    # Only restore when the candidate is at least as wide (LLM skipped a col).
    if len(meta) < len(columns):
        return

    # Mapping failure (renames / prefixing), not real omissions: abort rather
    # than restore every candidate column and then append every LLM column.
    if matched == 0:
        return
    if len(missing_meta) > max(2, int(len(meta) * 0.5)) and match_ratio < 0.5:
        return

    cand_vals = df.values.tolist()
    row_map = _align_llm_rows_to_candidate(rows, df)
    missing_set = set(missing_meta)

    new_columns: List[Dict[str, Any]] = []
    sources: List[Tuple[str, int]] = []
    used_llm: set = set()

    for meta_i in range(len(meta)):
        if meta_i in meta_to_llm:
            llm_i = meta_to_llm[meta_i]
            used_llm.add(llm_i)
            new_columns.append(dict(columns[llm_i]))
            sources.append(("llm", llm_i))
        elif meta_i in missing_set:
            m = meta[meta_i]
            fallback = str(df.columns[meta_i]) if meta_i < len(df.columns) else ""
            new_columns.append(_column_from_candidate_meta(m, fallback))
            sources.append(("cand", meta_i))
        # else: unit-suffixed duplicate of an LLM column — drop it

    # Append LLM-only extras only when most LLM columns already mapped onto
    # the candidate (true additions). Low match rate ⇒ leftovers are renames
    # of columns we already restored — appending them doubles the table.
    append_unmatched = match_ratio >= 0.5
    for llm_i, col in enumerate(columns):
        if llm_i not in used_llm and append_unmatched:
            new_columns.append(dict(col))
            sources.append(("llm", llm_i))

    new_rows: List[List[Any]] = []
    for r_i, row in enumerate(rows):
        built: List[Any] = []
        cand_i = row_map[r_i] if r_i < len(row_map) else None
        for kind, idx in sources:
            if kind == "llm":
                built.append(row[idx] if idx < len(row) else None)
            else:
                if cand_i is None or cand_i >= len(cand_vals):
                    built.append(None)
                else:
                    crow = cand_vals[cand_i]
                    val = crow[idx] if idx < len(crow) else None
                    if _cell_is_empty(val):
                        built.append(None)
                    else:
                        built.append(None if isinstance(val, float) and val != val else val)
        new_rows.append(built)

    table["columns"] = new_columns
    table["rows"] = new_rows
    notes = list(table.get("notes") or [])
    note = (
        f"ADDED: restored {len(missing_meta)} column(s) from pymupdf candidate "
        "that the LLM reconstruction omitted (often a trailing rowspan header)."
    )
    if note not in notes:
        notes.append(note)
    table["notes"] = notes


def _stamp_bbox_from_candidate(table: Dict[str, Any], cand: Optional[Dict[str, Any]]) -> None:
    """Persist pymupdf region for PDF snapshot comparison in review UI."""
    if not cand or table.get("bbox"):
        return
    bb = cand.get("bbox")
    if bb and len(bb) >= 4:
        table["bbox"] = [float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])]


def _attach_structure_from_candidates(
    table: Dict[str, Any],
    candidates: Optional[List[Dict[str, Any]]],
    used: Optional[set] = None,
) -> Dict[str, Any]:
    """Copy multi-level headers / merge empties from pymupdf, and restore any
    columns the LLM dropped (e.g. last rowspan measure). Does not change the
    extraction prompt or overwrite existing LLM cell values for matched cols."""
    cand = _pick_candidate_for_llm_table(table, candidates, used)
    if cand is None:
        return table
    _stamp_bbox_from_candidate(table, cand)
    df = cand["df"]
    meta = _candidate_column_meta(df)
    columns = table.get("columns") or []
    if not columns or not meta:
        return table

    mapping = _map_meta_indices_to_llm_columns(columns, meta, df)
    _merge_missing_candidate_columns(table, df, meta, mapping)

    columns = table.get("columns") or []
    mapping = _map_meta_indices_to_llm_columns(columns, meta, df)

    for llm_i, meta_i in enumerate(mapping):
        if meta_i is None or meta_i >= len(meta):
            continue
        col = columns[llm_i]
        existing = col.get("header_path")
        if isinstance(existing, (list, tuple)) and [p for p in existing if str(p).strip()]:
            if not col.get("header_group") and len(existing) >= 2:
                col["header_group"] = str(existing[-2]).strip() or None
            continue
        _stamp_header_meta_on_column(col, meta[meta_i])
    table["columns"] = columns

    _restore_body_merge_empties_from_df(table, df)
    return table



def _recover_missing_ruled_tables(
    tables: List[Dict[str, Any]],
    candidates: Optional[List[Dict[str, Any]]],
    page_num: int,
    page_text: str,
    used_candidate_idxs: set,
) -> List[Dict[str, Any]]:
    """If the LLM collapsed/omitted distinct ruled tables, restore them.

    When the page has multiple non-overlapping ruled regions but fewer LLM
    tables, rebuild from those ruled candidates (preserving LLM title /
    classification by reading order when available). Does not change how
    cells are extracted — only which physical tables are kept.
    """
    ruled = _distinct_ruled_candidates(candidates)
    if len(ruled) <= 1 or len(tables) >= len(ruled):
        return tables

    cand_list = list(candidates or [])
    out: List[Dict[str, Any]] = []
    for i, rc in enumerate(ruled):
        extra = table_dict_from_df(
            rc["df"],
            page_text=page_text,
            page_num=page_num,
            method=str(rc.get("method") or "pymupdf_lines_strict"),
        )
        extra["page"] = page_num
        if rc.get("bbox") and len(rc["bbox"]) >= 4:
            extra["bbox"] = [float(x) for x in rc["bbox"][:4]]
        # Prefer LLM semantics for the same ordinal when present.
        if i < len(tables):
            src = tables[i]
            if (src.get("title") or "").strip():
                extra["title"] = src.get("title")
                if src.get("title_source"):
                    extra["title_source"] = src.get("title_source")
            if src.get("description"):
                extra["description"] = src.get("description")
            if isinstance(src.get("classification"), dict) and src.get("classification"):
                extra["classification"] = src.get("classification")
                extra["semantic_status"] = src.get("semantic_status") or "classified"
            else:
                extra["semantic_status"] = "not_classified"
            # Carry column-level semantics when widths match.
            src_cols = src.get("columns") or []
            if len(src_cols) == len(extra.get("columns") or []):
                for j, col in enumerate(extra["columns"]):
                    sc = src_cols[j]
                    for key in (
                        "role", "concept", "description", "data_type", "unit",
                        "category", "human_review_needed", "input_type",
                        "input_options", "human_review_reason",
                    ):
                        if sc.get(key) is not None:
                            col[key] = sc.get(key)
        else:
            extra["semantic_status"] = "not_classified"
            extra["notes"] = list(extra.get("notes") or []) + [
                "ADDED: recovered ruled-border table omitted/collapsed by LLM reconstruction."
            ]

        if (tables and any(
            (t.get("extraction") or {}).get("confidence") == "alignment_guard_fallback"
            for t in tables
        )):
            extra["extraction"] = {
                "method": f"pymupdf_recovered<{rc.get('method')}>",
                "confidence": "alignment_guard_fallback",
            }
        extra["human_review_needed"], extra["human_review_reason"] = derive_human_review_needed(extra)
        out.append(extra)

        for idx, c in enumerate(cand_list):
            if c is rc or _bbox_iou(c.get("bbox"), rc.get("bbox")) >= 0.9:
                used_candidate_idxs.add(idx)
    return out


def _stamp_llm_metadata(
    page_result: Dict[str, Any],
    page_num: int,
    candidates: Optional[List[Dict[str, Any]]] = None,
    page_text: str = "",
) -> Dict[str, Any]:
    """Adds the pipeline-level bookkeeping fields (which extraction path
    produced this, whether it's been semantically classified, whether a
    human needs to review it and why, which page) that we already know
    deterministically -- not something we trust the LLM to self-report.

    ADDED: strips ungrounded Direction/Trend columns, then runs
    _apply_column_alignment_guard, then attaches pymupdf multi-level header
    meta / merge empties, before derive_human_review_needed."""
    # Dedupe strategy clones so attach/guard/recover see one grid per region.
    candidates = dedupe_candidates_by_bbox(list(candidates or []))
    tables = []
    used_candidates: set = set()
    for t in page_result.get("tables", []):
        normalized = _normalize_table(t)
        normalized = _strip_ungrounded_direction_columns(normalized, candidates, page_text)
        normalized = _apply_column_alignment_guard(normalized, candidates, used_candidates)
        if normalized.pop("_skip_structure_attach", False):
            pass
        else:
            normalized = _attach_structure_from_candidates(normalized, candidates, used_candidates)
            normalized["columns"] = dedupe_column_names(normalized.get("columns") or [])
        normalized["semantic_status"] = "classified"
        if not (isinstance(normalized.get("extraction"), dict) and normalized["extraction"].get("confidence") == "alignment_guard_fallback"):
            normalized["extraction"] = {"method": "pymupdf+llm", "confidence": "llm_validated"}
        normalized["page"] = page_num
        if not normalized.get("bbox"):
            matched, _ = _best_matching_ruled_candidate(normalized, candidates, used_candidates)
            _stamp_bbox_from_candidate(
                normalized,
                matched or _best_lines_strict_candidate(candidates),
            )
        normalized["human_review_needed"], normalized["human_review_reason"] = derive_human_review_needed(normalized)
        tables.append(normalized)

    tables = _recover_missing_ruled_tables(
        tables, candidates, page_num, page_text, used_candidates
    )
    return {"tables": tables}


def build_validation_prompt(page_num: int, candidates: List[Dict[str, Any]], text: str) -> str:
    candidates = dedupe_candidates_by_bbox(candidates)
    ruled_n = len(_distinct_ruled_candidates(candidates))
    sections = [f"--- {t['method']}, table {i + 1} ---\n{df_to_text(t['df'])}" for i, t in enumerate(candidates)]
    count_hint = (
        f"Ruled-border detectors found {ruled_n} distinct table region(s) on this page. "
        f"Return exactly {ruled_n} object(s) in \"tables\" unless the raw text clearly shows otherwise.\n\n"
        if ruled_n else ""
    )

    return f"""You are processing page {page_num} of an Indian government survey PDF (SDA_INDIA). You have two jobs on
this page, in order, in this same response:

A. RECONSTRUCT each table on the page.
B. UNDERSTAND what each reconstructed table means (initial semantic classification only).

You are given one or more independent extractions of the same page's table(s) by detection
strategies (pymupdf_lines_strict / pymupdf_lines for ruled borders, and pymupdf_text for
whitespace alignment), plus the raw page text for grounding. The strategies frequently
disagree: one may merge two columns, split a multi-line header across rows, drop a footnote, or misread a
numeric column. Candidates with different vertical positions are DIFFERENT tables.

Raw page text:
{text[:3000]}

Extracted candidates:
{chr(10).join(sections) if sections else '(no table candidates extracted on this page)'}

{count_hint}{TASK_A_RECONSTRUCTION_RULES}

{TASK_B_CLASSIFICATION_RULES}

Return ONLY valid JSON (no markdown fences) shaped as:
{TABLE_SCHEMA_EXAMPLE}
If there is genuinely no table on this page, return {{"tables": []}}."""


def validate_page(client: openai.OpenAI, page_num: int, candidates: List[Dict[str, Any]], text: str) -> Dict[str, Any]:
    prompt = build_validation_prompt(page_num, candidates, text)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        max_tokens=SINGLE_PAGE_MAX_TOKENS,
        temperature=0,
    )
    text_out = resp.choices[0].message.content
    try:
        return json.loads(text_out)
    except json.JSONDecodeError:
        cleaned = re.sub(r"```[a-z]*\n?", "", text_out).strip().rstrip("`")
        return json.loads(cleaned)


def validate_all_pages(pages_grouped: Dict[int, List[Dict[str, Any]]], page_text: Dict[int, str],
                        n_workers: int = OPENAI_WORKERS) -> Dict[int, Dict[str, Any]]:
    client = openai.OpenAI()
    validated: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {
            pool.submit(validate_page, client, page_num, candidates, page_text.get(page_num, "")): page_num
            for page_num, candidates in pages_grouped.items()
        }
        done = 0
        for future in as_completed(futures):
            page_num = futures[future]
            done += 1
            try:
                result = future.result()
            except Exception as e:
                log(f"  page {page_num}: validation failed ({e})")
                continue
            validated[page_num] = result
            if done % 20 == 0 or done == len(futures):
                log(f"  validated {done}/{len(futures)} pages")
    return validated


# ── Stage 4: batched OpenAI validation (for the "needs LLM" bucket) ─────

def build_batch_validation_prompt(pages: List[int], pages_grouped: Dict[int, List[Dict[str, Any]]],
                                   page_text: Dict[int, str]) -> str:
    page_sections = []
    for page_num in pages:
        candidates = dedupe_candidates_by_bbox(pages_grouped.get(page_num, []))
        ruled_n = len(_distinct_ruled_candidates(candidates))
        sections = [f"  --- {t['method']}, table {i + 1} ---\n{df_to_text(t['df'], max_rows=40)}" for i, t in enumerate(candidates)]
        text = page_text.get(page_num, "")[:RAW_TEXT_CHARS_PER_PAGE_BATCHED]
        count_hint = (
            f"\nRuled-border detectors found {ruled_n} distinct table region(s). "
            f"Return exactly {ruled_n} table object(s) for this page unless raw text clearly shows otherwise."
            if ruled_n else ""
        )
        page_sections.append(
            f"=== PAGE {page_num} ===\n"
            f"Raw page text:\n{text}\n\n"
            f"Extracted candidates:\n{chr(10).join(sections) if sections else '  (no table candidates extracted on this page)'}"
            f"{count_hint}"
        )

    return f"""You are processing {len(pages)} pages of an Indian government survey PDF (SDA_INDIA). For each page you
have two jobs, in order, in this same response: A) reconstruct each table on that page, B) understand what each
reconstructed table means (initial semantic classification only).

For each page below, you are given one or more independent extractions of that page's table(s) by detection
strategies (pymupdf_lines_strict / pymupdf_lines for ruled borders, and pymupdf_text for whitespace alignment),
plus the raw page text for grounding. Candidates at different vertical positions are DIFFERENT tables — do not
merge them. The strategies frequently disagree: one may merge two columns, split a multi-line header across rows,
drop a footnote, misread a numeric column, glue the header into the first data row, or -- for pages routed here
specifically because they looked ambiguous -- produce a nearly empty or garbled result that only the raw text can clarify.

{chr(10).join('----------------------------------------' + chr(10) + s for s in page_sections)}

{TASK_A_RECONSTRUCTION_RULES}
- If a page genuinely has no table, its entry should be {{"tables": []}}.

{TASK_B_CLASSIFICATION_RULES}

Return ONLY valid JSON (no markdown fences) with exactly one top-level key "pages", mapping each page number
(as a string) to its own {{"tables": [...]}} object shaped like this per table:
{TABLE_SCHEMA_EXAMPLE}
Include an entry for every one of these page numbers, even if empty: {pages}"""


def validate_batch(client: openai.OpenAI, pages: List[int], pages_grouped: Dict[int, List[Dict[str, Any]]],
                    page_text: Dict[int, str]) -> Dict[int, Dict[str, Any]]:
    prompt = build_batch_validation_prompt(pages, pages_grouped, page_text)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        max_tokens=min(16000, MAX_TOKENS_PER_PAGE * len(pages)),
        temperature=0,
    )
    text_out = resp.choices[0].message.content
    try:
        parsed = json.loads(text_out)
    except json.JSONDecodeError:
        cleaned = re.sub(r"```[a-z]*\n?", "", text_out).strip().rstrip("`")
        parsed = json.loads(cleaned)

    by_page = parsed.get("pages", {})
    # ADDED: pass per-page pymupdf candidates + page text into stamp so
    # ungrounded Direction columns can be stripped and alignment guard can
    # fall back when the LLM grid is shifted.
    return {
        p: _stamp_llm_metadata(
            by_page.get(str(p), {"tables": []}),
            p,
            pages_grouped.get(p),
            page_text.get(p, ""),
        )
        for p in pages
    }


def validate_all_pages_batched(pages_grouped: Dict[int, List[Dict[str, Any]]], page_text: Dict[int, str],
                                batch_size: int = BATCH_SIZE, n_workers: int = OPENAI_WORKERS,
                                progress_cb: Optional[Callable[[int, int], None]] = None,
                                api_key: Optional[str] = None) -> Dict[int, Dict[str, Any]]:
    client = openai.OpenAI(api_key=api_key)
    all_pages = list(pages_grouped.keys())
    batches = [all_pages[i:i + batch_size] for i in range(0, len(all_pages), batch_size)]

    validated: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {pool.submit(validate_batch, client, batch, pages_grouped, page_text): batch for batch in batches}
        done_pages = 0
        for future in as_completed(futures):
            batch = futures[future]
            try:
                result = future.result()
            except Exception as e:
                log(f"  batch {batch[0]}-{batch[-1]} failed, falling back to per-page ({e})")
                for page_num in batch:
                    try:
                        result_single = validate_page(client, page_num, pages_grouped[page_num], page_text.get(page_num, ""))
                        # ADDED: pass candidates + page text for Direction strip / alignment guard.
                        validated[page_num] = _stamp_llm_metadata(
                            result_single,
                            page_num,
                            pages_grouped.get(page_num),
                            page_text.get(page_num, ""),
                        )
                    except Exception as e2:
                        log(f"    page {page_num}: per-page fallback also failed ({e2})")
                done_pages += len(batch)
                log(f"  validated {done_pages}/{len(all_pages)} pages")
                if progress_cb:
                    progress_cb(done_pages, len(all_pages))
                continue
            validated.update(result)
            done_pages += len(batch)
            log(f"  validated {done_pages}/{len(all_pages)} pages ({len(batches)} batches of ~{batch_size})")
            if progress_cb:
                progress_cb(done_pages, len(all_pages))
    return validated


def _log_representative_examples(llm_results: Dict[int, Dict[str, Any]], high_results: Dict[int, Dict[str, Any]]) -> None:
    """Logs up to three examples for a quick sanity check: one table that
    needs no review, one flagged for semantic classification uncertainty,
    one flagged for data reconstruction uncertainty (uncertain_cells). Not
    every run will have all three -- e.g. a small page range might not
    contain an uncertain_cells case -- so each is best-effort."""

    def _describe(page_num: int, t: Dict[str, Any], why: str) -> None:
        log(f"  example ({why}) -- page {page_num}: title={t.get('title')!r}")
        log(f"    human_review_needed={t.get('human_review_needed')}, human_review_reason={t.get('human_review_reason')!r}")
        log(f"    semantic_status={t.get('semantic_status')}, extraction={t.get('extraction')}, uncertain_cells={t.get('uncertain_cells')}")
        cls = t.get("classification") or {}
        flagged_fields = [(name, f.get("human_review_reason")) for name, f in cls.items()
                          if isinstance(f, dict) and f.get("human_review_needed")]
        log(f"    classification fields flagged for review: {flagged_fields or 'none'}")
        for col in t.get("columns", [])[:4]:
            log(f"    column {col.get('name')!r}: role={col.get('role')}, concept={col.get('concept')}, "
                f"human_review_needed={col.get('human_review_needed')}, human_review_reason={col.get('human_review_reason')!r}")

    no_review = semantic_review = extraction_review = None
    for page_num, result in llm_results.items():
        for t in result.get("tables", []):
            if not no_review and not t.get("human_review_needed"):
                no_review = (page_num, t)
            if not extraction_review and t.get("uncertain_cells"):
                extraction_review = (page_num, t)
            if not semantic_review and t.get("human_review_needed") and not t.get("uncertain_cells"):
                semantic_review = (page_num, t)

    if no_review:
        _describe(*no_review, why="no review needed")
    if semantic_review:
        _describe(*semantic_review, why="semantic classification uncertainty")
    if extraction_review:
        _describe(*extraction_review, why="data reconstruction uncertainty")
    if not (no_review or semantic_review or extraction_review):
        log("  (no LLM-classified tables to show examples from)")


def run_pipeline(pdf_path: Path, on_progress: Optional[Callable[[str, int, str], None]] = None,
                  api_key: Optional[str] = None) -> Dict[int, Dict[str, Any]]:
    """Programmatic entry point for running the full pipeline on an arbitrary
    PDF (used by the /api/pdf/* endpoints in main.py for a user-uploaded
    file). Mirrors main()'s CLI orchestration but takes an explicit path,
    returns the validated-by-page dict directly instead of writing a JSON
    file, and reports coarse progress via on_progress(stage, percent, message)
    so a caller (e.g. a FastAPI background job) can surface a progress bar.

    Runs synchronously and blocks for as long as the pipeline takes (minutes,
    for a large PDF) -- callers on an event loop must wrap this in
    asyncio.to_thread rather than awaiting it directly."""

    def progress(stage: str, percent: int, message: str) -> None:
        log(message)
        if on_progress:
            on_progress(stage, percent, message)

    progress("classify", 2, f"Scanning {pdf_path.name} for text-bearing pages")
    text_pages, page_text = classify_pages(pdf_path)
    progress("classify", 10, f"{len(text_pages)} text-bearing page(s) found")

    progress("extract", 10, f"Extracting tables from {len(text_pages)} page(s)")
    all_tables = extract_all_tables(
        pdf_path, text_pages,
        progress_cb=lambda done, total: progress("extract", 10 + int(35 * done / total), f"Extracted {done}/{total} page(s)"),
    )
    progress("extract", 45, f"{len(all_tables)} table candidate(s) found")

    pages_grouped = filter_candidate_pages(group_by_page(all_tables))
    pages_grouped = resolve_dual_column_pages(pdf_path, pages_grouped, page_text)
    outline_index = build_pdf_outline_index(pdf_path)
    high_results, llm_pages, reason_counts = split_by_confidence(
        pages_grouped,
        page_text,
        pdf_path=pdf_path,
        outline_index=outline_index,
    )
    progress("classify_confidence", 55,
              f"{len(high_results)} page(s) auto-accepted, {len(llm_pages)} page(s) need AI validation")

    validated_by_page: Dict[int, Dict[str, Any]] = dict(high_results)
    if llm_pages:
        llm_results = validate_all_pages_batched(
            llm_pages, page_text, api_key=api_key,
            progress_cb=lambda done, total: progress("validate", 55 + int(45 * done / total), f"AI-validated {done}/{total} page(s)"),
        )
        validated_by_page.update(llm_results)

    progress("done", 100, f"Pipeline complete -- {len(validated_by_page)} page(s) with tables")
    return dict(sorted(validated_by_page.items()))


# ── Orchestration ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N text-bearing pages (for quick smoke tests). Default: all pages.")
    parser.add_argument("--pages", type=str, default=None, help="Only process text-bearing pages in this 1-based PDF page range, e.g. '80-140'. Takes precedence over --limit.")
    parser.add_argument("--skip-validation", action="store_true", help="Stop after table extraction, skip the OpenAI step.")
    args = parser.parse_args()

    assert PDF_PATH.exists(), f"PDF not found at {PDF_PATH.resolve()}"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    t_start = time.time()

    log(f"Stage 1: classifying pages in {PDF_PATH.name}")
    t0 = time.time()
    text_pages, page_text = classify_pages(PDF_PATH)
    log(f"  {len(text_pages)} text-bearing page(s) found in {time.time() - t0:.1f}s")

    if args.pages:
        start, end = (int(x) for x in args.pages.split("-", 1))
        target_pages = [p for p in text_pages if start <= p <= end]
    elif args.limit is not None:
        target_pages = text_pages[: args.limit]
    else:
        target_pages = text_pages
    log(f"Running on {len(target_pages)} page(s)")

    log(f"Stage 2: extracting tables with pymupdf ({CPU_WORKERS} workers)")
    t0 = time.time()
    all_tables = extract_all_tables(PDF_PATH, target_pages)
    log(f"  {len(all_tables)} table candidate(s) found in {time.time() - t0:.1f}s")

    pages_grouped = group_by_page(all_tables)
    log(f"  {len(pages_grouped)} page(s) have at least one table candidate")

    pages_grouped = filter_candidate_pages(pages_grouped)
    log(f"  {len(pages_grouped)} page(s) kept after requiring a ruled-border hit "
        f"(lines_strict or lines) -- drops likely false positives from the looser text strategy")

    pages_grouped = resolve_dual_column_pages(PDF_PATH, pages_grouped, page_text)

    log("Stage 3: confidence-classifying pages (no LLM)")
    t0 = time.time()
    outline_index = build_pdf_outline_index(PDF_PATH)
    high_results, llm_pages, reason_counts = split_by_confidence(
        pages_grouped,
        page_text,
        pdf_path=PDF_PATH,
        outline_index=outline_index,
    )
    log(f"  {len(high_results)} page(s) auto-accepted (no LLM call), {len(llm_pages)} page(s) need OpenAI validation, in {time.time() - t0:.1f}s")
    for reason, count in sorted(reason_counts.items(), key=lambda kv: -kv[1]):
        log(f"    [llm bucket] {count}x: {reason}")

    validated_by_page: Dict[int, Dict[str, Any]] = dict(high_results)

    if args.skip_validation:
        log(f"Skipping OpenAI validation (--skip-validation) -- output only has the {len(high_results)} auto-accepted page(s).")
    else:
        log(f"Stage 4: validating/restructuring {len(llm_pages)} page(s) with OpenAI (batches of {BATCH_SIZE}, {OPENAI_WORKERS} workers)")
        t0 = time.time()
        llm_results = validate_all_pages_batched(llm_pages, page_text)
        log(f"  validated {len(llm_results)} page(s) in {time.time() - t0:.1f}s")
        validated_by_page.update(llm_results)

        _log_representative_examples(llm_results, high_results)

    validated_by_page = dict(sorted(validated_by_page.items()))
    out_path = OUTPUT_DIR / f"validated_tables_pages_1-{max(target_pages)}.json"
    with open(out_path, "w") as f:
        json.dump(validated_by_page, f, indent=2, default=str)
    log(f"Saved {len(validated_by_page)} page(s) to {out_path}")
    log(f"Total time: {time.time() - t_start:.1f}s")


if __name__ == "__main__":
    main()
