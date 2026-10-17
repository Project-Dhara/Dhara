"""Irrigated / Un Irrigated / Total appendix tables keep proper multi-level headers.

PyMuPDF parks Name of Crop / Season / Appendix in the grid and often isolates
``District`` on its own row. Those metadata cells must not become L1 parents,
and District must not be dropped or swallowed into the body as a value row.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.utils.header_utils import dataframe_from_extracted_rows


def _irrigation_appendix_lines_rows():
    """``lines`` extract: District sits alone under the leaf measure row."""
    empty = [None] * 16
    return [
        ["ANNEXURE -5"] + empty,
        ["DISTRICTWISE AREA, PRODUCTIVITY AND PRODUCTION OF RICE"] + empty,
        [
            "Name of Crop:Paddy(Rice)",
            None,
            None,
            None,
            None,
            None,
            "Season :-Autumn (Kharif)",
            None,
            None,
            None,
            None,
            "Appendix :E1(1)",
            None,
            None,
            None,
            None,
            None,
        ],
        [
            "Sl. No",
            None,
            "Irrigated",
            None,
            None,
            None,
            None,
            "Un Irrigated",
            None,
            None,
            None,
            None,
            "Total",
            None,
            None,
            None,
            None,
        ],
        [
            None,
            None,
            "No.of Experiments",
            "Productivity(Kg/Ha)-Rice",
            "Area(Ha)",
            "Sampling Error",
            "Production of Rice in Tonnes",
            "No.of Experiments",
            "Productivity(Kg/Ha)-Rice",
            "Area(Ha)",
            "Sampling Error",
            "Production of Rice in Tonnes",
            "No.of Experiments",
            "Productivity(Kg/Ha)-Rice",
            "Area(Ha)",
            "Sampling Error",
            "Production of Rice in Tonnes",
        ],
        [None, "District"] + [None] * 15,
        [str(i) for i in range(1, 18)],
        ["1", "Thiruvananthapuram", "152", "2579", "681.93", "135", "175.9",
         "0", "0", "0", "0", "0", "152", "2579", "681.93", "135", "175.9"],
        ["2", "Kollam", "11", "1958", "4.72", "185", "9.2",
         "0", "0", "0", "0", "0", "11", "1958", "4.72", "185", "9.2"],
    ]


def _irrigation_appendix_strict_rows():
    """``lines_strict`` extract: Sl.No and District share the group row."""
    empty = [None] * 16
    return [
        ["ANNEXURE -6"] + empty,
        ["DISTRICTWISE AREA, PRODUCTIVITY AND PRODUCTION OF RICE"] + empty,
        [
            "Name of Crop:Paddy(Rice)",
            None,
            None,
            None,
            None,
            None,
            "Season :-Autumn (Kharif)",
            None,
            None,
            None,
            None,
            "Appendix :E1(2)",
            None,
            None,
            None,
            None,
            None,
        ],
        [
            "Sl.No",
            "District",
            "Irrigated",
            None,
            None,
            None,
            None,
            "Un Irrigated",
            None,
            None,
            None,
            None,
            "Total",
            None,
            None,
            None,
            None,
        ],
        [
            None,
            None,
            "No.of Exp",
            "Productivity(Kg/Ha)-Rice",
            "Area(Ha)",
            "Sampling Error",
            "Production of Rice in Tonnes",
            "No.of Exp",
            "Productivity(Kg/Ha)-Rice",
            "Area(Ha)",
            "Sampling Error",
            "Production of Rice in Tonnes",
            "No.of Exp",
            "Productivity(Kg/Ha)-Rice",
            "Area(Ha)",
            "Sampling Error",
            "Production of Rice in Tonnes",
        ],
        [str(i) for i in range(1, 18)],
        ["1", "Thiruvananthapuram", "2", "2000", "0.13", "0", "0.260",
         "0", "0", "0", "0", "0", "2", "2000", "0.13", "0", "0.260"],
        ["2", "Kollam", "0", "0", "0", "0", "0",
         "0", "0", "0", "0", "0", "0", "0", "0", "0", "0"],
    ]


def _paths(df):
    meta = list(df.attrs.get("dhara_column_meta") or [])
    return [list(m.get("header_path") or []) for m in meta]


def test_lines_district_row_becomes_column_not_body():
    df = dataframe_from_extracted_rows(_irrigation_appendix_lines_rows())
    assert df.shape[1] == 17
    paths = _paths(df)
    assert paths[0] == ["Sl. No"]
    assert paths[1] == ["District"]
    assert paths[2:7] == [
        ["Irrigated", "No.of Experiments"],
        ["Irrigated", "Productivity(Kg/Ha)-Rice"],
        ["Irrigated", "Area(Ha)"],
        ["Irrigated", "Sampling Error"],
        ["Irrigated", "Production of Rice in Tonnes"],
    ]
    assert paths[7][0] == "Un Irrigated"
    assert paths[12][0] == "Total"
    # Metadata must not appear as parents.
    flat = [p for path in paths for p in path]
    assert not any("name of crop" in p.lower() for p in flat)
    assert not any(p.lower().startswith("season") for p in flat)
    assert not any(p.lower().startswith("appendix") for p in flat)
    districts = [str(v) for v in df.iloc[:, 1].tolist()]
    assert "Thiruvananthapuram" in districts
    assert "Kollam" in districts


def test_strict_first_district_not_swallowed_into_header():
    df = dataframe_from_extracted_rows(_irrigation_appendix_strict_rows())
    assert df.shape[1] == 17
    paths = _paths(df)
    assert paths[0] == ["Sl.No"]
    assert paths[1] == ["District"]
    assert paths[2] == ["Irrigated", "No.of Exp"]
    assert paths[6] == ["Irrigated", "Production of Rice in Tonnes"]
    # First real district row must remain body data.
    districts = [str(v) for v in df.iloc[:, 1].tolist()]
    assert "Thiruvananthapuram" in districts
    assert "Kollam" in districts
    assert "Thiruvananthapuram" not in [p[-1] for p in paths]
