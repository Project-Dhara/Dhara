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


def test_job_column_is_an_occupation_column():
    from app.services.classification.classifications import _is_occupation_name

    assert _is_occupation_name("Job")
    assert _is_occupation_name("Jobs")
    assert _is_occupation_name("Job Title")
    assert _is_occupation_name("Occupation")
    assert not _is_occupation_name("Job ID")
    assert not _is_occupation_name("Sector")


def test_keeps_code_list_with_more_than_80_values():
    """A long category list is still a classification dimension."""
    labels = [f"Occupation {i}" for i in range(120)]
    table = {
        "title": "Workers by occupation",
        "columns": ["Occupation"],
        "rows": [{"Occupation": label} for label in labels],
    }
    dims = _classifications_from_table_data([table])
    assert "Occupation" in dims
    assert len(dims["Occupation"]) == 120


def test_identifier_column_names_excluded():
    assert _looks_like_non_classification_column_name("recordid")
    assert _looks_like_non_classification_column_name("Record_ID")
    assert _looks_like_non_classification_column_name("Record ID")
    assert _looks_like_non_classification_column_name("UUID")
    assert _looks_like_non_classification_column_name("guid")
    assert _looks_like_non_classification_column_name("id")
    assert _looks_like_non_classification_column_name("rowid")
    assert not _looks_like_non_classification_column_name("Organisation")
    assert not _looks_like_non_classification_column_name("State")


def test_recordid_not_rebuilt_as_classification():
    """Employee-style near-unique short IDs are not categorical dimensions."""
    rows = [
        {
            "recordid": f"REC{i:03d}",
            "Organisation": "Org A" if i % 2 == 0 else "Org B",
            "State": "Delhi" if i % 3 == 0 else "Haryana" if i % 3 == 1 else "Punjab",
        }
        for i in range(30)
    ]
    table = {
        "title": "Employee Details by Organisation and State",
        "columns": ["recordid", "Organisation", "State"],
        "rows": rows,
    }
    dims = _classifications_from_table_data([table])
    keys = {k.lower() for k in dims}
    assert "recordid" not in keys
    assert "organisation" in keys
    assert "state" in keys


def test_filter_drops_stored_recordid_and_id_tokens():
    filtered = _filter_classification_dict({
        "recordid": [
            {"code": "", "value": f"REC{i:03d}", "definition": None}
            for i in range(10)
        ],
        "MysteryId": [
            {"code": "", "value": f"X{i:04d}", "definition": None}
            for i in range(12)
        ],
        "State": [
            {"code": "", "value": "Delhi", "definition": None},
            {"code": "", "value": "Haryana", "definition": None},
        ],
    })
    assert "State" in filtered
    assert "recordid" not in filtered
    assert "MysteryId" not in filtered


def test_value_based_drops_renamed_id_column():
    """Near-unique code tokens are dropped even when the name is not deny-listed."""
    rows = [
        {
            "emp_key": f"REC{i:03d}",
            "Organisation": f"Org {i % 5}",
            "State": "Delhi" if i % 2 == 0 else "Haryana",
        }
        for i in range(40)
    ]
    table = {
        "title": "Employee Details",
        "columns": ["emp_key", "Organisation", "State"],
        "rows": rows,
    }
    dims = _classifications_from_table_data([table])
    keys = {k.lower() for k in dims}
    assert "emp_key" not in keys
    assert "organisation" in keys
    assert "state" in keys


def test_keeps_large_near_unique_occupation_list():
    """Employee microdata often has hundreds of distinct occupation titles."""
    titles = [f"Manager (Unit {i})" for i in range(831)]
    # Mostly unique titles across rows (near-unique), still a classification dim.
    rows = [{"Occupation": titles[i % 831], "State": "Delhi" if i % 2 == 0 else "Goa"} for i in range(900)]
    dims = _classifications_from_table_data([{
        "title": "Employee Details",
        "columns": ["Occupation", "State"],
        "rows": rows,
    }])
    assert "Occupation" in dims
    assert len(dims["Occupation"]) == 831
    assert "State" in dims


def test_keeps_many_organisations_and_state_codebook():
    """High-cardinality real categories must not be dropped by distinct-band rules."""
    orgs = [f"Organisation {i}" for i in range(40)]
    states = [
        "Andhra Pradesh", "Bihar", "Delhi", "Goa", "Gujarat", "Haryana",
        "Karnataka", "Kerala", "Maharashtra", "Odisha", "Punjab", "Rajasthan",
        "Tamil Nadu", "Telangana", "Uttar Pradesh", "West Bengal",
        "Assam", "Jharkhand", "Chhattisgarh", "Uttarakhand",
    ]
    rows = []
    for i in range(100):
        rows.append({
            "Organisation": orgs[i % len(orgs)],
            "State": states[i % len(states)],
        })
    # Codebook-shaped extract: one row per state label (single-word + multi-word).
    state_book = {
        "title": "State list",
        "columns": ["State"],
        "rows": [{"State": s} for s in states],
    }
    employee = {
        "title": "Employees",
        "columns": ["Organisation", "State"],
        "rows": rows,
    }
    dims = _classifications_from_table_data([employee, state_book])
    keys = {k.lower() for k in dims}
    assert "organisation" in keys
    assert "state" in keys
    assert len(dims[[k for k in dims if k.lower() == "organisation"][0]]) == 40
