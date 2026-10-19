"""Unit tests for catalogue group shaping and table code/definition append."""
from __future__ import annotations

from app.db.repositories.catalogue import _shape_group_row
from app.services.catalogue.group_export import append_code_definition_columns
from app.services.catalogue.summary import (
    catalogue_display_summary,
    is_usable_catalogue_description,
    synthesize_catalogue_summary,
)


def test_shape_group_row_includes_tables():
    shaped = _shape_group_row(
        {
            "metadata_id": "META-1",
            "title": "Vital statistics release",
            "description": "Group narrative covering births in Delhi.",
            "product": "SDA",
            "category": "Vital",
            "geography": "Delhi",
            "frequency": "Annual",
            "time_period": "2020",
            "data_source": "DES",
            "classifications": {
                "Occupation": [{"value": "Teacher", "code": "23", "definition": "Teaching"}],
            },
            "sector": "Health",
            "theme": "Births",
            "catalogue_product": "SDA",
            "nmds_concepts": [{"concept": "Geography", "details": "NCT"}],
            "last_updated_date": None,
        },
        tables=[
            {"id": "DS_1", "dataset_id": "DS_1", "title": "Live births", "table_id": "DS_1", "row_count": 12},
            {"id": "DS_2", "dataset_id": "DS_2", "title": "Still births", "table_id": "DS_2", "row_count": 3},
        ],
    )
    assert shaped["kind"] == "group"
    assert shaped["id"] == "META-1"
    assert shaped["metadata_id"] == "META-1"
    assert shaped["table_count"] == 2
    assert shaped["row_count"] == 15
    assert shaped["rows"] == "15"
    assert len(shaped["tables"]) == 2
    assert "ds_1" in shaped["keywords"]
    assert "Occupation" in shaped["classifications"]
    assert shaped["nmds_concepts"][0]["concept"] == "Geography"
    assert shaped["summary"] == "Group narrative covering births in Delhi."


def test_catalogue_summary_rejects_gibberish_and_synthesizes():
    assert not is_usable_catalogue_description(
        "Age: 0-1; Count: 10; Age: 1-2; Count: 12; Age: 2-3; Count: 8; "
        "Age: 3-4; Count: 9; Age: 4-5; Count: 11"
    )
    assert not is_usable_catalogue_description('{"title": "x", "rows": [1,2,3]}')
    blurb = synthesize_catalogue_summary(
        title="Vital statistics",
        category="Health",
        geography="Delhi",
        frequency="Annual",
        time_period="2023",
        table_titles=["Live births", "Still births"],
    )
    assert "Vital statistics" in blurb
    assert "Delhi" in blurb
    assert "Live births" in blurb
    assert len(blurb) < 400

    display = catalogue_display_summary(
        {
            "title": "Vital statistics",
            "description": "ColA: 1 | ColB: 2 | ColC: 3 | ColD: 4",
            "category": "Health",
            "geography": "Delhi",
            "frequency": "Annual",
            "time_period": "2023",
        },
        tables=[{"title": "Live births"}, {"title": "Still births"}],
    )
    assert "Delhi" in display
    assert "|" not in display


def test_append_code_definition_after_classified_column():
    columns = ["State", "Occupation", "Count"]
    rows = [
        {"State": "Delhi", "Occupation": "Teacher", "Count": 10},
        {"State": "Delhi", "Occupation": "Nurse", "Count": 4},
        {"State": "Delhi", "Occupation": "Unknown", "Count": 1},
    ]
    classifications = {
        "Occupation": [
            {"value": "Teacher", "code": "23", "definition": "Teaching professionals"},
            {"value": "nurse", "code": "22", "definition": "Nursing professionals"},
        ],
        "Sex": [  # not present in this table — ignored
            {"value": "Male", "code": "M", "definition": "Male"},
        ],
    }
    new_cols, new_rows = append_code_definition_columns(columns, rows, classifications)
    assert new_cols == [
        "State",
        "Occupation", "Code", "Definition",
        "Count",
    ]
    assert new_rows[0]["Code"] == "23"
    assert new_rows[0]["Definition"] == "Teaching professionals"
    assert new_rows[1]["Code"] == "22"  # case-insensitive match
    assert new_rows[2]["Code"] == ""
    assert new_rows[2]["Definition"] == ""
    # Original columns untouched
    assert new_rows[0]["Occupation"] == "Teacher"
    assert new_rows[0]["Count"] == 10


def test_append_is_idempotent_when_already_present():
    columns = ["Sex", "Code", "Definition"]
    rows = [{"Sex": "Male", "Code": "M", "Definition": "Male"}]
    classifications = {
        "Sex": [{"value": "Male", "code": "1", "definition": "M"}],
    }
    new_cols, new_rows = append_code_definition_columns(columns, rows, classifications)
    assert new_cols == columns
    assert new_rows[0]["Code"] == "M"


def test_append_second_classified_column_disambiguates():
    columns = ["Occupation", "Sex"]
    rows = [
        {"Occupation": "Teacher", "Sex": "Male"},
    ]
    classifications = {
        "Occupation": [{"value": "Teacher", "code": "23", "definition": "Teaching"}],
        "Sex": [{"value": "Male", "code": "1", "definition": "Male"}],
    }
    new_cols, new_rows = append_code_definition_columns(columns, rows, classifications)
    assert new_cols == [
        "Occupation", "Code", "Definition",
        "Sex", "Sex Code", "Sex Definition",
    ]
    assert new_rows[0]["Code"] == "23"
    assert new_rows[0]["Definition"] == "Teaching"
    assert new_rows[0]["Sex Code"] == "1"
    assert new_rows[0]["Sex Definition"] == "Male"
