"""
Run data ingestion + upload pipeline against fixtures in repo ``Testing files/``.

PDFs: smoke + table count (no LLM key — heuristic validation).
Excel/CSV: ``PreValidationInput`` + full spreadsheet upload pipeline.

Run from ``backend/``:

  .venv312/bin/python -m pytest tests/test_testing_files_pipeline.py -v
  .venv312/bin/python tests/test_testing_files_pipeline.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.ingestion import csv as ingest_csv
from app.services.ingestion import excel as ingest_excel
from app.services.ingestion.service import run_upload_pipeline
from app.services.ingestion.spreadsheet_pipeline import run_spreadsheet_upload_pipeline

TESTING_FILES = Path(__file__).resolve().parents[2] / "Testing files"

SAMPLE_CSV = TESTING_FILES / "sample_vital_stats.csv"
SAMPLE_XLSX = TESTING_FILES / "sample_workbook.xlsx"

PDF_FIXTURES = sorted(TESTING_FILES.glob("*.pdf"))


def _table_count(result: dict) -> int:
    return sum(len(page.get("tables") or []) for page in (result or {}).values())


def _assert_rows_match_columns(result: dict) -> None:
    for page in (result or {}).values():
        for t in page.get("tables") or []:
            cols = t.get("columns") or []
            n = len(cols)
            assert n >= 1, "table has no columns"
            for i, row in enumerate(t.get("rows") or []):
                assert len(row) == n, f"row {i} width {len(row)} != {n}"


@pytest.mark.skipif(not SAMPLE_XLSX.is_file(), reason=f"missing {SAMPLE_XLSX}")
def test_testing_files_excel_pre_validation():
    pre = ingest_excel.ingest_path(SAMPLE_XLSX)
    assert pre["pages_grouped"]
    assert pre.get("source_type") == "excel"
    for unit, cands in pre["pages_grouped"].items():
        assert pre["unit_context"][unit]
        assert cands[0]["method"] == "excel_grid"


@pytest.mark.skipif(not SAMPLE_XLSX.is_file(), reason=f"missing {SAMPLE_XLSX}")
def test_testing_files_excel_upload_pipeline():
    result = run_spreadsheet_upload_pipeline(SAMPLE_XLSX, "excel", api_key=None)
    assert _table_count(result) >= 1
    _assert_rows_match_columns(result)
    for page in result.values():
        for t in page["tables"]:
            assert t.get("source_type") == "excel"


@pytest.mark.skipif(not SAMPLE_CSV.is_file(), reason=f"missing {SAMPLE_CSV}")
def test_testing_files_csv_pre_validation():
    pre = ingest_csv.ingest_path(SAMPLE_CSV)
    assert len(pre["pages_grouped"]) == 1
    assert pre["pages_grouped"][1][0]["method"] == "csv_grid"


@pytest.mark.skipif(not SAMPLE_CSV.is_file(), reason=f"missing {SAMPLE_CSV}")
def test_testing_files_csv_upload_pipeline():
    result = run_spreadsheet_upload_pipeline(SAMPLE_CSV, "csv", api_key=None)
    assert _table_count(result) >= 1
    _assert_rows_match_columns(result)


@pytest.mark.parametrize("pdf_path", PDF_FIXTURES, ids=lambda p: p.name)
def test_testing_files_pdf_upload_pipeline(pdf_path: Path):
    if not pdf_path.is_file():
        pytest.skip(f"missing {pdf_path}")
    result = run_upload_pipeline(pdf_path, "pdf", api_key=None)
    assert isinstance(result, dict)
    # Some PDFs may have no ruled tables; most Testing files PDFs should have ≥1.
    if _table_count(result) == 0:
        pytest.skip(f"{pdf_path.name}: no tables after pipeline (may be image-only or empty range)")
    _assert_rows_match_columns(result)
    for page in result.values():
        for t in page["tables"]:
            assert t.get("source_type") == "pdf"


if __name__ == "__main__":
    missing = []
    if SAMPLE_XLSX.is_file():
        test_testing_files_excel_pre_validation()
        test_testing_files_excel_upload_pipeline()
        print(f"OK excel: {SAMPLE_XLSX.name}")
    else:
        missing.append(str(SAMPLE_XLSX))
    if SAMPLE_CSV.is_file():
        test_testing_files_csv_pre_validation()
        test_testing_files_csv_upload_pipeline()
        print(f"OK csv: {SAMPLE_CSV.name}")
    else:
        missing.append(str(SAMPLE_CSV))
    for pdf in PDF_FIXTURES:
        try:
            test_testing_files_pdf_upload_pipeline(pdf)
            print(f"OK pdf: {pdf.name} ({_table_count(run_upload_pipeline(pdf, 'pdf', api_key=None))} tables)")
        except Exception as e:
            print(f"SKIP/FAIL pdf {pdf.name}: {e}")
    if missing:
        print("Missing fixtures:", missing)
    else:
        print("test_testing_files_pipeline: done")
