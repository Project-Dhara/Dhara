"""Tests for key_statistics formatting after LLM metadata autofill."""
from __future__ import annotations

from metadata.metadata_fill import _format_key_statistics, _stringify_metadata_values


def test_format_key_statistics_list_of_rows():
    raw = [
        {
            "Group": "1",
            "Sub-Group": "FOOD & BEVERAGES",
            "Weight": "100",
            "Jan": "111.9",
            "Feb": "112.5",
            "Dec": "123.2",
        },
        {
            "Group": "a",
            "Sub-Group": "Cereals & Products",
            "Weight": "13.41",
            "Jan": "116",
            "Dec": "124.7",
        },
    ]
    text = _format_key_statistics(raw)
    assert text is not None
    assert not text.strip().startswith("[")
    assert "FOOD & BEVERAGES" in text
    assert "Cereals & Products" in text
    assert "weight 100" in text
    assert "Jan 111.9" in text
    assert "Dec 123.2" in text
    assert "•" in text


def test_format_key_statistics_json_string():
    raw = '[{"Sub-Group": "Pulses & Products", "Weight": "6.89", "Jan": "88.8", "Dec": "101.8"}]'
    text = _format_key_statistics(raw)
    assert text is not None
    assert "Pulses & Products" in text
    assert "[" not in text


def test_stringify_metadata_formats_key_statistics():
    meta = _stringify_metadata_values({
        "title": "CPI",
        "key_statistics": [
            {"Sub-Group": "Milk and Milk Products", "Weight": "20.13", "Jan": "116.2", "Dec": "120.4"},
        ],
    })
    assert meta["title"] == "CPI"
    assert meta["key_statistics"].startswith("•")
    assert "Milk and Milk Products" in meta["key_statistics"]
    assert "[" not in meta["key_statistics"]
