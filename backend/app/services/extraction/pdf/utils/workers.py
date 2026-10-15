"""
Worker functions for parallel table extraction, run inside a
ProcessPoolExecutor from app.services.extraction.pdf.utils.pymupdf.

Pulled out into their own module (rather than defined inline in the calling
script) because ProcessPoolExecutor on macOS uses the "spawn" start method,
which pickles submitted tasks by reference to an *importable* module --
functions defined in the caller's own `__main__` can't be re-imported by a
child process. A plain module makes them picklable.

Each worker opens the PDF once and handles a whole chunk of pages, rather
than one process per page, since re-opening a 150MB+ PDF per page would
dominate the runtime.

Table detection uses pymupdf exclusively, not camelot/pdfplumber. Both of
those libraries lean on pdfminer for layout analysis, and pdfminer is
pathologically slow on a handful of this PDF's pages (heavy vector
graphics) -- one page can single-handedly pin a worker for 5+ minutes while
every other worker finishes in under 2, and no chunking strategy fixes that
because the slow page still has to be parsed by *something*. pymupdf's
C-based engine parses the same pages in ~0.4s on average with no page
anywhere near that pathological (worst observed: ~7s on a 346-page sweep).

Ruled pymupdf strategies are run per page as independent candidates for the
OpenAI validation layer to reconcile (camelot lattice-style):
  - "lines_strict": only detects tables with explicit ruled border lines.
  - "lines":         ruled-border detection with a looser line threshold —
                      catches tables whose grid lines are light/dashed/partial
                      (common in CRS/statistical PDFs) that lines_strict misses.
The whitespace "text" strategy is off by default (PDF_EXTRACT_TEXT_STRATEGY=1
to enable): text-only pages are filtered out later, and text clones on ruled
pages mainly inflate LLM prompts on large PDFs.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

import pymupdf


def _bbox_for_row_slice(
    tab: Any,
    start: int,
    end: int,
    fallback: Sequence[float],
) -> List[float]:
    """Slice a table bbox vertically to match a row segment (avoids dedupe collapse)."""
    fx0, fy0, fx1, fy1 = (float(fallback[0]), float(fallback[1]), float(fallback[2]), float(fallback[3]))
    row_objs = getattr(tab, "rows", None) or []
    if not row_objs or start >= len(row_objs):
        return [fx0, fy0, fx1, fy1]
    end_i = min(max(end, start + 1), len(row_objs))
    ys0 = [float(getattr(row_objs[i], "bbox", (fx0, fy0, fx1, fy1))[1]) for i in range(start, end_i)]
    ys1 = [float(getattr(row_objs[i], "bbox", (fx0, fy0, fx1, fy1))[3]) for i in range(start, end_i)]
    return [fx0, min(ys0) if ys0 else fy0, fx1, max(ys1) if ys1 else fy1]


def _candidates_from_pymupdf_table(
    tab: Any,
    *,
    page_num: int,
    method: str,
    extra: Optional[Dict[str, Any]] = None,
    page: Any = None,
    page_text: str = "",
) -> List[Dict[str, Any]]:
    """Build one candidate per physical table; split glued multi-TABLE grids."""
    from app.services.extraction.pdf.utils.header_utils import dataframe_from_extracted_rows, split_extracted_rows_on_table_markers
    from app.services.extraction.pdf.confidence_validation.table_confidence import looks_like_chart_candidate

    rows = tab.extract()
    if not rows:
        return []
    bb = tab.bbox
    fallback = [float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])]
    segments = split_extracted_rows_on_table_markers(rows)
    out: List[Dict[str, Any]] = []
    for seg_rows, start, end in segments:
        df = dataframe_from_extracted_rows(seg_rows)
        if df is None or getattr(df, "empty", True):
            continue
        bbox = _bbox_for_row_slice(tab, start, end, fallback)
        is_chart, reason = looks_like_chart_candidate(
            df, page=page, bbox=bbox, page_text=page_text,
        )
        if is_chart:
            print(f"[pymupdf:{method}] page {page_num} skipped chart-like region: {reason}")
            continue
        cand: Dict[str, Any] = {
            "page": page_num,
            "method": method,
            "df": df,
            # Needed to detect side-by-side dual-column stacks and
            # to clip left/right halves without re-detecting.
            "bbox": bbox,
        }
        if extra:
            cand.update(extra)
        if len(segments) > 1:
            cand["split_from_merged_grid"] = True
        out.append(cand)
    return out


def _run_strategies_on_page(
    page: Any,
    page_num: int,
    page_text: str,
    strategies: Sequence[str],
) -> List[Dict[str, Any]]:
    """Run find_tables strategies and build candidates for one page."""
    results: List[Dict[str, Any]] = []
    for strategy in strategies:
        try:
            found = page.find_tables(strategy=strategy)
        except Exception as e:
            print(f"[pymupdf:{strategy}] page {page_num} failed: {e}")
            continue
        for tab in found.tables:
            # Flatten multi-row / merged headers (e.g. "In Lakhs" spanning
            # Mid Year Population + No. of Births) before building the DF.
            # Also split glued consecutive tables that share one pymupdf bbox.
            results.extend(
                _candidates_from_pymupdf_table(
                    tab,
                    page_num=page_num,
                    method=f"pymupdf_{strategy}",
                    page=page,
                    page_text=page_text,
                )
            )
    return results


def extract_pymupdf_chunk(pdf_path: str, pages: List[int]) -> List[Dict[str, Any]]:
    """Runs pymupdf table-detection strategies over one chunk of pages.

    Ruled strategies (lines_strict, lines) always run. The text strategy is
    off by default: text-only pages are dropped by ``filter_candidate_pages``,
    and text clones on ruled pages mainly bloat LLM prompts. Opt back in with
    PDF_EXTRACT_TEXT_STRATEGY=1.
    """
    import os

    results: List[Dict[str, Any]] = []
    if not pages:
        return results

    force_text = (os.environ.get("PDF_EXTRACT_TEXT_STRATEGY") or "").strip() in (
        "1", "true", "True", "yes", "YES",
    )

    doc = pymupdf.open(pdf_path)
    try:
        for page_num in pages:
            page = doc[page_num - 1]
            try:
                page_text = page.get_text("text") or ""
            except Exception:
                page_text = ""
            page_hits = _run_strategies_on_page(
                page, page_num, page_text, ("lines_strict", "lines"),
            )
            if force_text:
                # Old three-strategy behaviour. Text-only pages are still
                # dropped by filter_candidate_pages; useful for debugging.
                page_hits.extend(
                    _run_strategies_on_page(page, page_num, page_text, ("text",))
                )
            results.extend(page_hits)
    finally:
        doc.close()
    return results
