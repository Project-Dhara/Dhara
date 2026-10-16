"""Upload-path LLM speedups: reconstruct-only prompts + header/full tiers."""
from __future__ import annotations

import pandas as pd

from app.services.llm_prompts import (
    TASK_B_CLASSIFICATION_RULES,
    pdf_batch_validation_user_prompt,
    pdf_single_page_validation_user_prompt,
)
from app.services.extraction.pdf.confidence_validation.confidence_split import (
    _llm_tier_for_reason,
)
from app.services.extraction.pdf.confidence_validation.normalize import (
    derive_human_review_needed,
)
from app.services.extraction.pdf.confidence_validation.stamp import (
    _hydrate_rows_from_candidate_for_header_fix,
    _stamp_llm_metadata,
)


def test_upload_prompts_omit_task_b():
    single = pdf_single_page_validation_user_prompt(
        page_num=1,
        raw_page_text="text",
        candidates_block="grid",
        count_hint="",
        mode="full",
    )
    batch = pdf_batch_validation_user_prompt(
        page_numbers=[1, 2],
        page_sections_block="=== PAGE 1 ===",
        mode="full",
    )
    assert TASK_B_CLASSIFICATION_RULES not in single
    assert TASK_B_CLASSIFICATION_RULES not in batch
    assert "Do NOT classify semantics" in single
    assert "Do NOT classify semantics" in batch


def test_header_prompt_asks_for_empty_rows():
    prompt = pdf_single_page_validation_user_prompt(
        page_num=3,
        raw_page_text="caption",
        candidates_block="cand",
        count_hint="",
        mode="header",
    )
    assert "rows" in prompt.lower()
    assert "ruled-border" in prompt.lower() or "ruled" in prompt.lower()


def test_llm_tier_for_reason():
    assert (
        _llm_tier_for_reason(
            "structural issue (multiline/duplicate header or header glued into first row)"
        )
        == "header"
    )
    assert (
        _llm_tier_for_reason(
            "placeholder column header (blank in the raw table) -- real header likely lives outside the ruled region"
        )
        == "header"
    )
    assert (
        _llm_tier_for_reason("rotated or stacked column headers still need cleanup")
        == "header"
    )
    assert _llm_tier_for_reason("near-empty or sparse lines_strict candidate") == "full"
    assert (
        _llm_tier_for_reason(
            "column(s) with a murky numeric/text mix, likely misaligned cells"
        )
        == "full"
    )


def test_reconstruct_only_does_not_flag_unknown_roles():
    needed, reason = derive_human_review_needed(
        {
            "title": "Live Births by Birth Order and Weight (Urban)",
            "columns": [
                {"name": "Order", "role": "unknown"},
                {"name": "Male", "role": "unknown"},
            ],
            "rows": [["1", "10"]],
            "uncertain_cells": [],
            "semantic_status": "not_classified",
            "classification": {},
        }
    )
    assert needed is False
    assert reason is None


def test_header_fix_hydrates_rows_from_candidate():
    df = pd.DataFrame(
        [["1991", "100"], ["1992", "110"]],
        columns=["Col_1", "Col_2"],
    )
    table = {
        "title": "Demo",
        "columns": [{"name": "Year"}, {"name": "Births"}],
        "rows": [],
        "notes": [],
        "uncertain_cells": [],
    }
    out = _hydrate_rows_from_candidate_for_header_fix(
        table,
        [{"method": "pymupdf_lines_strict", "df": df, "bbox": [0, 0, 10, 10]}],
        None,
    )
    assert len(out["rows"]) == 2
    assert out["rows"][0][0] == "1991"
    assert out["columns"][0]["name"] == "Year"


def test_stamp_header_mode_marks_not_classified():
    df = pd.DataFrame([["a", "1"]], columns=["X", "Y"])
    stamped = _stamp_llm_metadata(
        {
            "tables": [
                {
                    "title": "Some Descriptive Table Title Here",
                    "columns": [{"name": "Name"}, {"name": "Value"}],
                    "rows": [],
                }
            ]
        },
        page_num=1,
        candidates=[{"method": "pymupdf_lines_strict", "df": df, "bbox": [0, 0, 5, 5]}],
        page_text="Some Descriptive Table Title Here",
        llm_mode="header",
    )
    t = stamped["tables"][0]
    assert t["semantic_status"] == "not_classified"
    assert (t.get("extraction") or {}).get("confidence") == "llm_header_fix"
    assert len(t.get("rows") or []) >= 1
