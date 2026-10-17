"""Non-response annexures with blank reason columns must auto-accept.

A gappy 1..N index strip (missing ``3`` under Planned) used to keep the strip
in the profile, tank ``nonempty_ratio``, and send the page to LLM — which then
invented merges and an extra trailing column.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.confidence_validation.table_confidence import (
    _structural_bucket_for_df,
    classify_page,
)
from app.services.extraction.pdf.utils.workers import extract_pymupdf_chunk


PDF = Path("/Users/sriramrahul/Desktop/data/testing pdf/1822-326-353-15-25.pdf")


def test_page1_non_response_auto_accepts_when_pdf_present():
    if not PDF.is_file():
        return
    cands = extract_pymupdf_chunk(str(PDF), [1])
    assert cands
    bucket, reason, _info = classify_page(cands)
    assert bucket == "high", (bucket, reason)
    strict = [c for c in cands if c.get("method") == "pymupdf_lines_strict"]
    assert strict
    df = strict[0]["df"]
    assert df.shape[1] == 13
    # No gappy index legend as first body row.
    assert str(df.iloc[0, 1]) == "Thiruvananthapuram"
    assert str(df.iloc[0, 2]) == "132"
    # No phantom 14th column.
    assert "Col_" not in "".join(str(c) for c in df.columns)
    bucket_df, reason_df, info = _structural_bucket_for_df(df)
    assert bucket_df == "high", (bucket_df, reason_df, info)
