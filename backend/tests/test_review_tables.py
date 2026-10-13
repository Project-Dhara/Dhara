"""Canonical review-table flattening and batch merge."""
from __future__ import annotations

from app.services.ingestion.review_tables import (
    flatten_job_result_to_review_tables,
    merge_file_result_into_batch,
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
