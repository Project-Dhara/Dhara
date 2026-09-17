"""Unit tests for catalogue access query helpers (no DB required)."""
from __future__ import annotations

import pytest

from catalogue.query import _shape_dataset_row, _validate_column


def test_shape_dataset_row_basics():
    shaped = _shape_dataset_row({
        "dataset_id": "DS_1",
        "title": "Live births",
        "short_description": "Short",
        "long_description": "Longer text",
        "geography": "Delhi",
        "frequency": "Annual",
        "time_period": "2020",
        "data_source": "DES",
        "classifications": {"Occupation": {"A": "x"}},
        "category": "Vital",
        "metadata_id": "META-1",
        "sector": "Health",
        "theme": "Births",
        "catalogue_product": "SDA",
        "nmds_concepts": [{"concept": "Geography", "details": "NCT"}],
        "last_updated_date": None,
        "row_count": 12,
    })
    assert shaped["id"] == "DS_1"
    assert shaped["row_count"] == 12
    assert shaped["rows"] == "12"
    assert "occupation" in shaped["keywords"] or "Occupation" in shaped["facets"]
    assert shaped["metadata_id"] == "META-1"
    assert shaped["nmds_concepts"][0]["concept"] == "Geography"


def test_validate_column_rejects_injection():
    assert _validate_column("State") == "State"
    assert _validate_column(None) is None
    with pytest.raises(ValueError):
        _validate_column("foo; DROP TABLE datasets")
    with pytest.raises(ValueError):
        _validate_column("a' OR '1'='1")
