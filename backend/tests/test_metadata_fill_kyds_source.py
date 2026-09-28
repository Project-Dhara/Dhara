"""Blank groups must still be LLM-filled after KYDS writes Source."""
import json

from metadata.metadata_fill import _fill_empty_group_metadata


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
    assert extractor.calls == 0
    assert groups[0]["metadata"]["product"] == "From workbook"
    assert groups[0]["metadata"]["description"] == "Already mapped"
