"""NMDS geography autofill keeps places, not header dumps and reorderings."""
from app.services.metadata.metadata_fill import (
    _stringify_metadata_values,
    normalize_catalogue_geography,
)


def test_geography_drops_case_dupes_header_and_reordered_lists():
    raw = (
        "URBAN, Urban, Rural, Region, "
        "Urban, Delhi Cantt, MCD, NDMC, "
        "Delhi Cantt, MCD, NDMC, Urban, "
        "MCD, NDMC, Delhi Cantt, Urban"
    )
    assert normalize_catalogue_geography(raw) == (
        "Urban, Rural, Delhi Cantt, MCD, NDMC"
    )


def test_geography_keeps_a_single_place():
    assert normalize_catalogue_geography("Delhi") == "Delhi"
    assert normalize_catalogue_geography("NCT of Delhi") == "NCT of Delhi"


def test_geography_header_alone_is_not_coverage():
    assert normalize_catalogue_geography("Region") is None
    assert normalize_catalogue_geography("Geography") is None


def test_geography_list_from_llm_is_flattened():
    assert normalize_catalogue_geography(
        ["URBAN", "Rural", "Region", "Delhi Cantt, MCD, NDMC, Urban"]
    ) == "Urban, Rural, Delhi Cantt, MCD, NDMC"


def test_stringify_metadata_normalizes_geography():
    out = _stringify_metadata_values({
        "geography": "URBAN; Urban; Rural; Region; Urban, Delhi Cantt, MCD, NDMC",
        "product": "Vital statistics",
    })
    assert out["geography"] == "Urban, Rural, Delhi Cantt, MCD, NDMC"
    assert out["product"] == "Vital statistics"
