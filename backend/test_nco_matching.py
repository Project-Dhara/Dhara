"""Golden tests for nco_matching.py's deterministic (no-LLM) shortlist.

Runs the same `_shortlist` / `_fallback_best_match` logic used when
SKIP_LLM=1 / no extractor is supplied, against representative legacy
occupation category values -- the ones already surfaced in the mock
Classify UI (frontend/src/components/Classify.jsx MAP_DEFS.occ) plus a
couple of raw-dataset-style variants (typos, comma/slash-joined titles) --
and checks the top match lands in the expected NCO 2015 family/division.

No real distinct-occupation-value dump from a pushed dataset was available
in this repo at the time this was written; update EXPECTED below with the
actual values once one is pushed through Classify, per the guide's section 6.

Run directly (loads the concordance CSV, no DB/LLM needed):
    python backend/test_nco_matching.py
"""

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import nco_matching as nco

CSV_PATH = os.path.join(os.path.dirname(__file__), "data", "nco_2015_concordance.csv")

# input -> (acceptable division codes, expected level)
EXPECTED = {
    "CLERICAL WORKERS": (("4",), "division"),
    "SALE WORKERS": (("5",), "subdivision"),
    "SERVICE WORKERS": (("5",), "subdivision"),
    "FARMERS,FISHERMEN,HUNTERS etc": (("6",), "division"),
    "PROFESSIONAL / TECHNICAL": (("2", "3"), "division"),
    "PROFESSIONAL / TECHNICAL RELATED WORKERS": (("2", "3"), "division"),
    "ADMINISTRATIVE, EXECUTIVE": (("1",), "subdivision"),
    "ADMINISTRATIVE, EXECUTIVE AND MANAGERIAL WORKERS": (("1",), "subdivision"),
}


def _load_rows():
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


def run():
    rows = _load_rows()
    assert rows, f"no rows loaded from {CSV_PATH}"

    failures = []
    for text, (expected_divisions, expected_level) in EXPECTED.items():
        result = nco._fallback_best_match(text, rows)
        got_codes = set(result.get("codes") or [result.get("division_code") or result.get("code")])
        ok_div = bool(result) and (
            set(expected_divisions).issubset(got_codes)
            if len(expected_divisions) > 1
            else (result.get("division_code") in expected_divisions)
        )
        ok_level = bool(result) and result.get("level") == expected_level
        status = "OK" if ok_div and ok_level else "MISMATCH"
        if status == "MISMATCH":
            failures.append((text, expected_divisions, result))
        print(
            f"[{status}] {text!r} -> {result.get('level')} {result.get('code')} "
            f"(div {result.get('division_code')}, family {result.get('family_code')!r})"
            if result else f"[{status}] {text!r} -> no match"
        )

    if failures:
        print(f"\n{len(failures)} of {len(EXPECTED)} golden cases failed:")
        for text, expected, result in failures:
            print(f"  {text!r}: expected div {expected} level {EXPECTED[text][1]}, got {result}")
        sys.exit(1)
    print(f"\nAll {len(EXPECTED)} golden cases passed.")


if __name__ == "__main__":
    run()
