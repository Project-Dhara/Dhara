"""NCO alias validation — never treat occupation labels as codes."""
from __future__ import annotations

from catalogue.nco_matching import (
    is_usable_nco_alias,
    looks_like_nco_code,
    match_occupation,
)


def test_looks_like_nco_code():
    assert looks_like_nco_code("4")
    assert looks_like_nco_code("24")
    assert looks_like_nco_code("2411")
    assert looks_like_nco_code("2.1.0100")
    assert not looks_like_nco_code("CLERICAL WORKERS")
    assert not looks_like_nco_code("SERVICE WORKERS")
    assert not looks_like_nco_code("")


def test_aggregate_labels_get_no_code():
    from catalogue.nco_matching import is_non_occupation_aggregate, match_occupation

    for label in ("ALL", "All", "Total", "TOTAL", "Grand Total", "Sub-total"):
        assert is_non_occupation_aggregate(label), label
        assert match_occupation(conn=None, occupation_text=label) is None

    assert not is_non_occupation_aggregate("CLERICAL WORKERS")
    assert not is_non_occupation_aggregate("SERVICE WORKERS")


def test_poisoned_alias_is_rejected():
    assert not is_usable_nco_alias(
        {"code": "CLERICAL WORKERS", "level": "division", "title": ""},
        "CLERICAL WORKERS",
    )
    assert is_usable_nco_alias(
        {"code": "4", "level": "division", "title": "Clerical Support Workers"},
        "CLERICAL WORKERS",
    )


def test_match_skips_poisoned_alias(monkeypatch):
    """A bad alias row must not short-circuit matching with a text code."""
    poisoned = {
        "normalized_value": "clerical workers",
        "level": "division",
        "code": "CLERICAL WORKERS",
        "title": "",
        "source": "steward",
    }

    monkeypatch.setattr(
        "catalogue.nco_matching._lookup_alias",
        lambda conn, text: poisoned,
    )
    # Force empty concordance so we don't depend on DB — still must not
    # return the poisoned text code via the alias path.
    monkeypatch.setattr("catalogue.nco_matching._load_all_codes", lambda conn: [])

    result = match_occupation(conn=object(), occupation_text="CLERICAL WORKERS", extractor=None)
    assert result is None or looks_like_nco_code(result.get("code"))
    if result is not None:
        assert result["code"] != "CLERICAL WORKERS"
        assert result.get("source") != "alias"
