"""Tests for stripping Statement/Table labels from auto-accepted titles."""
from __future__ import annotations

from pdf.pdf_table_confidence import strip_caption_label_prefix


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


def test_space_separated_number_without_colon():
    assert strip_caption_label_prefix(
        "Statement 4.6 Distribution of infant Deaths"
    ) == "Distribution of infant Deaths"
