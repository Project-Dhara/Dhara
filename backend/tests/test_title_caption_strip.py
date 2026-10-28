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


def test_prose_above_table_is_not_a_title():
    from app.services.extraction.pdf.confidence_validation.title_infer import (
        infer_title_meta_from_page_text,
        title_is_narrative,
    )

    prose = [
        "Institutional events in case of births accounted for 77.44% and 22.56 % were",
        "statement 2.2. Incase of births, urban areas accounted for 94.81% and share of rural was &",
        "This section is devoted to the brief analysis of the vital events registered under the",
    ]
    for line in prose:
        assert title_is_narrative(line), line
    assert not title_is_narrative("Statement 2.2: Distribution of Vital Events by Sector")
    assert not title_is_narrative(
        "Percentage distribution of live birth by medical attention at birth-2020"
    )

    blocks = [
        {
            "text": "SSttaatteem",
            "x0": 110.5, "y0": 549.5, "x1": 144.8, "y1": 560.0,
        },
        {
            "text": "meenntt  22..22..::  DDiissttrriibbuuttiioonn  ooff  VViittaall  EEvveennttss  bbyy  SSeeccttoorr",
            "x0": 135.0, "y0": 549.5, "x1": 373.5, "y1": 560.0,
        },
        {
            "text": "statement 2.2. Incase of births, urban areas accounted for 94.81% and share of rural was",
            "x0": 110.5, "y0": 491.1, "x1": 400.0, "y1": 502.0,
        },
    ]
    from app.services.extraction.pdf.confidence_validation.title_infer import (
        _merge_same_line_blocks,
    )

    merged = _merge_same_line_blocks(blocks)
    title, source, _banner = infer_title_meta_from_page_text(
        "\n".join(b["text"] for b in merged),
        ["S. No.", "Item", "Male", "Female", "Total"],
        bbox=[110.0, 566.0, 524.0, 701.0],
        page_blocks=merged,
    )
    assert title == "Distribution of Vital Events by Sector"
    assert source == "heuristic_bbox_caption"


def test_rejects_clipped_statement_and_header_fragments():
    from app.services.extraction.pdf.confidence_validation.title_infer import (
        infer_title_meta_from_page_text,
        title_is_misleading,
        title_needs_review,
    )
    from app.services.extraction.pdf.confidence_validation.table_confidence import (
        table_dict_from_df,
    )
    import pandas as pd

    assert title_is_misleading("Statem")
    assert title_is_misleading("AGE NOT")
    assert title_needs_review("Statem")
    assert title_needs_review("AGE NOT", [{"name": "AGE NOT STATED"}])
    assert not title_is_misleading("Statement 2.7: Distribution of deaths by age and sex")
    assert not title_is_misleading("Distribution of infant Deaths")
    assert not title_is_misleading("State")

    df = pd.DataFrame({"AGE NOT STATED": [1], "Total": [2]})
    df.attrs["dhara_table_caption"] = "Statem"
    page = "Statement 2.7: Distribution of deaths by age and sex\n"
    built = table_dict_from_df(df, page_text=page)
    assert built["title"] == "Distribution of deaths by age and sex"
    assert built["title"] != "Statem"

    title, _source, _banner = infer_title_meta_from_page_text(
        "Statem\nAGE NOT\nStatement 2.7: Distribution of deaths by age and sex\n",
        ["AGE NOT STATED", "Total"],
    )
    assert title == "Distribution of deaths by age and sex"


def test_space_separated_number_without_colon():
    assert strip_caption_label_prefix(
        "Statement 4.6 Distribution of infant Deaths"
    ) == "Distribution of infant Deaths"
