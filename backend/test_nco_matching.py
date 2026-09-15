"""Golden tests for nco_matching.py's deterministic (no-LLM) shortlist.

Runs `_fallback_best_match` against representative census-style occupation
labels. Expectations allow the dynamic fuzzy/token scorer some latitude on
level (division vs subdivision) as long as the major group is correct.

Run:
    python backend/test_nco_matching.py
"""

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import nco_matching as nco

CSV_PATH = os.path.join(os.path.dirname(__file__), "data", "nco_2015_concordance.csv")

# input -> frozenset of acceptable division codes
EXPECTED_DIVISIONS = {
    "CLERICAL WORKERS": frozenset({"4"}),
    "SALE WORKERS": frozenset({"5"}),
    "SERVICE WORKERS": frozenset({"5"}),
    "FARMERS,FISHERMEN,HUNTERS etc": frozenset({"6"}),
    "PROFESSIONAL / TECHNICAL": frozenset({"2", "3"}),
    "PROFESSIONAL / TECHNICAL RELATED WORKERS": frozenset({"2", "3"}),
    "ADMINISTRATIVE, EXECUTIVE": frozenset({"1"}),
    "ADMINISTRATIVE, EXECUTIVE AND MANAGERIAL WORKERS": frozenset({"1"}),
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


def _division_of(result):
    if not result:
        return None
    if result.get("division_code"):
        return str(result["division_code"])
    code = str(result.get("code") or "")
    # subdivision/family codes start with the division digit(s)
    if code and code[0].isdigit():
        return code[0]
    return None


def run():
    # Clear caches so CSV-backed nodes are used.
    nco._CODES_CACHE = None
    nco._NODES_CACHE = None
    nco._EMBED_CACHE = None

    rows = _load_rows()
    assert rows, f"no rows loaded from {CSV_PATH}"

    failures = []
    for text, expected_divs in EXPECTED_DIVISIONS.items():
        result = nco._fallback_best_match(text, rows)
        got = _division_of(result)
        # Also accept when the top alternative is in the expected set and
        # confidence is low (gate should block auto-fill).
        ok = got in expected_divs
        if not ok and result:
            alt_divs = {
                str(a.get("code", ""))[0]
                for a in (result.get("alternatives") or [])
                if str(a.get("code") or "")[:1].isdigit()
            }
            # Low-confidence wrong top is acceptable if expected is in shortlist alts
            # and auto_fill is false — still fail the golden for retrieval quality.
            ok = False
        status = "OK" if ok else "MISMATCH"
        if status == "MISMATCH":
            failures.append((text, expected_divs, result))
        print(
            f"[{status}] {text!r} -> {result.get('level')} {result.get('code')} "
            f"(div {got}, conf {result.get('confidence')}, auto_fill={result.get('auto_fill')})"
            if result else f"[{status}] {text!r} -> no match"
        )

    if failures:
        print(f"\n{len(failures)} of {len(EXPECTED_DIVISIONS)} golden cases failed:")
        for text, expected, result in failures:
            print(f"  {text!r}: expected div {sorted(expected)}, got {_division_of(result)} {result}")
        sys.exit(1)
    print(f"\nAll {len(EXPECTED_DIVISIONS)} golden cases passed.")


if __name__ == "__main__":
    run()
