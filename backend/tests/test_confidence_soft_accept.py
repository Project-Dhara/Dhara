"""Soft confidence failures skip LLM and keep ruled grids for review."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.confidence_validation.confidence_split import (
    _is_soft_llm_reason,
    split_by_confidence,
)


def test_soft_reason_markers():
    assert _is_soft_llm_reason(
        "placeholder column header (blank in the raw table) -- real header likely lives outside the ruled region"
    )
    assert _is_soft_llm_reason("many empty columns (likely bisected grid / split numeric cells)")
    assert not _is_soft_llm_reason(
        "column-number strip is gappy (phantom column split / misaligned measures)"
    )
    assert not _is_soft_llm_reason("glued multi-value measure cells (column boundaries collapsed)")


def test_placeholder_headers_soft_accept_not_llm():
    """Vital-stats style: blank headers → Col_* used to flood the AI queue."""
    df = pd.DataFrame(
        [
            ["1", "District A", "100", "12"],
            ["2", "District B", "200", "18"],
            ["3", "District C", "150", "15"],
        ],
        columns=["Col_1", "Col_2", "Col_3", "Col_4"],
    )
    pages = {
        10: [{"method": "pymupdf_lines_strict", "df": df, "bbox": [0, 0, 200, 200]}],
    }
    high, llm, reasons = split_by_confidence(pages, page_text={10: "Table 2.1 Live births"})
    assert 10 in high
    assert 10 not in llm
    assert any(str(k).startswith("soft_accept:") for k in reasons)
    tables = high[10]["tables"]
    assert tables
    assert tables[0].get("human_review_needed") is True


def test_hard_gappy_reason_is_not_soft():
    assert not _is_soft_llm_reason(
        "column-number strip is gappy (phantom column split / misaligned measures)"
    )
    assert not _is_soft_llm_reason(
        "glued multi-value measure cells (column boundaries collapsed)"
    )
    assert not _is_soft_llm_reason(
        "structural issue (multiline/duplicate header or header glued into first row)"
    )