"""LGD matching uses the same Directory.search cascade as lgd_explorer."""
from __future__ import annotations

from app.services.classification.lgd_matching import (
    match_lgd_values,
    reset_lgd_directory_cache,
)


def setup_function():
    reset_lgd_directory_cache()


def test_match_exact_name_autofills():
    # Prefer a single-code village so auto-fill stays true (Delhi is multi-code).
    matches = match_lgd_values(["Shahbad Daulatpur"])
    assert "Shahbad Daulatpur" in matches
    m = matches["Shahbad Daulatpur"]
    assert m["source"] == "lgd"
    assert m["lgd_code"] or m["code"]
    assert m["kind"] in {"exact name", "normalized name", "partial name", "code"}
    assert m.get("ambiguous") in (False, None)
    assert m["auto_fill"] is True
    assert m["confidence"] == "high"
    assert m["title"] or m["name_english"]


def test_match_by_code():
    # Pick a known code from a prior exact lookup so the test stays data-driven.
    seed = match_lgd_values(["Shahbad Daulatpur"])
    code = str(seed["Shahbad Daulatpur"]["code"])
    matches = match_lgd_values([code])
    assert code in matches
    assert matches[code]["kind"] == "code"
    assert matches[code]["auto_fill"] is True
    assert matches[code]["code"] == code


def test_match_skips_blanks_and_dedupes():
    matches = match_lgd_values(["", "  ", "Shahbad Daulatpur", "Shahbad Daulatpur"])
    assert list(matches.keys()) == ["Shahbad Daulatpur"]


def test_partial_name_sort_does_not_compare_dicts():
    # Multi-token / partial paths used to crash when sort compared record dicts.
    matches = match_lgd_values(["New Delhi", "South", "Ward"])
    assert isinstance(matches, dict)
    for value, m in matches.items():
        assert m.get("code") or m.get("lgd_code")
        assert m.get("kind")


def test_compound_vs_spaced_with_parenthetical_qualifier():
    """``Tehri Daulatpur`` must resolve to ``Tehri Daulat Pur (Un-Inhabited)``.

    General rules only: strip ``(...)`` for index variants + join adjacent
    tokens (``daulat``+``pur`` ↔ ``daulatpur``). No place-name hardcoding.
    """
    matches = match_lgd_values(["Tehri Daulatpur"])
    assert "Tehri Daulatpur" in matches
    m = matches["Tehri Daulatpur"]
    title = str(m.get("title") or m.get("name_english") or "")
    assert "Tehri Daulat Pur" in title
    assert m.get("code") or m.get("lgd_code")
    assert m["kind"] in {
        "normalized name",
        "partial name",
        "exact name",
        "fuzzy name",
        "similar name",
    }


def test_existing_exact_matches_still_preferred():
    matches = match_lgd_values(["Delhi", "Shahbad Daulatpur"])
    # Delhi also has a village with the same spelling — multi-code must not auto-fill.
    delhi = matches["Delhi"]
    if delhi.get("ambiguous"):
        assert delhi["auto_fill"] is False
        assert delhi["candidate_count"] >= 2
        assert len(delhi["candidates"]) >= 2
    else:
        assert delhi["kind"] in {"exact name", "normalized name", "code"}
        assert delhi["auto_fill"] is True
    assert "Shahbad Daulatpur" in matches["Shahbad Daulatpur"]["title"] or matches[
        "Shahbad Daulatpur"
    ]["title"] == "Shahbad Daulatpur"


def test_ambiguous_place_exposes_candidates_without_autofill():
    matches = match_lgd_values(["Narela", "Badarpur"])
    for name in ("Narela", "Badarpur"):
        assert name in matches
        m = matches[name]
        assert m["ambiguous"] is True
        assert m["auto_fill"] is False
        assert m["needs_manual_review"] is True
        assert m["candidate_count"] >= 2
        codes = {str(c["code"]) for c in m["candidates"]}
        assert len(codes) >= 2


def test_all_states_merged_without_duplicate_delhi():
    from app.services.classification.lgd_directory import Directory
    from app.services.classification.lgd_matching import get_lgd_directory

    reset_lgd_directory_cache()
    directory = get_lgd_directory()
    assert isinstance(directory, Directory)
    state_delhi = [
        e for e in directory.entities
        if e.get("entity_type") == "state" and str(e.get("lgd_code") or "") == "7"
    ]
    assert len(state_delhi) == 1
    # Other states from hierarchy_all_states.json are searchable.
    matches = match_lgd_values(["Bihar", "Maharashtra"])
    assert matches["Bihar"]["code"] == "10"
    assert matches["Bihar"]["entity_type"] == "state"
    assert matches["Maharashtra"]["entity_type"] == "state"
    assert matches["Maharashtra"]["auto_fill"] is True


def test_ndmc_alias_resolves_new_delhi_municipal_council():
    matches = match_lgd_values(["NDMC", "ndmc"])
    for key in ("NDMC", "ndmc"):
        assert key in matches
        m = matches[key]
        assert "New Delhi Municipal Council" in str(m.get("title") or m.get("name_english") or "")
        assert m["auto_fill"] is True
        assert m.get("ambiguous") in (False, None)


def test_delhi_cantt_alias_offers_cantonment_choices():
    matches = match_lgd_values(["Delhi cantt", "Delhi cant"])
    for key in ("Delhi cantt", "Delhi cant"):
        assert key in matches
        m = matches[key]
        titles = {
            str(c.get("title") or c.get("name_english") or "")
            for c in (m.get("candidates") or [])
        }
        assert any("Delhi Cantonment" == t for t in titles)
        assert any("Cantonment Board" in t for t in titles)
        assert m["ambiguous"] is True
        assert m["auto_fill"] is False
        assert m["needs_manual_review"] is True


def test_mcd_alias_offers_east_north_south_corporations():
    matches = match_lgd_values(["MCD", "Municipal Corporation of Delhi"])
    for key in ("MCD", "Municipal Corporation of Delhi"):
        assert key in matches
        m = matches[key]
        titles = {
            str(c.get("title") or c.get("name_english") or "")
            for c in (m.get("candidates") or [])
        }
        assert "East Delhi Municipal Corporation" in titles
        assert "North Delhi Municipal Corporation" in titles
        assert "South Delhi Municipal Corporation" in titles
        assert m["ambiguous"] is True
        assert m["auto_fill"] is False
        assert len(m["candidates"]) >= 3

