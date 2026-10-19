"""Recover Col_N stubs and jammed Age of mother / Birth order headers."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.utils.grid_repair import extract_needs_cell_clip
from app.services.extraction.pdf.utils.header_detect import (
    _recover_placeholder_column_headers,
)
from app.services.extraction.pdf.utils.header_utils import dataframe_from_extracted_rows


def _paths(df):
    return [m.get("header_path") for m in df.attrs.get("dhara_column_meta", [])]


def test_jammed_age_level_education_mother_first_column_only():
    """Corner mash must not leak leaf titles into the first column header."""
    rows = [
        [
            "Birth Order\nAge & Level of\nEducation of Mother 13 & Not\n"
            "1 2 3 4 5 6 7 8 9 10 11 12 Total\nAbove Stated",
            None, None, None, None, None, None, None, None, None, None, None, None, None, None, None,
        ],
        [None, "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13 & Above", "Not Stated", "Total"],
        ["30-34", "271", "674", "567", "242", "81", "43", "23", "15", "9", "9", "3", "1", "0", "0", "1938"],
        ["35-39", "208", "395", "326", "206", "100", "45", "30", "19", "8", "2", "2", "0", "0", "0", "1341"],
    ]
    df = dataframe_from_extracted_rows(rows)
    assert list(df.columns)[0] == "Age & Level of Education of Mother"
    assert "1 2 3" not in str(list(df.columns)[0])
    assert "Birth Order" not in str(list(df.columns)[0])
    paths = _paths(df)
    assert paths[0] == ["Age & Level of Education of Mother"]
    assert paths[1] == ["Birth Order", "1"]
    assert paths[-1] == ["Total"]


def test_jammed_age_birth_order_headers():
    rows = [
        [
            "Birth order\nAge of\nmother 1 2 3 4 5 6 7+ Not stated Total",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ],
        [None, "1", "2", "3", "4", "5", "6", "7+", "Not stated", "Total"],
        ["Below 15", "0.00", "0.00", "0.00", "0.00", "0.00", "0.00", "0.00", "0.00", "0.00"],
        ["15-19", "0.00", "0.00", "0.00", "0.00", "0.00", "0.00", "0.00", "0.00", "0.00"],
        ["20-24", "1.00", "2.00", "0.00", "0.00", "0.00", "0.00", "0.00", "0.00", "3.00"],
    ]
    assert extract_needs_cell_clip(rows)
    df = dataframe_from_extracted_rows(rows)
    assert list(df.columns)[0] == "Age of mother"
    assert not any(str(c).lower().startswith("col_") for c in df.columns)
    paths = _paths(df)
    assert paths[0] == ["Age of mother"]
    assert paths[1] == ["Birth order", "1"]
    assert paths[-2] == ["Birth order", "Not stated"]
    assert paths[-1] == ["Total"]


def test_recover_rural_urban_and_town_stubs():
    # Guard path used when resolve leaves Col_1/Col_2 for empty rowspan stubs.
    names = [
        "Col_1",
        "Col_2",
        "Government Institutions",
        "Private/ Non-Government",
        "Doctor/Nurses/Trained Midwife",
        "Traditional Birth Attendant",
        "Relatives/ Others",
        "Not Stated",
        "Total",
    ]
    meta = [{"name": n, "header_group": None, "header_path": [n]} for n in names]
    body = [
        ["Rural", "Cherthala (M)", "1", "2", "3", "4", "5", "6", "7"],
        ["Urban", "Alappuzha (M)", "1", "2", "3", "4", "5", "6", "7"],
        ["Total", "Kerala", "2", "4", "6", "8", "10", "12", "14"],
    ]
    out, out_meta = _recover_placeholder_column_headers(names, meta, body)
    assert out[:2] == ["Rural/ Urban", "Town"]
    assert out_meta[0]["header_path"] == ["Rural/ Urban"]
    assert out_meta[1]["header_path"] == ["Town"]


def test_recover_serial_district_stubs():
    rows = [
        [None, None, "Male", "Female", "Not Reported", "Total"],
        ["1", "Thiruvananthapuram", "10", "11", "0", "21"],
        ["2", "Kollam", "8", "9", "0", "17"],
        ["3", "Pathanamthitta", "5", "6", "0", "11"],
    ]
    df = dataframe_from_extracted_rows(rows)
    assert list(df.columns)[:2] == ["S.No.", "District"]


def test_recover_age_of_mother_from_body_bands():
    rows = [
        [None, "1", "2", "3", "4", "5", "6", "7+", "Not stated", "Total"],
        ["Below 15", "0", "0", "0", "0", "0", "0", "0", "0", "0"],
        ["15-19", "0", "0", "0", "0", "0", "0", "0", "0", "0"],
        ["20-24", "1", "2", "0", "0", "0", "0", "0", "0", "3"],
        ["Not stated", "0", "0", "0", "0", "0", "0", "0", "0", "0"],
    ]
    df = dataframe_from_extracted_rows(rows)
    assert list(df.columns)[0] == "Age of mother"
    paths = _paths(df)
    assert paths[1] == ["Birth order", "1"]
    assert paths[-1] == ["Total"]


def test_jammed_education_level_mother_father():
    rows = [
        ["Education level Mother Father", None, None],
        ["Illiterate", "0.36", "0.35"],
        ["Below Primary", "0.22", "0.33"],
        ["Total", "100.00", "100.00"],
    ]
    df = dataframe_from_extracted_rows(rows)
    assert list(df.columns) == ["Education level", "Mother", "Father"]
    assert list(df.iloc[0].astype(str).values) == ["Illiterate", "0.36", "0.35"]


def test_jammed_marriage_birth_order_headers():
    rows = [
        [
            "Birth order\nDuration of\nmarriage (Years) 1 2 3 4+ Not stated Total",
            None,
            None,
            None,
            None,
            None,
            None,
        ],
        [None, "1", "2", "3", "4+", "Not stated", "Total"],
        ["0-4", "40.15", "10.68", "0.58", "0.05", "0.00", "51.46"],
        ["5-9", "4.11", "19.88", "5.98", "0.66", "0.00", "30.63"],
        ["Total", "45.55", "35.98", "14.00", "4.44", "0.03", "100.00"],
    ]
    df = dataframe_from_extracted_rows(rows)
    assert list(df.columns)[0] == "Duration of marriage (Years)"
    paths = _paths(df)
    assert paths[1] == ["Birth order", "1"]
    assert paths[-2] == ["Birth order", "Not stated"]
    assert paths[-1] == ["Total"]


def test_jammed_pregnancy_birth_weight_headers():
    rows = [
        [
            "Duration of Birth weight (Kg)\npregnancy\n(weeks) <2.5 2.5-3.0 3.0-4.0 4+ Not stated Total",
            None,
            None,
            None,
            None,
            None,
            None,
        ],
        [None, "<2.5", "2.5-3.0", "3.0-4.0", "4+", "Not stated", "Total"],
        ["<32", "0.74", "0.03", "0.03", "0.00", "0.00", "0.80"],
        ["32-36", "5.51", "4.20", "2.45", "0.05", "0.00", "12.21"],
        ["Total", "15.90", "39.70", "43.60", "0.90", "0.02", "100.00"],
    ]
    df = dataframe_from_extracted_rows(rows)
    assert list(df.columns)[0] == "Duration of pregnancy (weeks)"
    paths = _paths(df)
    assert paths[1] == ["Birth weight (Kg)", "<2.5"]
    assert paths[-1] == ["Total"]


def test_rural_urban_not_invented_from_total_only_body():
    names = ["Col_1", "<2.5", "2.5-3.0", "Total"]
    meta = [{"name": n, "header_group": None, "header_path": [n]} for n in names]
    body = [
        ["<32", "0.74", "0.03", "0.80"],
        ["32-36", "5.51", "4.20", "12.21"],
        ["Total", "15.90", "39.70", "100.00"],
    ]
    out, _ = _recover_placeholder_column_headers(names, meta, body)
    assert out[0] == "Col_1"


def test_mashed_header_fails_auto_accept():
    from app.services.extraction.pdf.confidence_validation.table_confidence import (
        _structural_bucket_for_df,
    )
    import pandas as pd

    df = pd.DataFrame(
        [["0-4", "40.15", "10.68"]],
        columns=[
            "Birth order Duration of marriage (Years) 1 2 3 4+ Not stated Total",
            "1",
            "2",
        ],
    )
    bucket, reason, _ = _structural_bucket_for_df(df)
    assert bucket == "llm"
    assert "mashed" in reason.lower()


def test_promoted_data_header_fails_auto_accept():
    from app.services.extraction.pdf.confidence_validation.table_confidence import (
        _structural_bucket_for_df,
    )
    import pandas as pd

    df = pd.DataFrame(
        [
            ["Below Primary", "0.22", "0.33"],
            ["Primary but below Metric", "5.80", "11.37"],
            ["Total", "100.00", "100.00"],
        ],
        columns=["Illiterate", "0.36", "0.35"],
    )
    bucket, reason, _ = _structural_bucket_for_df(df)
    assert bucket == "llm"
    assert "promoted" in reason.lower() or "data row" in reason.lower()
