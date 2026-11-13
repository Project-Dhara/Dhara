"""Canonical review-table flattening and batch merge."""
from __future__ import annotations

from app.services.ingestion.review_tables import (
    flatten_job_result_to_review_tables,
    infer_job_source_type,
    merge_file_result_into_batch,
    merge_persisted_with_result_provenance,
    provenance_from_table,
    source_location_label,
)


def test_source_location_labels():
    assert source_location_label({"source_type": "pdf", "page": 3}) == "Page 3"
    assert source_location_label({"source_type": "excel", "sheet": "Districts"}) == "Sheet Districts"
    assert source_location_label({"source_type": "csv"}) == "CSV rows"


def test_flatten_job_result():
    job = {
        "job_id": "j1",
        "filename": "report.pdf",
        "reviews": {"1-0": {"title": "Edited"}},
        "deleted_table_ids": [],
        "result": {
            1: {
                "tables": [
                    {"title": "T1", "source_type": "pdf", "page": 1, "columns": [], "rows": []},
                ],
            },
        },
    }
    tables = flatten_job_result_to_review_tables(job)
    assert len(tables) == 1
    assert tables[0]["table_id"] == "1-0"
    assert tables[0]["title"] == "Edited"
    assert tables[0]["source_location"] == "Page 1"


def test_merge_file_results_namespaced():
    merged = {}
    merge_file_result_into_batch(
        merged,
        0,
        {1: {"tables": [{"title": "A", "page": 1}]}},
        source_filename="a.pdf",
        source_file_id="f0",
        source_type="pdf",
    )
    merge_file_result_into_batch(
        merged,
        1,
        {2: {"tables": [{"title": "B", "sheet": "S1", "page": 2}]}},
        source_filename="b.xlsx",
        source_file_id="f1",
        source_type="excel",
    )
    assert "__f0__1" in merged
    assert merged["__f0__1"]["tables"][0]["source_filename"] == "a.pdf"
    assert merged["__f1__2"]["tables"][0]["source_type"] == "excel"


def test_infer_job_source_type_from_filename():
    assert infer_job_source_type({"filename": "book.xlsx", "source_type": "batch"}) == "excel"
    assert infer_job_source_type({"filename": "rows.csv"}) == "csv"
    assert infer_job_source_type({"filename": "report.pdf"}) == "pdf"
    assert infer_job_source_type({"source_type": "excel"}) == "excel"


def test_merge_persisted_restores_excel_and_pdf_provenance():
    job = {"job_id": "batch1", "filename": "mixed-batch", "source_type": "batch"}
    persisted = [
        {"table_id": "t-pdf", "title": "PDF table", "page": 2, "columns": [], "rows": []},
        {"table_id": "t-xlsx", "title": "Excel table", "page": 1, "columns": [], "rows": []},
    ]
    result_tables = [
        {
            "table_id": "t-pdf",
            "source_type": "pdf",
            "source_filename": "report.pdf",
            "page": 2,
        },
        {
            "table_id": "t-xlsx",
            "source_type": "excel",
            "source_filename": "book.xlsx",
            "sheet": "Districts",
            "page": 1,
        },
    ]
    merged = merge_persisted_with_result_provenance(
        persisted, job, result_tables=result_tables
    )
    by_id = {t["table_id"]: t for t in merged}
    assert by_id["t-pdf"]["source_type"] == "pdf"
    assert by_id["t-pdf"]["source_filename"] == "report.pdf"
    assert by_id["t-pdf"]["source_location"] == "Page 2"
    assert by_id["t-xlsx"]["source_type"] == "excel"
    assert by_id["t-xlsx"]["source_filename"] == "book.xlsx"
    assert by_id["t-xlsx"]["source_location"] == "Sheet Districts"


def test_merge_persisted_honors_deleted_table_ids():
    job = {
        "job_id": "j1",
        "filename": "report.pdf",
        "source_type": "pdf",
        "deleted_table_ids": ["gone"],
    }
    persisted = [
        {"table_id": "gone", "title": "Removed", "page": 1},
        {"table_id": "keep", "title": "Kept", "page": 2},
    ]
    merged = merge_persisted_with_result_provenance(persisted, job, result_tables=[])
    assert [t["table_id"] for t in merged] == ["keep"]
    assert merged[0]["source_type"] == "pdf"


def test_provenance_from_table_keeps_excel_fields():
    prov = provenance_from_table(
        {
            "source_type": "excel",
            "source_filename": "a.xlsx",
            "sheet": "S1",
            "title": "ignored",
        }
    )
    assert prov == {
        "source_type": "excel",
        "source_filename": "a.xlsx",
        "sheet": "S1",
    }
