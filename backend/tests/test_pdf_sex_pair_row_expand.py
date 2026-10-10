"""Collapsed M/F sex-pair rows in cause-of-death style PDF tables must expand."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.utils.header_utils import (
    dataframe_from_extracted_rows,
    expand_collapsed_sex_pair_rows,
)


def _cell(v):
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in {"", "none", "nan"} else s


def test_expand_merges_measure_continuation_row():
    """Labels+Sex stack on one row, remaining age counts on the next (pymupdf)."""
    rows = [
        ["S.No.", "Name of the Disease", "Sex", "<1", "1-4", "Total"],
        ["(1)", "(2)", "(3)", "(4)", "(5)", "(6)"],
        [
            "1\n1\n2",
            "INTESTINAL INFECTIOUS DISEASES (A00-A09)\nCholera (A00)\nTyphoid Fever (A01)",
            "M\nF\nM\nF\nM\nF",
            # Only the first M pair's measures live on this physical row.
            "59",
            "21",
            "195",
        ],
        [
            "",
            "",
            "",
            # Continuation: F for intestinal + Cholera M/F + Typhoid M/F.
            "35\n0\n0\n0\n1",
            "20\n0\n0\n0\n0",
            "154\n1\n2\n9\n11",
        ],
    ]
    expanded = expand_collapsed_sex_pair_rows(rows)
    data = expanded[2:]
    assert len(data) == 6
    assert [r[2] for r in data] == ["M", "F", "M", "F", "M", "F"]
    assert [_cell(r[5]) for r in data] == ["195", "154", "1", "2", "9", "11"]
    assert [_cell(r[3]) for r in data] == ["59", "35", "0", "0", "0", "1"]
    assert _cell(data[0][0]) == "1"
    assert _cell(data[1][0]) == ""
    assert _cell(data[2][1]).startswith("Cholera")
    assert "Typhoid" in _cell(data[4][1])


def test_dataframe_merges_measure_continuation_from_extract_shape():
    """End-to-end: continuation merge + header detect yields dense M/F grid."""
    rows = [
        ["S.No.", "Name of the Disease", "Sex", "<1", "Total"],
        ["1", "2", "(3)", "(4)", "(5)"],
        [
            "1\n2",
            "Cholera (A00)\nPlague (A20)",
            "M\nF\nM\nF",
            "0",
            "4",
        ],
        [
            "",
            "",
            "",
            "1\n5\n3",
            "2\n10\n7",
        ],
    ]
    df = dataframe_from_extracted_rows(rows)
    # Leading 1..N / (1)(2)… index strip is retained as the first body row.
    assert df.shape[0] == 5
    data = df.iloc[1:].reset_index(drop=True)
    sexes = [_cell(v) for v in data["Sex"].tolist()]
    assert sexes == ["M", "F", "M", "F"]
    totals = [_cell(v) for v in data["Total"].tolist()]
    assert totals == ["4", "2", "10", "7"]
    assert _cell(data.iloc[0]["S.No."]) == "1"
    assert _cell(data.iloc[1]["S.No."]) == ""
    assert _cell(data.iloc[2]["S.No."]) == "2"



def test_expand_glued_digit_measures_and_serials():
    rows = [
        ["S.No.", "Name of the Disease", "Sex", "<1", "Total"],
        [
            "12",  # one digit per M/F pair
            "Cholera (A00)\nPlague (A20)",
            "M\nF\nM\nF",
            "3 5 0 1",  # space-separated age counts
            "8 4 9 5",
        ],
    ]
    expanded = expand_collapsed_sex_pair_rows(rows)
    assert len(expanded) == 5  # header + 4
    data = expanded[1:]
    assert [r[2] for r in data] == ["M", "F", "M", "F"]
    assert [_cell(r[0]) for r in data] == ["1", "", "2", ""]
    assert [_cell(r[3]) for r in data] == ["3", "5", "0", "1"]
    assert [_cell(r[4]) for r in data] == ["8", "4", "9", "5"]


def test_expand_does_not_digit_split_multidigit_total():
    # A lone "1955" with 4 sex tokens must stay atomic (not 1,9,5,5).
    rows = [
        ["S.No.", "Name", "Sex", "Total"],
        ["1", "Cholera (A00)\nPlague (A20)", "M\nF\nM\nF", "1955"],
    ]
    expanded = expand_collapsed_sex_pair_rows(rows)
    data = expanded[1:]
    assert _cell(data[0][3]) == "1955"
    assert _cell(data[1][3]) == ""
    assert _cell(data[2][3]) == ""
    assert _cell(data[3][3]) == ""


def test_expand_uses_measure_lines_when_sex_undercounts():
    """Sex only has M\\nF but age columns stack 6 lines — expand to 6, don't cram."""
    rows = [
        ["S.No.", "Name of the Disease", "Sex", "<1", "Total"],
        [
            "1\n2\n3",
            "Cholera\nTyphoid\nPlague",
            "M\nF",  # undercounts relative to measures
            "0\n1\n2\n3\n4\n5",
            "10\n11\n12\n13\n14\n15",
        ],
    ]
    expanded = expand_collapsed_sex_pair_rows(rows)
    data = expanded[1:]
    assert len(data) == 6
    assert [_cell(r[3]) for r in data] == ["0", "1", "2", "3", "4", "5"]
    assert [_cell(r[4]) for r in data] == ["10", "11", "12", "13", "14", "15"]
    # Must NOT cram leftovers into the last row as "2 3 4 5" / "12 13 14 15"
    assert " " not in _cell(data[5][3])
    assert " " not in _cell(data[5][4])


def test_expand_lone_f_with_stacked_age_lines():
    """Auto-accept failure mode: Sex shows only F but ages have many lines."""
    rows = [
        ["S.No.", "Name of the Disease", "Sex", "<1", "1-4", "Total"],
        [
            "",
            "",
            "F",
            "3\n5\n0\n0\n0\n1",
            "5\n0\n0\n0\n1\n0",
            "20\n11\n4\n2\n1\n9",
        ],
    ]
    expanded = expand_collapsed_sex_pair_rows(rows)
    data = expanded[1:]
    assert len(data) == 6
    assert _cell(data[0][2]) == "F"
    assert [_cell(r[3]) for r in data] == ["3", "5", "0", "0", "0", "1"]
    assert [_cell(r[5]) for r in data] == ["20", "11", "4", "2", "1", "9"]


def test_expand_never_joins_overflow_into_last_measure_cell():
    from app.services.extraction.pdf.utils.header_utils import _split_measure_cell_to_n

    parts = _split_measure_cell_to_n("1\n2\n3\n4\n5\n6", 2)
    assert parts == ["1", "2"]
    assert " " not in (parts[1] or "")


def test_pair_labels_do_not_put_next_disease_on_f_row():
    """Sequential fill used to park 'All other types…' on Septicaemia's F row."""
    from app.services.extraction.pdf.utils.header_utils import _assign_pair_label_parts

    out = _assign_pair_label_parts(
        ["Septicaemia (A40-A41)", "All other types of bacterial Diseases"],
        ["M", "F", "M", "F"],
    )
    assert out[0] == "Septicaemia (A40-A41)"
    assert out[1] is None  # F stub stays empty
    assert out[2] == "All other types of bacterial Diseases"
    assert out[3] is None


def test_pair_labels_keep_wrap_on_f_row():
    from app.services.extraction.pdf.utils.header_utils import _assign_pair_label_parts

    out = _assign_pair_label_parts(
        [
            "Diarrhoea and gastroenteritis of presume",
            "infectious origin (A09)",
        ],
        ["M", "F"],
    )
    assert "presume" in (out[0] or "")
    assert "infectious origin" in (out[1] or "")


def test_sex_glue_tokens_still_pair_align_labels():
    """'0M' / 'eM' must not disable pair-aware name assignment."""
    from app.services.extraction.pdf.utils.header_utils import _sex_tokens_from_cell, expand_collapsed_sex_pair_rows

    assert _sex_tokens_from_cell("M\nF\n0M\nF") == ["M", "F", "M", "F"]
    assert _sex_tokens_from_cell("eM\nF\nM\nF") == ["M", "F", "M", "F"]

    rows = [
        ["S.No.", "Name of the Disease", "Sex", "Total"],
        [
            "6\n1",
            "Protozoal diseases (B50-B64)\nMalaria (B50-B54)",
            "M\nF\n0M\nF",
            "95\n47\n90\n42",
        ],
    ]
    expanded = expand_collapsed_sex_pair_rows(rows)
    data = expanded[1:]
    assert len(data) == 4
    assert [r[2] for r in data] == ["M", "F", "M", "F"]
    assert _cell(data[0][1]).startswith("Protozoal")
    assert _cell(data[1][1]) == ""
    assert _cell(data[2][1]).startswith("Malaria")
    assert [_cell(r[3]) for r in data] == ["95", "47", "90", "42"]


def test_long_title_wraps_do_not_become_extra_rows():
    """Multi-line disease titles must stay on one M/F pair (Protozoal-page style)."""
    from app.services.extraction.pdf.utils.header_utils import _assign_pair_label_parts

    out = _assign_pair_label_parts(
        [
            "Protozoal diseases (B50-B64)",
            "Malaria (B50-B54",  # clipped ')'
            "All other types of protozoal diseases (B55-B64)",
            "Other certain infectious and pasastic",
            "diseases & late effect of infectious and",
            "parasitic diseases (A65-A69 & A75-A79, B35-",
            "B49 B65-B94 & B99)",
            "Filariasis (B74)",
        ],
        ["M", "F"] * 5,
    )
    assert out[0].startswith("Protozoal")
    assert out[2].startswith("Malaria")
    assert out[3] is None or out[3] == "" or "All other" not in (out[3] or "")
    assert "All other types of protozoal" in (out[4] or "")
    assert "Other certain" in (out[6] or "")
    assert "diseases & late" in (out[7] or "")
    assert "Filariasis" in (out[8] or "")
    assert out[9] is None


def test_misadventure_block_keeps_e57_subrows():
    rows = [
        ["S.No.", "Name of the Disease", "Sex", "Total"],
        [
            "2\nE57\n1\nE58",
            "Misadven during surgical & medical care, advers\n"
            "adverse incidents in diagnostic and therapeutic\n"
            "use, abnormal reactions and late complications\n"
            "(Y60-Y69,Y70-Y82 & Y83-Y84)\n"
            "Other external causes of accidental injury not\n"
            "elasewhere classified (W20-W64, W75-W99,\n"
            "X10-X39, X50-X59)\n"
            "Accidents caused by firearm missile\n"
            "(W32-W34)\n"
            "Late effects of external causes of morbidity and\n"
            "mortality (Y85-Y89)",
            "eM\nF\nM\nF\nM\nF\nM\nF",
            "1\n1\n0\n0\n0\n0\n0\n0",
        ],
    ]
    df = dataframe_from_extracted_rows(rows)
    assert df.shape[0] == 8
    snos = [_cell(v) for v in df["S.No."].tolist()]
    names = [_cell(v) for v in df["Name of the Disease"].tolist()]
    sexes = [_cell(v) for v in df["Sex"].tolist()]
    assert sexes == ["M", "F", "M", "F", "M", "F", "M", "F"]
    assert snos[0] == "2" and "Misadven" in names[0]
    assert "adverse" in names[1]
    assert snos[2] == "E57" and "Other external" in names[2]
    assert snos[4] == "1" and "firearm" in names[4]
    assert snos[6] == "E58" and "Late effects" in names[6]



def test_dataframe_keeps_whooping_and_meningococcal_rows():
    """End-of-block wrap must not drop/shift Whooping + Meningococcal pairs."""
    rows = [
        ["S.No.", "Name of the Disease", "Sex", "Total"],
        [
            "3\n3\n1\n6\n7",
            "Tuberculosis of other organs & miliary\n"
            "Tuberculosis (A18-A19\n"
            "Other bacterial diseases (A20-A49\n"
            "Plague (A20)\n"
            "Whooping cough (A37\n"
            "Meningoocooal infection (A39",
            "M\nF\nM\nF\nM\nF\nM\nF\nM\nF",
            "270\n201\n2095\n1383\n0\n0\n0\n1\n42\n17",
        ],
    ]
    df = dataframe_from_extracted_rows(rows)
    assert df.shape[0] == 10
    names = [_cell(v) for v in df["Name of the Disease"].tolist()]
    totals = [_cell(v) for v in df["Total"].tolist()]
    sexes = [_cell(v) for v in df["Sex"].tolist()]
    assert sexes == ["M", "F", "M", "F", "M", "F", "M", "F", "M", "F"]
    assert "miliary" in names[0]
    assert "A18-A19" in names[1]
    assert "Other bacterial" in names[2]
    assert "Plague" in names[4]
    assert "Whooping" in names[6]
    assert "Meningo" in names[8]
    assert names[9] == ""
    assert totals == ["270", "201", "2095", "1383", "0", "0", "0", "1", "42", "17"]


def test_repair_moves_next_title_off_f_stub():
    from app.services.extraction.pdf.utils.header_utils import repair_sex_pair_next_row_label_bleed

    rows = [
        ["S.No.", "Name of the Disease", "Sex", "Total"],
        ["8", "Septicaemia (A40-A41)", "M", "1955"],
        # Bug: next disease title bled into empty F name cell
        ["", "All other types of bacterial Diseases", "F", "1323"],
        ["9", "(A21-A28,A31-A32,A38,A42-A49)", "M", "10"],
        ["", "", "F", "7"],
    ]
    fixed = repair_sex_pair_next_row_label_bleed(rows, sex_col=2)
    assert _cell(fixed[2][1]) == ""  # F stub cleared
    assert "All other types" in _cell(fixed[3][1])
    assert "(A21" in _cell(fixed[3][1])
    assert _cell(fixed[2][3]) == "1323"  # F measures untouched
    assert _cell(fixed[3][0]) == "9"


def test_dataframe_repairs_f_stub_bleed():
    rows = [
        ["S.No.", "Name of the Disease", "Sex", "<1", "Total"],
        ["8", "Septicaemia (A40-A41)", "M", "656", "1955"],
        ["", "All other types of bacterial Diseases", "F", "359", "1323"],
        ["9", "(A21-A28,A42-A49)", "M", "1", "10"],
        ["", "", "F", "1", "7"],
    ]
    df = dataframe_from_extracted_rows(rows)
    assert df.shape[0] == 4
    names = [_cell(v) for v in df["Name of the Disease"].tolist()]
    assert names[1] == ""
    assert "All other types" in names[2]
    sexes = [_cell(v) for v in df["Sex"].tolist()]
    assert sexes == ["M", "F", "M", "F"]
    assert _cell(df.iloc[1]["Total"]) == "1323"



def test_dataframe_from_extracted_expands_sex_pairs():
    rows = [
        ["S.No.", "Name of the Disease", "Sex", "<1", "Total"],
        [
            "1",
            "Cholera (A00)",
            "M\nF",
            "0\n1",
            "4\n2",
        ],
        [
            "2",
            "Plague (A20)",
            "M\nF",
            "5\n3",
            "10\n7",
        ],
    ]
    df = dataframe_from_extracted_rows(rows)
    assert df.shape[0] == 4
    sexes = [_cell(v) for v in df["Sex"].tolist()]
    assert sexes == ["M", "F", "M", "F"]
    snos = [_cell(v) for v in df["S.No."].tolist()]
    assert snos == ["1", "", "2", ""]
    assert _cell(df.iloc[0]["Total"]) == "4"
    assert _cell(df.iloc[1]["Total"]) == "2"


def test_expand_does_not_split_normal_single_sex_rows():
    rows = [
        ["S.No.", "Name", "Sex", "Total"],
        ["1", "Cholera", "M", "4"],
        ["", "", "F", "2"],
        ["2", "Plague", "M", "10"],
        ["", "", "F", "7"],
    ]
    expanded = expand_collapsed_sex_pair_rows(rows)
    assert len(expanded) == len(rows)
    assert [r[2] for r in expanded[1:]] == ["M", "F", "M", "F"]


def test_wrapped_disease_name_on_f_line_kept():
    rows = [
        ["S.No.", "Name of the Disease", "Sex", "Total"],
        [
            "6",
            "Diarrhoea and gastroenteritis of presume\ninfectious origin (A09)",
            "M\nF",
            "195\n154",
        ],
    ]
    expanded = expand_collapsed_sex_pair_rows(rows)
    assert len(expanded) == 3
    assert "presume" in _cell(expanded[1][1])
    assert "infectious origin" in _cell(expanded[2][1])
    assert expanded[1][2] == "M" and expanded[2][2] == "F"
