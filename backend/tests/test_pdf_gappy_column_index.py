"""Gappy 1..N index strips and sparse wide grids must not auto-accept."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.confidence_validation.table_confidence import (
    _leading_column_index_is_gappy,
    _structural_bucket_for_df,
)


def test_dense_index_strip_is_not_gappy():
    df = pd.DataFrame(
        [list(map(str, range(1, 19)))]
        + [
            [str(i), f"District{i}"] + [f"{1000 + j}.22" for j in range(16)]
            for i in range(1, 8)
        ],
        columns=[f"C{i}" for i in range(18)],
    )
    assert not _leading_column_index_is_gappy(df)
    bucket, reason, info = _structural_bucket_for_df(df)
    assert bucket == "high", (bucket, reason, info)
    assert not info.get("gappy_column_index")


def test_gappy_index_strip_forces_llm():
    # 1..18 with empty holes — classic bisected land-use lines extract.
    index = []
    n = 1
    for i in range(29):
        if i % 2 == 0 and n <= 18:
            index.append(str(n))
            n += 1
        else:
            index.append(None)
    df = pd.DataFrame(
        [index]
        + [["1", "Thiruvananthapuram"] + [None if j % 2 else "1.0" for j in range(27)]],
        columns=[f"C{i}" for i in range(29)],
    )
    assert _leading_column_index_is_gappy(df)
    bucket, reason, info = _structural_bucket_for_df(df)
    assert bucket == "llm", (bucket, reason, info)
    assert "gappy" in reason or "empty columns" in reason
