"""LLM validation failures must not drop already-extracted ruled tables."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.confidence_validation.confidence_split import _llm_pages_missing_tables
from app.services.extraction.pdf.utils.header_utils import (
    _fill_blank_leading_serial_header,
    dataframe_from_extracted_rows,
)
from app.services.extraction.pdf.confidence_validation.table_confidence import _structural_bucket_for_df


def test_llm_pages_missing_when_validation_omits_page():
    llm_pages = {30: [{"method": "pymupdf_lines_strict"}], 31: [{"method": "pymupdf_lines_strict"}]}
    llm_results = {30: {"tables": [{"title": "ok"}]}}  # 31 missing after 401
    missing = _llm_pages_missing_tables(llm_pages, llm_results)
    assert list(missing.keys()) == [31]


def test_llm_pages_missing_when_tables_empty():
    llm_pages = {45: [{"method": "pymupdf_lines_strict"}]}
    llm_results = {45: {"tables": []}}
    missing = _llm_pages_missing_tables(llm_pages, llm_results)
    assert 45 in missing


def test_fill_blank_serial_header_for_cause_of_death():
    names = ["Col_1", "Name of the Disease", "Sex", "<1", "Total"]
    meta = [{"name": n, "header_group": None, "header_path": [n]} for n in names]
    out_names, out_meta = _fill_blank_leading_serial_header(names, meta)
    assert out_names[0] == "S.No."
    assert out_meta[0]["name"] == "S.No."
    # Non-placeholder first col unchanged
    names2, _ = _fill_blank_leading_serial_header(
        ["Year", "Male", "Female"], [{"name": "Year"}, {"name": "Male"}, {"name": "Female"}]
    )
    assert names2[0] == "Year"


def test_cause_of_death_blank_sno_renamed_not_placeholder():
    """Blank S.No. header + Name of Disease becomes S.No., not Col_1."""
    rows = [
        ["", "Name of the Disease", "Sex", "<1", "Total"],
        ["1", "Cholera (A00)", "M", "10", "20"],
        ["", "", "F", "5", "8"],
    ]
    df = dataframe_from_extracted_rows(rows)
    assert list(df.columns)[0] == "S.No."
    # Placeholder Col_* reason must not fire once S.No. is filled.
    _bucket, reason, _info = _structural_bucket_for_df(df)
    assert "placeholder column header" not in reason
