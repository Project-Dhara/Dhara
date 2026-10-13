"""Human-readable review table ID helpers."""
from __future__ import annotations

from app.services.ingestion.table_ids import (
    assign_table_ids_to_result,
    build_review_table_id,
    find_table_in_job_result,
    statistics_short_form,
)


def test_statistics_short_form():
    assert statistics_short_form("Vital Statistics") == "VS"
    assert statistics_short_form("Labour Statistics") == "LS"
    assert statistics_short_form("Industrial Statistics") == "IS"


def test_build_review_table_id_single_table_no_t_suffix():
    tid = build_review_table_id(
        source_filename="1.pdf",
        page=79,
        index=0,
        tables_on_page=1,
    )
    assert tid == "DDI_DES_DEL_VS_1_P79"
    assert "PDF" not in tid
    assert "_F" not in tid
    assert "_T" not in tid


def test_build_review_table_id_multi_table_adds_t():
    tid = build_review_table_id(
        source_filename="1.pdf",
        page=79,
        index=1,
        tables_on_page=2,
    )
    assert tid == "DDI_DES_DEL_VS_1_P79_T2"


def test_build_review_table_id_no_redundant_file_index():
    tid = build_review_table_id(
        source_filename="report.pdf",
        page=12,
        index=0,
        tables_on_page=1,
        file_index=1,
    )
    assert tid == "DDI_DES_DEL_VS_REPORT_P12"
    assert "F2" not in tid


def test_assign_and_find_batch_table():
    result = {
        "__f0__48": {
            "tables": [
                {"page": 48, "bbox": [0, 0, 1, 1], "source_filename": "1.pdf", "source_type": "pdf"}
            ]
        },
        "__batch_meta__": {
            "batch_files": [{"file_job_id": "c1", "filename": "1.pdf", "source_type": "pdf"}]
        },
    }
    assign_table_ids_to_result(
        result,
        default_filename="1.pdf",
        batch_files=result["__batch_meta__"]["batch_files"],
    )
    tid = result["__f0__48"]["tables"][0]["table_id"]
    assert tid == "DDI_DES_DEL_VS_1_P48"
    assert "F1" not in tid
    assert "T1" not in tid
    assert "PDF" not in tid

    job = {"job_id": "batch", "result": result, "filename": "1 file"}
    found = find_table_in_job_result(job, tid)
    assert found is not None
    page_key, idx, table = found
    assert page_key == "__f0__48"
    assert idx == 0
    assert table["table_id"] == tid


def test_assign_multi_table_page_uses_t_suffix():
    result = {
        10: {
            "tables": [
                {"page": 10, "source_filename": "a.pdf"},
                {"page": 10, "source_filename": "a.pdf"},
            ]
        }
    }
    assign_table_ids_to_result(result, default_filename="a.pdf")
    assert result[10]["tables"][0]["table_id"] == "DDI_DES_DEL_VS_A_P10_T1"
    assert result[10]["tables"][1]["table_id"] == "DDI_DES_DEL_VS_A_P10_T2"


def test_temp_filename_uses_upload_name_not_tmp_stem():
    from app.services.ingestion.table_ids import build_review_table_id, source_stem_abbrev

    assert source_stem_abbrev("tmp86rimsi.pdf", source_type="pdf") == "PDF"
    assert build_review_table_id(
        source_filename="tmp86rimsi.pdf",
        page=51,
        index=0,
        tables_on_page=1,
    ) == "DDI_DES_DEL_VS_PDF_P51"

    result = {
        51: {
            "tables": [
                {
                    "page": 51,
                    "source_filename": "tmp86rimsi.pdf",
                    "source_type": "pdf",
                }
            ]
        }
    }
    assign_table_ids_to_result(result, default_filename="1.pdf")
    assert result[51]["tables"][0]["table_id"] == "DDI_DES_DEL_VS_1_P51"
    assert result[51]["tables"][0]["source_filename"] == "1.pdf"
