"""Cause-of-Death style wraps must fold into the parent row, not shift measures."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.utils.header_utils import (
    _assign_label_parts_to_n,
    _looks_like_name_continuation,
    dataframe_from_extracted_rows,
)


def test_continuation_detects_to_elsewhere_and_such_as():
    assert _looks_like_name_continuation(
        "Duodenum", prev="Ulcer of Stomach and"
    )
    assert _looks_like_name_continuation(
        "Pregnancy", prev="Complication related to"
    )
    assert _looks_like_name_continuation(
        "Classified", prev="Others Not elsewhere"
    )
    assert _looks_like_name_continuation(
        "Slow Growth of Foetus and",
        prev="Condition such as Birth Injuries",
    )
    assert not _looks_like_name_continuation(
        "Appendicitis", prev="Ulcer of Stomach and Duodenum"
    )


def test_assign_label_parts_folds_wraps_to_measure_count():
    parts = [
        "Ulcer of Stomach and",
        "Duodenum",
        "Appendicitis",
        "Syphillis",
        "Abortion",
        "Complication related to",
        "Pregnancy",
        "Condition such as Birth Injuries",
        "Slow Growth of Foetus and",
        "Prematuring originating in the",
        "Perinantal Period",
        "Cerobrovascular(Paralysis)",
        "Senillity",
        "Others Not elsewhere",
        "Classified",
        "Bites",
        "Accidental burns",
        "Falls and Drowning",
        "Accidental poisoning",
        "Transport accidents",
        "Other Accidents",
        "Sucide",
        "Homicide",
    ]
    out = _assign_label_parts_to_n(parts, 17)
    assert len(out) == 17
    assert out[0] == "Ulcer of Stomach and Duodenum"
    assert out[4] == "Complication related to Pregnancy"
    assert out[5] and "Birth Injuries" in out[5] and "Perinantal Period" in out[5]
    assert out[8] == "Others Not elsewhere Classified"
    assert out[-1] == "Homicide"


def test_dataframe_folds_cause_of_death_wraps_without_sex_column():
    """Region×Male/Female headers — no Sex column — still fold name wraps."""
    # Single header row + stacked body (mirrors lines_strict after leaf detect).
    causes = "\n".join([
        "Ulcer of Stomach and",
        "Duodenum",
        "Appendicitis",
        "Complication related to",
        "Pregnancy",
        "Others Not elsewhere",
        "Classified",
        "Bites",
    ])
    snos = "\n".join(["24", "25", "28", "32", "33"])
    males = "\n".join(["5", "2", "0", "29825", "3"])
    females = "\n".join(["3", "0", "18", "19004", "4"])
    rows = [
        ["S.No.", "Cause of Death", "MALE", "FEMALE", "MALE", "FEMALE"],
        [snos, causes, males, females, males, females],
    ]
    df = dataframe_from_extracted_rows(rows)
    assert df.shape[0] == 5, (df.shape, df.values.tolist())
    causes_out = [str(v) for v in df.iloc[:, 1].tolist()]
    assert causes_out[0] == "Ulcer of Stomach and Duodenum"
    assert causes_out[1] == "Appendicitis"
    assert causes_out[2] == "Complication related to Pregnancy"
    assert causes_out[3] == "Others Not elsewhere Classified"
    assert causes_out[4] == "Bites"
    # Measures stay aligned with the parent disease (not shifted by wraps).
    male_col = [str(v).strip() for v in df.iloc[:, 2].tolist()]
    assert male_col == ["5", "2", "0", "29825", "3"]
