"""Repeated leaf labels under distinct groups must not become Total (2)/(3)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.confidence_validation.table_confidence import (
    dedupe_column_names,
    table_dict_from_df,
)
from app.services.extraction.pdf.utils.dataframe_build import dataframe_from_extracted_rows


def test_dedupe_keeps_shared_leaf_when_paths_differ():
    cols = [
        {
            "name": "Total",
            "header_group": "Oil Seeds",
            "header_path": ["Non Food Crops", "Oil Seeds", "Total"],
        },
        {
            "name": "Total",
            "header_group": "Fibre Drugs and Narcotics",
            "header_path": ["Non Food Crops", "Fibre Drugs and Narcotics", "Total"],
        },
        {
            "name": "Total",
            "header_group": "Plantation Crops",
            "header_path": ["Non Food Crops", "Plantation Crops", "Total"],
        },
    ]
    out = dedupe_column_names([dict(c) for c in cols])
    assert [c["name"] for c in out] == ["Total", "Total", "Total"]
    assert not any(c.get("human_review_reason") == "ambiguous_column" for c in out)


def test_dedupe_still_suffixes_true_flat_duplicates():
    cols = [
        {"name": "Year", "header_path": ["Year"]},
        {"name": "Year", "header_path": ["Year"]},
    ]
    out = dedupe_column_names([dict(c) for c in cols])
    assert out[0]["name"] == "Year"
    assert out[1]["name"] == "Year (2)"
    assert out[1].get("human_review_reason") == "ambiguous_column"


def test_table_dict_uses_path_leaf_not_df_uniquify_suffix():
    df = pd.DataFrame(
        [["1", "10", "20", "30"]],
        columns=["District", "Total", "Total (2)", "Total (3)"],
    )
    df.attrs["dhara_column_meta"] = [
        {"name": "District", "header_group": None, "header_path": ["District"]},
        {
            "name": "Total (2)",  # stale uniquify in meta name
            "header_group": "Oil Seeds",
            "header_path": ["Non Food Crops", "Oil Seeds", "Total"],
        },
        {
            "name": "Total (3)",
            "header_group": "Fibre Drugs and Narcotics",
            "header_path": ["Non Food Crops", "Fibre Drugs and Narcotics", "Total"],
        },
        {
            "name": "Total (4)",
            "header_group": "Plantation Crops",
            "header_path": ["Non Food Crops", "Plantation Crops", "Total"],
        },
    ]
    table = table_dict_from_df(df, page_num=1, method="pymupdf_lines_strict")
    names = [c["name"] for c in table["columns"]]
    assert names == ["District", "Total", "Total", "Total"]


def test_dataframe_build_meta_name_is_real_leaf():
    rows = [
        ["Sl. No.", "District", "Non Food Crops", "", "", "", ""],
        ["", "", "Oil Seeds", "", "Fibre", "", "Plantation"],
        ["", "", "A", "Total", "B", "Total", "Total"],
        ["1", "X", "1", "2", "3", "4", "5"],
    ]
    df = dataframe_from_extracted_rows(rows)
    meta = list(getattr(df, "attrs", {}).get("dhara_column_meta") or [])
    totals = [m for m in meta if str((m.get("header_path") or [None])[-1]) == "Total"]
    assert len(totals) >= 2
    assert all(m.get("name") == "Total" for m in totals)
    # DataFrame columns may still be uniquified for pandas.
    assert list(df.columns).count("Total") + sum(
        1 for c in df.columns if str(c).startswith("Total (")
    ) >= 2
