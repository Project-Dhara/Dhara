"""AI-classified tables should prefer descriptive captions over TABLE ids."""
from __future__ import annotations

import pandas as pd

from pdf.sda_india_pdf_extraction import (
    _llm_title_is_id_only,
    _prefer_descriptive_llm_title,
)


def test_id_only_detection():
    assert _llm_title_is_id_only("TABLE: B-22")
    assert _llm_title_is_id_only("Table B-22")
    assert _llm_title_is_id_only("")
    assert _llm_title_is_id_only(None)
    assert not _llm_title_is_id_only(
        "LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT (URBAN)"
    )


def test_prefer_candidate_in_grid_caption():
    df = pd.DataFrame([["1", "2"]])
    df.attrs["dhara_table_caption"] = (
        "LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT (URBAN)"
    )
    df.attrs["dhara_banner_table_id"] = "TABLE: B-22"
    table = {
        "title": "TABLE: B-22",
        "rows": [["1", "2"]],
        "columns": [{"name": "a"}, {"name": "b"}],
        "notes": [],
    }
    out = _prefer_descriptive_llm_title(
        table, [{"df": df, "method": "pymupdf_lines_strict", "bbox": [0, 0, 1, 1]}]
    )
    assert out["title"] == "LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT (URBAN)"
    assert out["banner_table_id"] == "TABLE: B-22"
    assert "table_id: TABLE: B-22" in out["notes"]
    assert out["title_source"] == "llm_in_grid_caption_from_candidate"


def test_prefer_title_from_llm_rows_when_banners_present():
    rows = [
        ["TABLE: B-22", "", "", ""],
        ["LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT (URBAN)", "", "", ""],
        ["1", "2", "3", "4"],
    ]
    table = {"title": "Table B-22", "rows": rows, "notes": []}
    out = _prefer_descriptive_llm_title(table, candidates=None)
    assert out["title"] == "LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT (URBAN)"
    assert out["title_source"] == "llm_in_grid_caption_from_rows"


def test_keeps_already_descriptive_llm_title():
    table = {
        "title": "LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT (URBAN)",
        "rows": [["1", "2"]],
        "notes": [],
    }
    out = _prefer_descriptive_llm_title(table, candidates=None)
    assert out["title"] == "LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT (URBAN)"
    assert out.get("title_source") is None
