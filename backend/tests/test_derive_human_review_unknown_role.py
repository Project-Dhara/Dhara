"""role==unknown alone must not force Review needed (false clearer-role flags)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.confidence_validation.normalize import (
    derive_human_review_needed,
)
from app.services.ingestion.review_tables import enrich_table_for_review


def test_unknown_role_without_column_flag_does_not_need_review():
    table = {
        "title": "Deaths by age and sex",
        "semantic_status": "classified",
        "columns": [
            {"name": "S.No.", "role": "unknown", "human_review_needed": False},
            {"name": "Name of the Disease", "role": "unknown", "human_review_needed": False},
            {"name": "Sex", "role": "dimension", "human_review_needed": False},
            {"name": "<1", "role": "measure", "human_review_needed": False},
        ],
        "rows": [["1", "Plague", "M", "0"]],
        "classification": {},
        "uncertain_cells": [],
    }
    needed, reason = derive_human_review_needed(table)
    assert needed is False
    assert reason is None


def test_clearer_role_flags_are_ignored():
    """ambiguous_column / uncertain_semantic_role no longer drive Review needed."""
    table = {
        "title": "Deaths by age and sex",
        "semantic_status": "classified",
        "columns": [
            {
                "name": "Percentage (Number of Deaths)",
                "role": "unknown",
                "header_group": "Number of Deaths",
                "header_path": ["Number of Deaths", "Percentage"],
                "human_review_needed": True,
                "human_review_reason": "ambiguous_column",
            },
        ],
        "rows": [["63.18"]],
        "classification": {},
        "uncertain_cells": [],
    }
    needed, reason = derive_human_review_needed(table)
    assert needed is False
    assert reason is None


def test_enrich_clears_stale_clearer_role_flag_and_group_qualified_name():
    table = {
        "title": "Number of registered deaths",
        "semantic_status": "classified",
        "human_review_needed": True,
        "human_review_reason": "ambiguous_column",
        "columns": [
            {
                "name": "Percentage",
                "header_group": "Number of Deaths",
                "header_path": ["Number of Deaths", "Percentage"],
                "human_review_needed": False,
            },
            {
                "name": "Percentage (Number of Deaths)",
                "header_group": "Number of Deaths",
                "header_path": ["Number of Deaths", "Percentage"],
                "human_review_needed": True,
                "human_review_reason": "ambiguous_column",
                "input_type": "inputbox",
            },
        ],
        "rows": [["63.18", "36.82"]],
        "classification": {},
        "uncertain_cells": [],
    }
    out = enrich_table_for_review(table, table_id="t1", page_key=1)
    assert out["human_review_needed"] is False
    assert out["human_review_reason"] is None
    assert [c["name"] for c in out["columns"]] == ["Percentage", "Percentage"]
    assert not any(c.get("human_review_needed") for c in out["columns"])
