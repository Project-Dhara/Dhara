"""Column-number strips (1..N) must appear; real birth-order data stays intact."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.confidence_validation.alignment import _row_is_column_index_strip
from app.services.extraction.pdf.confidence_validation.stamp import (
    _restore_missing_data_rows_from_candidate,
)
from app.services.extraction.pdf.confidence_validation.table_confidence import table_dict_from_df
from app.services.extraction.pdf.utils.header_utils import dataframe_from_extracted_rows


def _rural_birth_order_raw():
    """Exact pymupdf lines_strict shape: headers + bare index + collapsed body + TOTAL."""
    return [
        [
            "BIRTH\nORDER",
            "AGE OF MOTHERS (IN YEARS)",
            None, None, None, None, None, None, None, None, None, None,
        ],
        [
            None,
            "0-14", "15-19", "20-24", "25-29", "30-34", "35-39",
            "40-44", "45-49", ">=50", "AGE NOT\nSTATED", "ALL\nAGES",
        ],
        ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"],
        [
            "1\n2\n3\n4\n5\n6\n7\n8\n9\n10\nabove10\nnot stated",
            "0\n0\n0\n0\n0\n0\n0\n0\n0\n0\n0\n0",
            "633\n33\n1\n0\n0\n0\n0\n0\n0\n0\n0\n8",
            "6322\n2946\n491\n86\n16\n0\n0\n0\n0\n0\n0\n67",
            "2545\n4138\n2142\n504\n63\n12\n1\n3\n0\n0\n0\n50",
            "216\n665\n886\n646\n143\n24\n5\n5\n0\n0\n0\n62",
            "62\n67\n185\n153\n118\n46\n13\n5\n0\n1\n0\n20",
            "14\n13\n12\n24\n40\n18\n7\n6\n0\n0\n0\n4",
            "0\n1\n3\n3\n1\n5\n1\n1\n0\n0\n0\n2",
            "0\n0\n0\n0\n0\n0\n0\n0\n0\n0\n0\n0",
            "109\n5\n8\n1\n0\n0\n0\n0\n0\n0\n0\n4340",
            "9901\n7868\n3728\n1417\n381\n105\n27\n20\n0\n1\n0\n4553",
        ],
        ["TOTAL", "0", "675", "9928", "9458", "2652", "670", "138", "17", "0", "4463", "28001"],
    ]


def _literacy_raw():
    """Birth order × levels of education — 8-column index strip 1..8."""
    return [
        [
            "BIRTH\nORDER",
            "LEVELS OF EDUCATION OF MOTHER",
            None, None, None, None, None, None,
        ],
        [
            None,
            "Illiterate",
            "Below Primary",
            "Primary but Below Matric",
            "Matric but below Graduate",
            "Graduate and above",
            "Not Stated",
            "TOTAL",
        ],
        ["1", "2", "3", "4", "5", "6", "7", "8"],
        [
            "1\n2\n3\n4\n5\n6\n7\n8\n9\n10\nabove10\nNot stated",
            "272\n263\n139\n59\n12\n3\n1\n1\n0\n0\n0\n4",
            "60\n34\n36\n3\n1\n0\n0\n0\n0\n0\n0\n2",
            "197\n213\n130\n25\n6\n1\n0\n0\n0\n0\n0\n9",
            "573\n603\n209\n29\n3\n1\n0\n0\n0\n0\n0\n4",
            "439\n343\n55\n6\n1\n0\n0\n0\n0\n0\n0\n0",
            "27\n36\n11\n2\n0\n1\n1\n1\n0\n0\n0\n2",
            "1568\n1492\n580\n124\n23\n6\n2\n2\n0\n0\n0\n21",
        ],
        ["TOTAL", "491", "63", "390", "1796", "1010", "68", "3818"],
    ]


def test_column_number_strip_kept_as_first_body_row():
    df = dataframe_from_extracted_rows(_literacy_raw())
    assert list(df.columns)[1] == "Illiterate"  # not renamed to "2"
    assert list(df.columns)[-1] == "TOTAL"
    # First body row is the 1..8 reference strip.
    assert [str(v) for v in df.iloc[0].tolist()] == [str(i) for i in range(1, 9)]
    # Next row is real birth-order 1 data.
    assert str(df.iloc[1, 0]) == "1"
    assert str(df.iloc[1, -1]) == "1568"
    assert str(df.iloc[-1, 0]).upper() == "TOTAL"


def test_rural_birth_order_keeps_index_then_first_data_row():
    df = dataframe_from_extracted_rows(_rural_birth_order_raw())
    assert df.shape[0] == 14  # index + 12 body + TOTAL? 1 index + 12 collapsed + TOTAL = 14
    assert [str(v) for v in df.iloc[0].tolist()] == [str(i) for i in range(1, 13)]
    assert str(df.iloc[1, 0]) == "1"
    assert str(df.iloc[1, -1]) == "9901"
    assert str(df.iloc[2, -1]) == "7868"
    assert str(df.iloc[-1, 0]).upper() == "TOTAL"
    assert str(df.iloc[-1, -1]) == "28001"


def test_bare_index_strip_detected():
    assert _row_is_column_index_strip(["1", "2", "3", "4", "5", "6", "7", "8"])
    assert _row_is_column_index_strip(["(1)", "(2)", "(3)", "(4)"])
    assert not _row_is_column_index_strip(
        ["1", "0", "633", "6322", "2545", "216", "62", "14", "0", "0", "109", "9901"]
    )


def test_restore_reinserts_dropped_column_number_strip():
    df = dataframe_from_extracted_rows(_literacy_raw())
    table = table_dict_from_df(df)
    # LLM dropped the 1..8 strip; kept data from birth-order 1 onward.
    table["rows"] = [r for r in table["rows"] if not _row_is_column_index_strip(r)]
    assert not _row_is_column_index_strip(table["rows"][0])
    _restore_missing_data_rows_from_candidate(table, df)
    assert _row_is_column_index_strip(table["rows"][0])
    assert [str(v) for v in table["rows"][0]] == [str(i) for i in range(1, 9)]
    assert str(table["rows"][1][0]) == "1"
    assert str(table["rows"][1][-1]) == "1568"
