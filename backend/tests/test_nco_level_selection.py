"""Regression: Other-X shadowing, residual NEC, non-occupation, crosswalk, aliases."""
from __future__ import annotations

import csv
import os

import pytest

from app.services.classification import nco_aliases as aliases_mod
from app.services.classification import nco_matching as matching
from app.services.classification.nco_pipeline import (
    build_index,
    rank_occupation,
    title_is_residual,
)

CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data",
    "nco_2015_concordance.csv",
)


def _load_concordance_rows():
    rows = []
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            code = (r.get("NCO_2015_Code") or "").strip()
            title = (r.get("Occupation_Title") or "").strip()
            if not code or not title:
                continue
            rows.append({
                "nco_code": code,
                "occupation_title": title,
                "division_code": (r.get("Division_Code") or "").strip(),
                "division_title": (r.get("Division_Title") or "").strip(),
                "subdivision_code": (r.get("SubDivision_Code") or "").strip(),
                "subdivision_title": (r.get("SubDivision_Title") or "").strip(),
                "group_code": (r.get("Group_Code") or "").strip(),
                "group_title": (r.get("Group_Title") or "").strip(),
                "family_code": (r.get("Family_Code") or "").strip(),
                "family_title": (r.get("Family_Title") or "").strip(),
            })
    return rows


@pytest.fixture(scope="module")
def nco_index():
    return build_index(_load_concordance_rows())


def test_title_is_residual_detects_other_and_nec():
    assert title_is_residual("Other Sales Workers")
    assert title_is_residual("Sales Workers, Other")
    assert title_is_residual("Travel Attendants and Travel Stewards, Other")
    assert title_is_residual("Not Elsewhere Classified")
    assert not title_is_residual("Sales Workers")
    assert not title_is_residual("Personal Service Workers")


def test_sales_workers_not_shadowed_by_other_sales(nco_index):
    result = rank_occupation("Sales Workers", nco_index)
    assert result is not None
    assert result.get("code") == "52"
    assert result.get("level") == "subdivision"
    assert result.get("auto_fill") is True


def test_other_sales_workers_returns_group_524(nco_index):
    result = rank_occupation("Other Sales Workers", nco_index)
    assert result is not None
    assert result.get("code") == "524"
    assert result.get("level") == "group"


@pytest.mark.parametrize(
    "label,expected_code",
    [
        ("Health Professionals", "22"),
        ("Teaching Professionals", "23"),
        ("Health Associate Professionals", "32"),
        ("Personal Service Workers", "51"),
        ("Stationary Plant and Machine Operators", "81"),
    ],
)
def test_plain_x_not_shadowed_by_other_x(nco_index, label, expected_code):
    result = rank_occupation(label, nco_index)
    assert result is not None
    assert result.get("code") == expected_code
    assert result.get("level") in ("subdivision", "group", "division")
    assert "Other" not in (result.get("title") or "")


def test_clerical_workers_not_auto_441(nco_index):
    result = rank_occupation("Clerical workers", nco_index)
    assert result is not None
    # Must not land on residual group 441 Other Clerical Support Workers as auto.
    if result.get("code") in ("44", "441"):
        assert result.get("auto_fill") is False
        assert result.get("status") == "needs_review"
    else:
        assert result.get("code") != "441"


@pytest.mark.parametrize(
    "label",
    [
        "Sales Workers NEC",
        "Sales Workers, n.e.c.",
        "NEC Sales Workers",
    ],
)
def test_sales_workers_nec_variants_are_review(nco_index, label):
    result = rank_occupation(label, nco_index)
    assert result is not None
    # Residual-marked inputs may consider Other/NEC, but stay review unless exact Other title.
    if result.get("auto_fill"):
        assert title_is_residual(result.get("title") or "") or result.get("status") == "exact_match"
    else:
        assert result.get("status") in ("needs_review", "unmatched", "exact_match", "auto_matched")
        assert result.get("auto_fill") is False or result.get("status") == "exact_match"


def test_non_occupation_exact_phrases():
    for label in (
        "Housewife / non-workers",
        "HOUSEWIFE / NON WORKERS",
        "Student",
        "Unemployed",
        "Not in labour force",
        "Homemaker",
        "Retired",
        "Dependent",
    ):
        assert matching.is_non_occupation_status(label), label
        result = matching.match_occupation(conn=None, occupation_text=label, extractor=None)
        assert result is not None
        assert result["status"] == "not_an_occupation"
        assert result["code"] is None
        assert result["auto_fill"] is False


def test_non_occupation_does_not_block_content_titles():
    assert not matching.is_non_occupation_status("Student Welfare Officer")
    assert not matching.is_non_occupation_status("Retired Teacher")
    assert not matching.is_non_occupation_status("Homemaker Services Supervisor")


def test_legacy_crosswalk_sales_and_service(monkeypatch):
    matching.clear_crosswalk_cache()
    monkeypatch.setattr(matching, "_load_all_codes", lambda conn: _load_concordance_rows())

    sales = matching.match_occupation(conn=object(), occupation_text="SALE WORKERS", extractor=None)
    assert sales is not None
    assert sales["code"] == "52"
    assert sales["source"] == "seed"
    assert sales["auto_fill"] is True

    service = matching.match_occupation(conn=object(), occupation_text="SERVICE WORKERS", extractor=None)
    assert service is not None
    assert service["ambiguous"] is True
    assert service["auto_fill"] is False
    codes = {c["code"] for c in service["candidates"]}
    assert codes == {"51", "53", "54"}

    combined = matching.match_occupation(
        conn=object(),
        occupation_text="Service workers and shop & market sales workers",
        extractor=None,
    )
    assert combined is not None
    assert combined["code"] == "5"
    assert combined["level"] == "division"

    prof = matching.match_occupation(
        conn=object(),
        occupation_text="PROFESSIONAL / TECHNICAL RELATED WORKERS",
        extractor=None,
    )
    assert prof is not None
    assert prof["ambiguous"] is True
    assert {c["code"] for c in prof["candidates"]} == {"2", "3"}


def test_alias_conflict_does_not_overwrite():
    store = {}

    class FakeCursor:
        def __init__(self):
            self.rowcount = 0
            self._last = None

        def execute(self, sql, params=None):
            sql_l = " ".join(sql.lower().split())
            if sql_l.startswith("select"):
                norm = params[0]
                row = store.get(norm)
                self._last = [row] if row else []
            elif sql_l.startswith("insert"):
                norm, level, code, title, source, version = params
                store[norm] = {
                    "normalized_value": norm,
                    "level": level,
                    "code": code,
                    "title": title,
                    "source": source,
                    "nco_version": version,
                }
                self.rowcount = 1
                self._last = None
            elif sql_l.startswith("update"):
                self.rowcount = 1
                self._last = None
            else:
                self._last = None

        def fetchone(self):
            if not self._last:
                return None
            return self._last[0]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeConn:
        def cursor(self, cursor_factory=None):
            return FakeCursor()

        def commit(self):
            return None

    conn = FakeConn()
    first = aliases_mod.upsert_nco_aliases(
        conn,
        [{"value": "Widget Maker", "code": "1", "level": "division", "title": "Managers"}],
        source="steward",
    )
    assert first["saved"] == 1
    assert store["widget maker"]["code"] == "1"

    second = aliases_mod.upsert_nco_aliases(
        conn,
        [{"value": "Widget Maker", "code": "2", "level": "division", "title": "Professionals"}],
        source="steward",
    )
    assert second["saved"] == 0
    assert len(second["conflicts"]) == 1
    assert store["widget maker"]["code"] == "1"

    ambiguous = aliases_mod.upsert_nco_aliases(
        conn,
        [{"value": "SERVICE WORKERS", "code": "51", "level": "subdivision", "title": "Personal Service Workers"}],
        source="steward",
    )
    assert ambiguous["saved"] == 0
    assert ambiguous["rejected_ambiguous"]


def test_hierarchy_validate_rebuilds_from_registry():
    rows = _load_concordance_rows()
    matching.clear_codes_cache()
    # Pick a known occupation and poison hierarchy fields.
    sample = next(r for r in rows if r["nco_code"] == "5223.0100")
    poisoned = {
        "level": "occupation",
        "code": "5223.0100",
        "nco_code": "5223.0100",
        "title": sample["occupation_title"],
        "division_code": "2",  # wrong
        "division_title": "Professionals",
        "subdivision_code": sample["subdivision_code"],
        "family_code": sample["family_code"],
        "group_code": sample["group_code"],
        "status": "auto_matched",
        "auto_fill": True,
        "confidence": "high",
    }

    class Conn:
        pass

    matching._CODES_CACHE = rows
    fixed = matching.validate_and_rebuild_hierarchy(poisoned, conn=Conn())
    assert fixed["division_code"] == sample["division_code"]
    assert fixed["division_title"] == sample["division_title"]
    assert fixed["family_code"] == sample["family_code"]
