"""Missing birth-order leaf strips must not glue measure columns together."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.utils.header_utils import dataframe_from_extracted_rows
from app.services.extraction.pdf.confidence_validation.table_confidence import _structural_bucket_for_df, classify_page


def _religion_all_missing_leaf_rows():
    """B-14 RELIGION-ALL shape: BIRTH ORDER colspan, no 1..>8 leaf row."""
    return [
        ["TABLE: B-14"] + [None] * 11,
        [
            "LIVE BIRTHS BY THE AGE OF THE MOTHER, BIRTH ORDER AND "
            "RELIGION OF THE FAMILY(RURAL)"
        ]
        + [None] * 11,
        ["RELIGION- ALL"] + [None] * 11,
        ["Sl.No.", "MOTHER AGE", "BIRTH ORDER"] + [None] * 8 + ["All"],
        # Leaf strip absent — data starts immediately (pymupdf drop).
        ["1", "< 15", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0"],
        ["2", "15 - 19", "556", "28", "5", "3", "0", "0", "0", "0", "0", "592"],
        ["3", "20 - 24", "8058", "3798", "560", "73", "6", "3", "3", "0", "0", "12501"],
        ["TOTAL", "TOTAL", "46082", "29322", "9361", "1590", "321", "66", "17", "0", "0", "86760"],
    ]


def _mother_education_with_age_of_fragment():
    """Education banner + AGE OF stub fragment; leaf strip parked as data."""
    return [
        ["TABLE: B-12"] + [None] * 11,
        [
            "LIVE BIRTHS BY AGE OF MOTHER AND BIRTH ORDER FOR EACH LEVEL "
            "OF MOTHER EDUCATION (URBAN)"
        ]
        + [None] * 11,
        ["", "AGE OF", "MOTHER EDUCATION = 3 PPRIMARY BUT BELOW MATRIC"]
        + [None] * 8
        + [""],
        ["Sl.No.", "MOTHER", "1", "2", "3", "4", "5", "6", "7", "8", ">8", "All"],
        ["1", "< 15", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0"],
        ["2", "15 - 19", "2222", "128", "13", "6", "1", "0", "0", "0", "0", "2370"],
        ["3", "20 - 24", "30978", "13730", "1790", "157", "19", "6", "1", "0", "0", "46681"],
    ]


def test_missing_leaf_keeps_twelve_columns_unglued():
    df = dataframe_from_extracted_rows(_religion_all_missing_leaf_rows())
    assert df.shape[1] == 12, list(df.columns)
    assert list(df.columns)[:4] == ["Sl.No.", "MOTHER AGE", "1", "2"]
    assert list(df.columns)[-2:] == [">8", "All"]
    # Values stay in separate cells — not "556 28 5 3".
    row = [str(v) if v is not None else "" for v in df.iloc[1].tolist()]
    assert row[2] == "556"
    assert row[3] == "28"
    assert " " not in row[2]
    bucket, reason, _ = _structural_bucket_for_df(df)
    assert bucket == "high", reason


def test_education_age_of_fragment_promotes_leaf_and_stub():
    df = dataframe_from_extracted_rows(_mother_education_with_age_of_fragment())
    assert df.shape[1] == 12, list(df.columns)
    cols = [str(c) for c in df.columns]
    assert "Col_1" not in cols
    assert cols[0].lower().startswith("sl")
    # Stub recovered to AGE OF MOTHER from caption + leaf promotion.
    assert "AGE OF" in cols[1].upper() and "MOTHER" in cols[1].upper()
    assert cols[2:5] == ["1", "2", "3"]
    row = [str(v) if v is not None else "" for v in df.iloc[1].tolist()]
    assert row[2] == "2222"
    assert row[3] == "128"
    assert " " not in row[2]
    bucket, reason, _ = _structural_bucket_for_df(df)
    assert bucket == "high", reason


def test_page3_b12_pdf_stays_high_twelve_cols():
    pdf = Path(
        "/Users/sriramrahul/.cursor/projects/"
        "Users-sriramrahul-Desktop-dhara-toolkit-own-dhara-poc/attachments/"
        "bb2476fb-6852-45ec-a3a2-7bbf982b7a32/13-62-76-testing_1.pdf"
    )
    if not pdf.is_file():
        return
    import pymupdf
    from app.services.extraction.pdf.utils.workers import extract_pymupdf_chunk

    cands = [
        c
        for c in extract_pymupdf_chunk(str(pdf), [3])
        if c.get("method") == "pymupdf_lines_strict"
    ]
    assert cands
    for c in cands:
        df = c["df"]
        assert df.shape[1] == 12, list(df.columns)
        assert "Col_1" not in [str(x) for x in df.columns]
        # No glued measure packs.
        for col in df.columns:
            for v in df[col].values:
                s = str(v) if v is not None else ""
                parts = s.split()
                if len(parts) >= 3 and all(p.replace(",", "").isdigit() for p in parts):
                    raise AssertionError(f"glued cell {s!r} in {col}")
    bucket, reason, _ = classify_page(cands)
    assert bucket == "high", reason
