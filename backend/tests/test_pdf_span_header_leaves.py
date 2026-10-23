"""Spanning sex/age headers and birth-order leaf rows stay in the header."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.utils.header_utils import dataframe_from_extracted_rows


def _vital_stats_header_raw():
    """Group title and MALE/FEMALE/TOTAL packed into the first cell of each span."""
    return [
        ["VITAL STATISTICS BY SEX, 1991 - 2004", None, None, None, None, None, None, None, None, None, None],
        [
            "YEAR",
            "LIVE BIRTHS\nMALE FEMALE TOTAL",
            None,
            None,
            "DEATHS\nMALE FEMALE TOTAL",
            None,
            None,
            "INFANT DEATHS\nMALE FEMALE TOTAL",
            None,
            None,
            "MATERNAL\nDEATHS",
        ],
        ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"],
        ["1991", "145694", "126326", "272020", "37828", "22772", "60600", "5432", "3374", "8806", "113"],
        ["1992", "147138", "126840", "273978", "38742", "23180", "61922", "5654", "3377", "9031", "79"],
    ]


def _order_leaf_raw():
    """1ST/2ND leaves parked under a one-cell BIRTH ORDER band."""
    return [
        ["YEAR", "LIVE BIRTHS BY ORDER OF BIRTH", None, None, None],
        [None, "BIRTH ORDER", None, None, None],
        [None, "1ST", "2ND", "3rd", "4th"],
        ["1", "2", "3", "4", "5"],
        ["1991", "94886", "74457", "48442", "22201"],
        ["1992", "95600", "75100", "49289", "22504"],
    ]


def test_packed_sex_leaves_become_header_paths():
    df = dataframe_from_extracted_rows(_vital_stats_header_raw())
    meta = list(df.attrs.get("dhara_column_meta") or [])
    paths = [m.get("header_path") for m in meta]
    assert paths[0] == ["YEAR"]
    assert paths[1] == ["LIVE BIRTHS", "MALE"]
    assert paths[2] == ["LIVE BIRTHS", "FEMALE"]
    assert paths[3] == ["LIVE BIRTHS", "TOTAL"]
    assert paths[4] == ["DEATHS", "MALE"]
    assert paths[10] == ["MATERNAL DEATHS"]
    # Column-number strip stays the first body row; the year row follows.
    assert str(df.iloc[0, 0]) == "1"
    assert str(df.iloc[1, 0]) == "1991"
    assert str(df.iloc[1, 1]) == "145694"
    assert str(df.iloc[1, -1]) == "113"


def test_packed_leaves_are_not_tied_to_one_vocabulary():
    """Same span shape, different labels: categories and age bands."""
    df = dataframe_from_extracted_rows([
        ["AREA", "SECTOR\nSC ST OTHERS", None, None, "AGE GROUP\n0-14 15-19 20-24", None, None],
        ["1", "2", "3", "4", "5", "6", "7"],
        ["North", "10", "4", "1", "80", "40", "20"],
        ["South", "12", "3", "2", "70", "35", "18"],
    ])
    paths = [m.get("header_path") for m in (df.attrs.get("dhara_column_meta") or [])]
    assert paths[1:] == [
        ["SECTOR", "SC"],
        ["SECTOR", "ST"],
        ["SECTOR", "OTHERS"],
        ["AGE GROUP", "0-14"],
        ["AGE GROUP", "15-19"],
        ["AGE GROUP", "20-24"],
    ]
    assert str(df.iloc[1, 0]) == "North"
    assert str(df.iloc[1, 1]) == "10"


def test_wrapped_single_label_is_not_split():
    """A title that wraps inside one span is not sliced into columns."""
    df = dataframe_from_extracted_rows([
        ["BIRTH ORDER", "Primary but\nBelow Matric", "AGE NOT\nSTATED", None],
        ["1", "2", "3", "4"],
        ["1", "1179", "50", "6143"],
        ["2", "706", "43", "4165"],
    ])
    paths = [m.get("header_path") for m in (df.attrs.get("dhara_column_meta") or [])]
    assert paths[1] == ["Primary but Below Matric"]
    joined = " ".join(paths[2])
    assert "NOT" in joined.upper() and "STATED" in joined.upper()
    assert str(df.iloc[1, 1]) == "1179"


def test_birth_order_leaf_row_is_header_not_body():
    df = dataframe_from_extracted_rows(_order_leaf_raw())
    meta = list(df.attrs.get("dhara_column_meta") or [])
    paths = [m.get("header_path") for m in meta]
    assert paths[1][-1] == "1ST"
    assert paths[2][-1] == "2ND"
    assert paths[3][-1] == "3rd"
    assert paths[1][0].startswith("LIVE BIRTHS")
    # Leaves are not dumped into the body. Index strip, then 1991.
    assert str(df.iloc[0, 0]) == "1"
    assert str(df.iloc[1, 0]) == "1991"
    assert str(df.iloc[1, 1]) == "94886"
    assert not any(str(v).upper() == "1ST" for v in df.iloc[:, 1].tolist())


def test_month_sex_groups_keep_index_row_and_all_measures():
    """Rural/Urban/Total with a repeated Total leaf, plus a stacked month column."""
    df = dataframe_from_extracted_rows([
        ["Months", "Rural", None, None, "Urban", None, None, "Total", None, None],
        [None, "Male", "Female", "Total", "Male", "Female", "Total", "Male", "Female", "Total"],
        ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"],
        [
            "JANUARY\nFEBURARY",
            "167\n268",
            "79\n105",
            "246\n373",
            "3264\n4262",
            "2017\n2563",
            "5281\n6825",
            "3431\n4530",
            "2096\n2668",
            "5527\n7198",
        ],
        ["TOTAL", "3325", "1625", "4950", "49691", "30737", "80428", "53016", "32362", "85378"],
    ])
    paths = [m.get("header_path") for m in (df.attrs.get("dhara_column_meta") or [])]
    assert paths == [
        ["Months"],
        ["Rural", "Male"],
        ["Rural", "Female"],
        ["Rural", "Total"],
        ["Urban", "Male"],
        ["Urban", "Female"],
        ["Urban", "Total"],
        ["Total", "Male"],
        ["Total", "Female"],
        ["Total", "Total"],
    ]
    assert [str(v) for v in df.iloc[0]] == ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]
    assert [str(v) for v in df.iloc[1]] == [
        "JANUARY", "167", "79", "246", "3264", "2017", "5281", "3431", "2096", "5527",
    ]
    assert str(df.iloc[-1, 0]) == "TOTAL"
    assert str(df.iloc[-1, -1]) == "85378"


def test_estimated_population_group_stays_aligned():
    """Two-level mid-year header, column numbers, and registration columns in order."""
    df = dataframe_from_extracted_rows([
        [
            "S.No.",
            "Local Body",
            "Population -2001",
            "No. of Registration\nUnit",
            "No. of\nmonthly\nReturns Due",
            "No. of Monthly\nreturns not\nreceived",
            "Estimated Mid Year Population",
            None,
        ],
        [None, None, None, None, None, None, "Total", "Adjusted for\nIncomplete Receipts\nor Returns"],
        ["1", "2", "3", "4", "5", "6", "7", "8"],
        ["1\n2", "MCD(U)\nNDMC", "12478500\n302363", "137\n9", "1644\n108", "0\n0", "NA\nNA", None],
        [None, "TOTAL", "13850507", "198", "2376", "0", "15279000", None],
    ])
    paths = [m.get("header_path") for m in (df.attrs.get("dhara_column_meta") or [])]
    assert paths[3] == ["No. of Registration Unit"]
    assert paths[4] == ["No. of monthly Returns Due"]
    assert paths[5] == ["No. of Monthly returns not received"]
    assert paths[6] == ["Estimated Mid Year Population", "Total"]
    assert paths[7][0] == "Estimated Mid Year Population"
    assert "Adjusted" in paths[7][-1]
    assert [str(v) for v in df.iloc[0]] == ["1", "2", "3", "4", "5", "6", "7", "8"]
    assert [str(v) for v in df.iloc[1]] == ["1", "MCD(U)", "12478500", "137", "1644", "0", "NA", "None"]
    assert str(df.iloc[-1, 1]) == "TOTAL"
    assert str(df.iloc[-1, 6]) == "15279000"
