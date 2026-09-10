"""
Worker functions for parallel table extraction, run inside a
ProcessPoolExecutor from sda_india_pdf_extraction.py.

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

Two pymupdf strategies are run per page as independent candidates for the
OpenAI validation layer to reconcile, mirroring the original camelot-lattice
(ruled borders) vs camelot-stream (text position) split:
  - "lines_strict": only detects tables with actual ruled border lines.
  - "text":          infers columns from text alignment/whitespace, like
                      camelot's stream mode -- catches borderless tables.
"""

from typing import Any, Dict, List

import pymupdf


def extract_pymupdf_chunk(pdf_path: str, pages: List[int]) -> List[Dict[str, Any]]:
    """Runs both pymupdf table-detection strategies over one chunk of pages."""
    from pdf_header_utils import dataframe_from_extracted_rows

    results: List[Dict[str, Any]] = []
    if not pages:
        return results

    doc = pymupdf.open(pdf_path)
    try:
        for page_num in pages:
            page = doc[page_num - 1]
            for strategy in ("lines_strict", "text"):
                try:
                    found = page.find_tables(strategy=strategy)
                except Exception as e:
                    print(f"[pymupdf:{strategy}] page {page_num} failed: {e}")
                    continue
                for tab in found.tables:
                    rows = tab.extract()
                    if not rows:
                        continue
                    # Flatten multi-row / merged headers (e.g. "In Lakhs" spanning
                    # Mid Year Population + No. of Births) before building the DF.
                    df = dataframe_from_extracted_rows(rows)
                    if df is None or df.empty:
                        continue
                    bb = tab.bbox
                    results.append({
                        "page": page_num,
                        "method": f"pymupdf_{strategy}",
                        "df": df,
                        # Needed to detect side-by-side dual-column stacks and
                        # to clip left/right halves without re-detecting.
                        "bbox": [float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])],
                    })
    finally:
        doc.close()
    return results
