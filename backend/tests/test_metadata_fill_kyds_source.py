"""Blank groups must still be LLM-filled after KYDS writes Source."""
import json

from app.services.metadata.metadata_fill import _fill_empty_group_metadata


class _FakeExtractor:
    def __init__(self, skip_llm=False):
        self.skip_llm = skip_llm
        self.calls = 0

    def _complete(self, prompt, max_tokens):
        self.calls += 1
        return json.dumps({
            "title": "Births",
            "product": "Vital statistics",
            "category": "Health",
            "geography": "Delhi",
            "frequency": "Annual",
            "time_period": "2023",
            "data_source": "report.pdf",
            "description": "Registered births.",
            "last_updated": None,
            "future_release": None,
            "key_statistics": "1,200 births",
            "remarks": None,
        })


def _blank_group():
    return {
        "file_name": "Births",
        "metadata": {
            "title": "Births",
            "product": "",
            "category": "",
            "geography": "",
            "frequency": "",
            "time_period": "",
            "data_source": "",
            "description": "",
            "last_updated": "",
            "future_release": "",
            "key_statistics": "",
            "remarks": "",
        },
        "matched_tables": [{
            "table": {
                "title": "Births by age",
                "source_file": "report.pdf",
                "columns": ["Age", "Count"],
                "rows": [["0-1", "10"]],
            },
        }],
    }


def test_blank_group_is_filled_without_kyds():
    """A missing Know Your Dataset entry must not skip Stage 4."""
    groups = [_blank_group()]
    extractor = _FakeExtractor()
    skipped, errors = _fill_empty_group_metadata(groups, {}, None, extractor)
    assert skipped is False
    assert errors == []
    assert extractor.calls == 1
    assert groups[0]["_llm_filled"] is True
    assert groups[0]["metadata"]["product"] == "Vital statistics"
    assert groups[0]["metadata"]["description"] == "Registered births."
    assert groups[0]["metadata"]["key_statistics"] == "1,200 births"
    assert groups[0]["metadata"]["remarks"]
    # Filename-like Source is still cleared when KYDS has no department.
    assert groups[0]["metadata"]["data_source"] == ""


def test_blank_group_is_filled_even_after_kyds_source_injection():
    groups = [_blank_group()]
    extractor = _FakeExtractor()
    skipped, errors = _fill_empty_group_metadata(
        groups,
        {},
        {"department": "Department of Health and Welfare"},
        extractor,
    )
    assert skipped is False
    assert errors == []
    assert extractor.calls == 1
    assert groups[0]["metadata"]["product"] == "Vital statistics"
    assert groups[0]["metadata"]["description"] == "Registered births."
    assert groups[0]["metadata"]["data_source"] == "Department of Health and Welfare"
    assert groups[0]["_llm_filled"] is True


def test_source_only_group_is_still_filled():
    """A previous pass may already have written the KYDS department into Source."""
    group = _blank_group()
    group["metadata"]["data_source"] = "Department of Health and Welfare"
    groups = [group]
    extractor = _FakeExtractor()
    skipped, errors = _fill_empty_group_metadata(
        groups,
        {},
        {"department": "Department of Health and Welfare"},
        extractor,
    )
    assert skipped is False
    assert errors == []
    assert extractor.calls == 1
    assert groups[0]["metadata"]["product"] == "Vital statistics"
    assert groups[0]["metadata"]["data_source"] == "Department of Health and Welfare"


def test_workbook_metadata_is_not_overwritten():
    """Existing workbook values stay; blank priority fields still get an LLM pass."""
    group = _blank_group()
    group["metadata"]["product"] = "From workbook"
    group["metadata"]["description"] = "Already mapped"
    groups = [group]
    extractor = _FakeExtractor()
    skipped, errors = _fill_empty_group_metadata(
        groups,
        {},
        {"department": "Department of Health and Welfare"},
        extractor,
    )
    assert skipped is False
    assert errors == []
    assert extractor.calls == 1
    assert groups[0]["metadata"]["product"] == "From workbook"
    assert groups[0]["metadata"]["description"] == "Already mapped"
    assert groups[0]["metadata"]["category"] == "Health"
    assert groups[0]["metadata"]["remarks"]


def test_complete_workbook_group_skips_llm():
    """When every priority field is already set, Stage 4 does not call the LLM."""
    group = _blank_group()
    group["metadata"].update({
        "product": "From workbook",
        "category": "Health",
        "geography": "Delhi",
        "frequency": "Annual",
        "time_period": "2023",
        "description": "Already mapped",
        "key_statistics": "n = 10",
        "remarks": "Workbook note",
    })
    groups = [group]
    extractor = _FakeExtractor()
    skipped, errors = _fill_empty_group_metadata(
        groups,
        {},
        {"department": "Department of Health and Welfare"},
        extractor,
    )
    assert skipped is False
    assert errors == []
    assert extractor.calls == 0
    assert groups[0]["metadata"]["product"] == "From workbook"
    assert groups[0]["metadata"]["description"] == "Already mapped"


def test_llm_nulls_get_catalogue_fallbacks():
    """Product / description / key_statistics / remarks are filled even if the model returns null."""

    class _SparseExtractor(_FakeExtractor):
        def _complete(self, prompt, max_tokens):
            self.calls += 1
            return json.dumps({
                "title": "Births",
                "product": None,
                "category": "Health",
                "geography": None,
                "frequency": None,
                "time_period": None,
                "data_source": None,
                "description": None,
                "last_updated": None,
                "future_release": None,
                "key_statistics": None,
                "remarks": None,
            })

    groups = [_blank_group()]
    extractor = _SparseExtractor()
    skipped, errors = _fill_empty_group_metadata(
        groups,
        {},
        {
            "datasetName": "Vital statistics register",
            "description": "Birth registrations for the year.",
            "notes": "Provisional figures.",
            "department": "Department of Health and Welfare",
        },
        extractor,
    )
    assert skipped is False
    assert errors == []
    assert extractor.calls == 1
    meta = groups[0]["metadata"]
    assert meta["product"] == "Vital statistics register"
    assert meta["description"] == "Birth registrations for the year."
    assert meta["remarks"] == "Provisional figures."
    assert meta["data_source"] == "Department of Health and Welfare"


def test_multiple_blank_groups_are_filled_in_parallel():
    """Several empty groups each get an LLM call; outcomes match sequential fill."""
    groups = [_blank_group(), _blank_group()]
    groups[1]["file_name"] = "Deaths"
    groups[1]["metadata"]["title"] = "Deaths"
    groups[1]["matched_tables"][0]["table"]["title"] = "Deaths by age"
    extractor = _FakeExtractor()
    skipped, errors = _fill_empty_group_metadata(
        groups,
        {},
        {"department": "Department of Health and Welfare"},
        extractor,
    )
    assert skipped is False
    assert errors == []
    assert extractor.calls == 2
    assert groups[0]["metadata"]["product"] == "Vital statistics"
    assert groups[1]["metadata"]["product"] == "Vital statistics"
    assert groups[0]["_llm_filled"] is True
    assert groups[1]["_llm_filled"] is True
    assert groups[0]["metadata"]["data_source"] == "Department of Health and Welfare"
    assert groups[1]["metadata"]["data_source"] == "Department of Health and Welfare"
