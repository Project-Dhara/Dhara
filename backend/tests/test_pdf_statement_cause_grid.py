"""Statement-style Cause of Death grids: keep lines_strict, coalesce phantoms."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.utils.header_utils import (
    coalesce_phantom_grid_columns,
    dataframe_from_extracted_rows,
    fold_label_wrap_continuation_rows,
)
from app.services.extraction.pdf.confidence_validation.table_confidence import looks_like_chart_candidate


# lines_strict-shaped grid (6 cols) — already correct.
STRICT_GRID = [
    ["Sl. No.", "Cause of Death & ICD-10 Coding", "No. of Infant Deaths", None, None, "% to total\nMCCD\nInfant\nDeaths"],
    [None, None, "Male", "Female", "Total", None],
    ["1", "All other conditions originating in the\nperinatal period (P00-P04,P08,P29-\nP54,P56-P57,P60-P96)", "1490", "949", "2439", "29.62"],
    ["2", "Hypoxia, birth asphyxia and other\nrespiratory conditions (P20-P28)", "627", "411", "1038", "12.61"],
    ["3", "Septicaemia (A40-A41)", "442", "276", "718", "8.72"],
    ["4", "Slow fetal growth, fetal malnutrition and\nimmaturity (P05-P07)", "401", "229", "630", "7.65"],
    ["5", "Pneumonia (J12-J18)", "203", "135", "338", "4.11"],
    ["Total (1 to 14)", None, "3790", "2366", "6156", "74.77"],
]


# lines-strategy phantom grid: Cause split across 3 cols, Male/Female/Total
# each repeated with empty interstitial columns, plus wrap continuation rows.
PHANTOM_GRID = [
    [
        "Sl. No.",
        "Cause of Death & ICD-10 Coding",
        None,
        None,
        "No. of Infant Deaths",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        "% to total\nMCCD\nInfant\nDeaths",
    ],
    [None, None, None, None, "", "Male", "", "", "Female", "", "", "Total", "", None],
    ["1", "All other conditions originating in the\nperinatal period (P00-P04,P08,P29-\nP54,P56-P57,P60-P96)", None, None, "1490", None, None, "949", None, None, "2439", None, None, "29.62"],
    ["2", "Hypoxia, birth asphyxia and other\nrespiratory conditions (P20-P28)", None, None, "627", None, None, "411", None, None, "1038", None, None, "12.61"],
    ["3", "Septicaemia (A40-A41)", None, None, "442", None, None, "276", None, None, "718", None, None, "8.72"],
    ["4", "", "Slow fetal growth, fetal malnutrition and", "", "401", None, None, "229", None, None, "630", None, None, "7.65"],
    [None, None, "immaturity (P05-P07)", None, None, None, None, None, None, None, None, None, None, None],
    ["5", "Pneumonia (J12-J18)", "Pneumonia (J12-J18)", None, "203", None, None, "135", None, None, "338", None, None, "4.11"],
    ["6", "", "Congenital malformations of the", "", "193", None, None, "97", None, None, "290", None, None, "3.52"],
    [None, None, "circulatory sytem (Q20-Q28)", None, None, None, None, None, None, None, None, None, None, None],
    ["7", "Shock, not elsewhere classified (R57)", "Shock, not elsewhere classified (R57)", None, "109", None, None, "72", None, None, "181", None, None, "2.20"],
]


def test_compact_cause_table_not_chart_despite_fat_rects():
    df = dataframe_from_extracted_rows(STRICT_GRID)

    class _Rect:
        def __init__(self, x0, y0, x1, y1):
            self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
            self.width = x1 - x0
            self.height = y1 - y0

    class _Page:
        def get_drawings(self):
            # Pretend many filled highlight rects inside the table bbox.
            return [
                {"fill": (1, 1, 0), "rect": _Rect(100 + i, 100 + i, 140 + i, 130 + i)}
                for i in range(20)
            ]

        def get_text(self, *args, **kwargs):
            return "Statement 4.8: Distribution of major causes of infant deaths"

    is_chart, reason = looks_like_chart_candidate(
        df,
        page=_Page(),
        bbox=[90.0, 90.0, 520.0, 620.0],
        page_text="Statement 4.8: Distribution of major causes of infant deaths",
    )
    assert not is_chart, reason
    assert reason == ""


def test_lines_strict_shape_stays_clean():
    df = dataframe_from_extracted_rows(STRICT_GRID)
    assert df.shape[1] == 6
    assert "Cause of Death & ICD-10 Coding" in list(df.columns)
    assert "Male" in list(df.columns)
    causes = [str(v) for v in df.iloc[:, 1].tolist() if str(v) not in ("", "None", "nan")]
    assert causes[0].startswith("All other conditions")
    assert "perinatal period" in causes[0]
    assert causes[2] == "Septicaemia (A40-A41)"


def test_phantom_columns_coalesce_and_wraps_fold():
    df = dataframe_from_extracted_rows(PHANTOM_GRID)
    cols = list(df.columns)
    # One Cause column, one Male/Female/Total — not Cause (2)/(3).
    assert sum(1 for c in cols if "Cause of Death" in str(c)) == 1
    assert sum(1 for c in cols if str(c).startswith("Male")) == 1
    assert sum(1 for c in cols if str(c).startswith("Female")) == 1
    assert sum(1 for c in cols if str(c).startswith("Total")) == 1

    cause_col = next(c for c in cols if "Cause of Death" in str(c))
    causes = [str(v).strip() for v in df[cause_col].tolist()]
    # Wrap continuation rows folded into parent.
    assert any("immaturity (P05-P07)" in c and "Slow fetal growth" in c for c in causes)
    assert any("circulatory sytem" in c and "Congenital malformations" in c for c in causes)
    # Duplicate Pneumonia / Shock collapsed to one cell.
    pneumonia = [c for c in causes if "Pneumonia" in c]
    assert len(pneumonia) == 1
    assert pneumonia[0] == "Pneumonia (J12-J18)"

    male_col = next(c for c in cols if str(c) == "Male" or str(c).startswith("Male"))
    males = [str(v).strip() for v in df[male_col].tolist() if str(v).strip() not in ("", "None", "nan")]
    assert males[0] == "1490"
    assert "203" in males
    female_col = next(c for c in cols if str(c) == "Female" or str(c).startswith("Female"))
    females = [str(v).strip() for v in df[female_col].tolist() if str(v).strip() not in ("", "None", "nan")]
    assert females[0] == "949"
    # Empty spanning parent column should be gone after the shift+drop.
    assert "No. of Infant Deaths" not in cols
