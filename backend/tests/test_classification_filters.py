"""Skip TOC/index tables and serial/contents junk classification columns."""
from __future__ import annotations

from app.services.classification.classifications import (
    _classifications_from_table_data,
    _collapse_near_duplicate_dimensions,
    _filter_classification_dict,
    _looks_like_index_or_toc_table,
    _looks_like_non_classification_column_name,
)


def test_detects_contents_index_table():
    toc = {
        "title": "Contents",
        "columns": ["Sl.No.", "Contents", "Page"],
        "rows": [
            {"Sl.No.": "1", "Contents": "Introduction", "Page": "1"},
            {"Sl.No.": "2", "Contents": "Vital Statistics", "Page": "15"},
        ],
    }
    assert _looks_like_index_or_toc_table(toc)
    assert _classifications_from_table_data([toc]) == {}


def test_detects_list_of_tables_by_title():
    table = {
        "title": "List of Tables",
        "columns": ["S.No", "Title", "Page No"],
        "rows": [
            {"S.No": "1", "Title": "Table A", "Page No": "3"},
            {"S.No": "2", "Title": "Table B", "Page No": "9"},
        ],
    }
    assert _looks_like_index_or_toc_table(table)


def test_real_stats_table_not_treated_as_toc():
    table = {
        "title": "Live births by sex and district",
        "columns": ["Sl.No.", "District", "Male", "Female", "Total"],
        "rows": [
            {"Sl.No.": "1", "District": "North", "Male": 10, "Female": 12, "Total": 22},
            {"Sl.No.": "2", "District": "South", "Male": 8, "Female": 9, "Total": 17},
            {"Sl.No.": "3", "District": "East", "Male": 11, "Female": 10, "Total": 21},
        ],
    }
    assert not _looks_like_index_or_toc_table(table)
    dims = _classifications_from_table_data([table])
    assert "District" in dims or "district" in {k.lower() for k in dims}
    assert not any(_looks_like_non_classification_column_name(k) for k in dims)


def test_serial_and_contents_column_names_excluded():
    assert _looks_like_non_classification_column_name("Sl.No.")
    assert _looks_like_non_classification_column_name("SL_NO")
    assert _looks_like_non_classification_column_name("Contents")
    assert _looks_like_non_classification_column_name("Page No.")
    assert not _looks_like_non_classification_column_name("District")
    assert not _looks_like_non_classification_column_name("Sex")


def test_placeholder_and_numeric_column_names_excluded():
    """Col_1 / bare numbers are extraction stubs, not classification dims."""
    assert _looks_like_non_classification_column_name("Col_1")
    assert _looks_like_non_classification_column_name("Col_12")
    assert _looks_like_non_classification_column_name("column_3")
    assert _looks_like_non_classification_column_name("Unnamed: 0")
    assert _looks_like_non_classification_column_name("15")
    assert _looks_like_non_classification_column_name("2023")
    assert _looks_like_non_classification_column_name("2023-24")
    assert _looks_like_non_classification_column_name("(1)")
    assert not _looks_like_non_classification_column_name("Age_15")
    assert not _looks_like_non_classification_column_name("District")


def test_placeholder_columns_not_rebuilt_as_classifications():
    table = {
        "title": "Broken header extract",
        "columns": ["Col_1", "15", "District"],
        "rows": [
            {"Col_1": "A", "15": "X", "District": "North"},
            {"Col_1": "B", "15": "Y", "District": "South"},
            {"Col_1": "C", "15": "Z", "District": "East"},
        ],
    }
    dims = _classifications_from_table_data([table])
    assert "District" in dims
    assert "Col_1" not in dims
    assert "15" not in dims


def test_filter_drops_stored_junk_keeps_real_dims():
    filtered = _filter_classification_dict({
        "Contents": [
            {"code": "", "value": "Introduction", "definition": None},
            {"code": "", "value": "Annexure", "definition": None},
        ],
        "Sl_No": [
            {"code": "", "value": "a", "definition": None},
            {"code": "", "value": "b", "definition": None},
        ],
        "Col_1": [
            {"code": "", "value": "foo", "definition": None},
            {"code": "", "value": "bar", "definition": None},
        ],
        "15": [
            {"code": "", "value": "x", "definition": None},
            {"code": "", "value": "y", "definition": None},
        ],
        "Sex": [
            {"code": "M", "value": "Male", "definition": None},
            {"code": "F", "value": "Female", "definition": None},
        ],
    })
    assert "Sex" in filtered
    assert "Contents" not in filtered
    assert "Sl_No" not in filtered
    assert "Col_1" not in filtered
    assert "15" not in filtered


def test_collapse_near_duplicate_dimensions():
    merged = _collapse_near_duplicate_dimensions({
        "State": [
            {"code": "", "value": "Delhi", "definition": None},
            {"code": "", "value": "Haryana", "definition": None},
            {"code": "", "value": "Punjab", "definition": None},
        ],
        "Name_of_State": [
            {"code": "", "value": "Delhi", "definition": None},
            {"code": "", "value": "Haryana", "definition": None},
            {"code": "", "value": "Punjab", "definition": None},
            {"code": "", "value": "UP", "definition": None},
        ],
        "Sex": [
            {"code": "", "value": "Male", "definition": None},
            {"code": "", "value": "Female", "definition": None},
        ],
    })
    assert "Sex" in merged
    # Near-identical state lists collapse to one canonical short name.
    state_keys = [k for k in merged if "state" in k.lower()]
    assert len(state_keys) == 1
    assert len(merged[state_keys[0]]) == 4


def test_free_text_contents_column_skipped_even_without_toc_shape():
    """Chapter-title text columns must not become Classify chips."""
    table = {
        "title": "Chapter overview",
        "columns": ["Section", "Summary"],
        "rows": [
            {
                "Section": "A very long chapter title about births in urban areas",
                "Summary": "Another long free-text summary line for chapter one",
            },
            {
                "Section": "A very long chapter title about deaths in rural areas",
                "Summary": "Another long free-text summary line for chapter two",
            },
            {
                "Section": "A very long chapter title about infant mortality trends",
                "Summary": "Another long free-text summary line for chapter three",
            },
            {
                "Section": "A very long chapter title about maternal health indicators",
                "Summary": "Another long free-text summary line for chapter four",
            },
            {
                "Section": "A very long chapter title about registration completeness",
                "Summary": "Another long free-text summary line for chapter five",
            },
            {
                "Section": "A very long chapter title about cause of death patterns",
                "Summary": "Another long free-text summary line for chapter six",
            },
            {
                "Section": "A very long chapter title about fertility differentials",
                "Summary": "Another long free-text summary line for chapter seven",
            },
            {
                "Section": "A very long chapter title about migration statistics",
                "Summary": "Another long free-text summary line for chapter eight",
            },
        ],
    }
    assert _classifications_from_table_data([table]) == {}
