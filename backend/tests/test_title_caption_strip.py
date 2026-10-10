"""Tests for stripping Statement/Table labels from auto-accepted titles."""
from __future__ import annotations

from app.services.extraction.pdf.confidence_validation.table_confidence import strip_caption_label_prefix


def test_strip_statement_prefix():
    assert strip_caption_label_prefix(
        "Statement 4.6: Distribution of infant Deaths"
    ) == "Distribution of infant Deaths"
    assert strip_caption_label_prefix(
        "Statement 4.5: Distribution of Deaths by Age group and sex"
    ) == "Distribution of Deaths by Age group and sex"


def test_strip_table_prefix():
    assert strip_caption_label_prefix("TABLE 2.1: Live births by district") == "Live births by district"
    assert strip_caption_label_prefix("Table 3.2 — Infant mortality rate") == "Infant mortality rate"


def test_strip_annex_and_schedule():
    assert strip_caption_label_prefix("Annexure A: Key indicators") == "Key indicators"
    assert strip_caption_label_prefix("Schedule 1.1: Definitions") == "Definitions"


def test_keeps_plain_descriptive_title():
    assert strip_caption_label_prefix("Distribution of infant Deaths") == "Distribution of infant Deaths"


def test_collapse_doubled_pdf_glyph_titles():
    from app.services.extraction.pdf.confidence_validation.table_confidence import collapse_doubled_pdf_glyphs

    assert (
        collapse_doubled_pdf_glyphs(
            "Maaiinn VViittaall IInnddiiccaattoorrss ooff DDeellhhii aanndd IInnddiiaa"
        )
        == "Main Vital Indicators of Delhi and India"
    )
    assert collapse_doubled_pdf_glyphs("Maaiinn RReelliiggiioonn") == "Main Religion"
    assert collapse_doubled_pdf_glyphs("SSttaatteem") == "Statem"
    # Normal titles must not be damaged
    assert collapse_doubled_pdf_glyphs("Distribution of infant Deaths") == "Distribution of infant Deaths"
    assert collapse_doubled_pdf_glyphs("MISSISSIPPI") == "MISSISSIPPI"
    assert collapse_doubled_pdf_glyphs("All Ages") == "All Ages"


def test_strip_also_collapses_doubled_glyphs():
    assert (
        strip_caption_label_prefix(
            "Maaiinn VViittaall IInnddiiccaattoorrss ooff DDeellhhii aanndd IInnddiiaa"
        )
        == "Main Vital Indicators of Delhi and India"
    )


def test_space_separated_number_without_colon():
    assert strip_caption_label_prefix(
        "Statement 4.6 Distribution of infant Deaths"
    ) == "Distribution of infant Deaths"
