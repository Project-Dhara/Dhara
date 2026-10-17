"""Gibberish title rejection + AI title-fill review flag."""
from __future__ import annotations

from app.services.extraction.pdf.confidence_validation.title_fill import (
    apply_ai_title_fill,
    ensure_usable_titles_on_pages,
)
from app.services.extraction.pdf.confidence_validation.title_infer import (
    title_looks_like_gibberish,
    title_needs_review,
)
from app.services.extraction.pdf.confidence_validation.normalize import (
    derive_human_review_needed,
)
from app.services.extraction.pdf.confidence_validation.constants import REVIEW_REASONS


def test_title_filled_by_ai_is_standard_reason():
    assert "title_filled_by_ai" in REVIEW_REASONS


def test_gibberish_titles_need_review():
    cols = ["Age", "Male", "Female"]
    assert title_looks_like_gibberish("Sheet: MySheetName")
    assert title_looks_like_gibberish("Source file: demo.xlsx")
    assert title_looks_like_gibberish("\uf8ff\uf8ff\uf8ff")
    assert title_looks_like_gibberish("|||| ··· ###")
    hash_pdf = (
        "cf503361bf9e75ca602b611d5ecda46c24c0c2f805a32b208c17dbb194cbd5a1.pdf"
    )
    assert title_looks_like_gibberish(hash_pdf)
    assert title_looks_like_gibberish(f"{hash_pdf}, {hash_pdf}")
    assert title_needs_review(f"{hash_pdf}, {hash_pdf}", cols)
    assert title_needs_review("Sheet: MySheetName", cols)
    assert title_needs_review("", cols)
    assert title_needs_review("D-14", cols) or title_needs_review("TABLE: D-14", cols)
    assert not title_looks_like_gibberish("Infant Deaths by Age and Sex (Urban)")
    assert not title_looks_like_gibberish("Annual Report 2023.pdf")  # human filename OK
    assert not title_needs_review("Infant Deaths by Age and Sex (Urban)", cols)


def test_ensure_clears_gibberish_without_api_key():
    pages = {
        1: {
            "tables": [
                {
                    "title": "Sheet: Combined",
                    "columns": [{"name": "Age"}, {"name": "Male"}],
                    "rows": [["<7", 10]],
                    "semantic_status": "not_classified",
                }
            ]
        }
    }
    ensure_usable_titles_on_pages(pages, api_key=None)
    t = pages[1]["tables"][0]
    assert t.get("title") in (None, "")
    assert t.get("human_review_needed") is True
    assert t.get("human_review_reason") == "uncertain_title"
    assert not t.get("title_filled_by_ai")


def test_apply_ai_title_fill_sets_review_flag(monkeypatch):
    table = {
        "title": None,
        "columns": [{"name": "Age"}, {"name": "Male"}, {"name": "Female"}],
        "rows": [["< 7 days", 10, 8], ["7-28 days", 5, 4]],
        "sheet": "D-14",
        "semantic_status": "not_classified",
    }

    monkeypatch.setattr(
        "app.services.extraction.pdf.confidence_validation.title_fill.suggest_crisp_table_title_llm",
        lambda *a, **k: "Infant Deaths by Age and Sex",
    )
    assert apply_ai_title_fill(table, api_key="sk-test") is True
    assert table["title"] == "Infant Deaths by Age and Sex"
    assert table["title_filled_by_ai"] is True
    assert table["title_source"] == "llm_from_content"
    assert table["human_review_needed"] is True
    assert table["human_review_reason"] == "title_filled_by_ai"

    needed, reason = derive_human_review_needed(table)
    assert needed is True
    assert reason == "title_filled_by_ai"
