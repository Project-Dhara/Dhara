"""Marriage-registration leading banners appear above leaf columns via header_path."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.utils.dataframe_build import (
    dataframe_from_extracted_rows,
)


def _header():
    return [
        "S.No.",
        "Marriage Act",
        "Total No. of application Received",
        "No. of Registration Done",
    ]


def _acts():
    return [
        ["1", "Anand Marriage Act", "40", "31"],
        ["2", "Delhi Order 2014", "861", "766"],
        ["3", "Hindu Marriage Act", "968", "613"],
        ["4", "Special Marriage Act", "81", "30"],
        ["", "Total", "1950", "1440"],
    ]


def _header_path_text(df) -> str:
    meta = list(getattr(df, "attrs", {}).get("dhara_column_meta") or [])
    parts: list[str] = []
    for cm in meta:
        for p in cm.get("header_path") or []:
            parts.append(str(p))
    return " ".join(parts)


def test_all_districts_block_keeps_title_date_district_in_header_path():
    rows = [
        ["Act Wise Marriage Registration Report", None, None, None],
        ["From  01.10.2026       TO     31.10.2026", None, None, None],
        ["All Districts", None, None, None],
        _header(),
        *_acts(),
    ]
    df = dataframe_from_extracted_rows(rows)
    assert list(df.columns)[:2] == ["S.No.", "Marriage Act"]
    path_text = _header_path_text(df)
    assert "Act Wise Marriage Registration Report" in path_text
    assert "01.10.2026" in path_text
    assert "All Districts" in path_text
    body_text = " ".join(
        str(v) for row in df.values.tolist() for v in row if v is not None
    )
    assert "Hindu Marriage Act" in body_text
    # Banners must not appear as body rows under the leaf headers.
    assert "Act Wise Marriage Registration Report" not in body_text
    assert "01.10.2026" not in body_text
    assert "All Districts" not in body_text
    first = [str(v) for v in df.values.tolist()[0] if v is not None]
    assert first[:2] == ["1", "Anand Marriage Act"]
    title = str(df.attrs.get("dhara_table_caption") or "")
    assert "Act Wise Marriage Registration Report" in title
    # All Districts is not appended to the title.
    assert "—" not in title or "All Districts" not in title


def test_west_block_keeps_date_and_district_in_header_path():
    rows = [
        ["Act Wise Marriage Registration Report", None, None, None],
        ["From  01.10.2026       TO     31.10.2026", None, None, None],
        ["West", None, None, None],
        _header(),
        ["1", "Anand Marriage Act", "6", "5"],
        ["2", "Delhi Order 2014", "48", "42"],
        ["", "Total", "71", "50"],
    ]
    df = dataframe_from_extracted_rows(rows)
    path_text = _header_path_text(df)
    assert "01.10.2026" in path_text
    assert "West" in path_text
    body_text = " ".join(
        str(v) for row in df.values.tolist() for v in row if v is not None
    )
    assert "01.10.2026" not in body_text
    # District label must not be a body row (acts still mention Marriage Act).
    assert df.values.tolist()[0][1] == "Anand Marriage Act"
    title = str(df.attrs.get("dhara_table_caption") or "")
    assert "Act Wise Marriage Registration Report" in title
    assert "West" in title


def test_unrelated_caption_banner_not_reinjected():
    """Ordinary tables keep today's Preview: leading caption stays out of body."""
    rows = [
        ["Annual Statistical Abstract of Crop Yields by Season", None, None, None],
        ["Crop", "Area", "Production", "Yield"],
        ["Wheat", "10", "20", "2"],
        ["Rice", "5", "15", "3"],
    ]
    df = dataframe_from_extracted_rows(rows)
    body_text = " ".join(
        str(v) for row in df.values.tolist() for v in row if v is not None
    )
    assert "Annual Statistical Abstract" not in body_text
    assert "Wheat" in body_text
