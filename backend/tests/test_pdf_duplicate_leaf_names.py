"""Repeated leaf labels must stay stable — no ``(2)`` / ambiguous_column noise."""

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


def test_dedupe_keeps_flat_duplicates_without_review_flag():
    """Two Year columns stay Year/Year — no Year (2) ambiguous_column chip."""
    cols = [
        {"name": "Year", "header_path": ["Year"]},
        {"name": "Year", "header_path": ["Year"]},
    ]
    out = dedupe_column_names([dict(c) for c in cols])
    assert [c["name"] for c in out] == ["Year", "Year"]
    assert not any(c.get("human_review_needed") for c in out)
    assert not any(c.get("human_review_reason") == "ambiguous_column" for c in out)


def test_dedupe_promotes_distinct_groups_into_header_path():
    cols = [
        {"name": "Total", "header_group": "Oil Seeds", "header_path": ["Total"]},
        {"name": "Total", "header_group": "Fibre", "header_path": ["Total"]},
    ]
    out = dedupe_column_names([dict(c) for c in cols])
    assert [c["name"] for c in out] == ["Total", "Total"]
    assert out[0]["header_path"] == ["Oil Seeds", "Total"]
    assert out[1]["header_path"] == ["Fibre", "Total"]
    assert not any(c.get("human_review_reason") == "ambiguous_column" for c in out)


def test_dedupe_keeps_frequency_stack_repeats_unflagged():
    leaf_cycle = ["Sl.No.", "Range", "Freq.", "% of Freq."]
    cols = []
    for _ in range(3):
        for leaf in leaf_cycle:
            cols.append({"name": leaf, "header_path": [leaf], "header_group": None})
    out = dedupe_column_names([dict(c) for c in cols])
    assert [c["name"] for c in out] == leaf_cycle * 3
    assert not any(c.get("human_review_needed") for c in out)


def test_dedupe_repairs_prior_occurrence_suffix_flags():
    """Older Sl.No. (2) / Percentage (2) + ambiguous_column are cleaned up."""
    cols = [
        {"name": "Sl.No.", "header_path": ["Sl.No."]},
        {"name": "Range", "header_path": ["Range"]},
        {"name": "Freq.", "header_path": ["Freq."]},
        {"name": "% of Freq.", "header_path": ["% of Freq."]},
        {
            "name": "Sl.No. (2)",
            "header_path": ["Sl.No."],
            "human_review_needed": True,
            "human_review_reason": "ambiguous_column",
            "input_type": "inputbox",
        },
        {"name": "Range (2)", "header_path": ["Range"], "human_review_needed": True,
         "human_review_reason": "ambiguous_column", "input_type": "inputbox"},
        {"name": "Freq. (2)", "header_path": ["Freq."], "human_review_needed": True,
         "human_review_reason": "ambiguous_column", "input_type": "inputbox"},
        {"name": "% of Freq. (2)", "header_path": ["% of Freq."], "human_review_needed": True,
         "human_review_reason": "ambiguous_column", "input_type": "inputbox"},
    ]
    out = dedupe_column_names([dict(c) for c in cols])
    assert [c["name"] for c in out] == [
        "Sl.No.", "Range", "Freq.", "% of Freq.",
        "Sl.No.", "Range", "Freq.", "% of Freq.",
    ]
    assert not any(c.get("human_review_needed") for c in out)


def test_dedupe_keeps_paired_percentage_columns_unflagged():
    cols = [
        {"name": "Age Group years", "header_path": ["Age Group years"]},
        {"name": "Male", "header_path": ["Male"]},
        {"name": "Percentage", "header_path": ["Percentage"]},
        {"name": "Female", "header_path": ["Female"]},
        {"name": "Percentage", "header_path": ["Percentage"]},
        {"name": "Total", "header_path": ["Total"]},
        {"name": "Percentage", "header_path": ["Percentage"]},
    ]
    out = dedupe_column_names([dict(c) for c in cols])
    assert [c["name"] for c in out] == [
        "Age Group years", "Male", "Percentage", "Female", "Percentage", "Total", "Percentage",
    ]
    assert not any(c.get("human_review_needed") for c in out)


def test_dedupe_repairs_prior_paired_percentage_suffix_flags():
    cols = [
        {"name": "Age Group years", "header_path": ["Age Group years"]},
        {"name": "Male", "header_path": ["Male"]},
        {"name": "Percentage", "header_path": ["Percentage"]},
        {"name": "Female", "header_path": ["Female"]},
        {
            "name": "Percentage (2)",
            "header_path": ["Percentage"],
            "human_review_needed": True,
            "human_review_reason": "ambiguous_column",
            "input_type": "inputbox",
        },
        {"name": "Total", "header_path": ["Total"]},
        {
            "name": "Percentage (3)",
            "header_path": ["Percentage"],
            "human_review_needed": True,
            "human_review_reason": "ambiguous_column",
            "input_type": "inputbox",
        },
    ]
    out = dedupe_column_names([dict(c) for c in cols])
    assert [c["name"] for c in out] == [
        "Age Group years", "Male", "Percentage", "Female", "Percentage", "Total", "Percentage",
    ]
    assert not any(c.get("human_review_needed") for c in out)


def test_dedupe_repairs_group_qualified_percentage_name():
    """Percentage (Number of Deaths) → Percentage under Number of Deaths path."""
    cols = [
        {
            "name": "Male",
            "header_group": "Number of Deaths",
            "header_path": ["Number of Deaths", "Male"],
        },
        {
            "name": "Percentage",
            "header_group": "Number of Deaths",
            "header_path": ["Number of Deaths", "Percentage"],
        },
        {
            "name": "Female",
            "header_group": "Number of Deaths",
            "header_path": ["Number of Deaths", "Female"],
        },
        {
            "name": "Percentage (Number of Deaths)",
            "header_group": "Number of Deaths",
            "header_path": ["Number of Deaths", "Percentage"],
            "human_review_needed": True,
            "human_review_reason": "ambiguous_column",
            "input_type": "inputbox",
        },
    ]
    out = dedupe_column_names([dict(c) for c in cols])
    assert [c["name"] for c in out] == ["Male", "Percentage", "Female", "Percentage"]
    assert out[3]["header_path"] == ["Number of Deaths", "Percentage"]
    assert not any(c.get("human_review_needed") for c in out)


def test_table_dict_uses_path_leaf_not_df_uniquify_suffix():
    df = pd.DataFrame(
        [["1", "10", "20", "30"]],
        columns=["District", "Total", "Total (2)", "Total (3)"],
    )
    df.attrs["dhara_column_meta"] = [
        {"name": "District", "header_group": None, "header_path": ["District"]},
        {
            "name": "Total (2)",
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
    assert list(df.columns).count("Total") + sum(
        1 for c in df.columns if str(c).startswith("Total (")
    ) >= 2
