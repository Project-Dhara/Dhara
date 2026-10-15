"""Sequential catalogue / Preview dataset ID helpers."""
from __future__ import annotations

from app.services.ingestion.table_ids import (
    assign_table_ids_to_result,
    build_review_table_id,
    ensure_sequential_dataset_ids_on_job,
    find_table_in_job_result,
    format_sequential_dataset_id,
    is_review_locator_id,
    is_sequential_catalogue_id,
    statistics_short_form,
)


def test_statistics_short_form():
    assert statistics_short_form("Vital Statistics") == "VS"
    assert statistics_short_form("Labour Statistics") == "LS"
    assert statistics_short_form("Industrial Statistics") == "IS"


def test_format_sequential_dataset_id():
    assert format_sequential_dataset_id(42) == "DDI_DES_DEL_VS_00042"
    assert format_sequential_dataset_id(1) == "DDI_DES_DEL_VS_00001"
    assert is_sequential_catalogue_id("DDI_DES_DEL_VS_00042")
    assert not is_sequential_catalogue_id("DDI_DES_DEL_VS_P79")
    assert is_review_locator_id("DDI_DES_DEL_VS_P79")
    assert is_review_locator_id("DDI_DES_DEL_VS_F1_P79_T2")
    assert not is_review_locator_id("DDI_DES_DEL_VS_00042")


def test_build_review_table_id_is_locator_only():
    tid = build_review_table_id(
        source_filename="infant_mortality.pdf",
        page=79,
        index=0,
        tables_on_page=1,
    )
    assert tid == "DDI_DES_DEL_VS_P79"
    assert not is_sequential_catalogue_id(tid)


def test_assign_stamps_sequential_ids(monkeypatch):
    seq = {"n": 0}

    def _fake_mint(cfg, count):
        out = []
        for _ in range(count):
            seq["n"] += 1
            out.append(format_sequential_dataset_id(seq["n"], config=cfg))
        return out

    monkeypatch.setattr(
        "app.services.ingestion.table_ids._mint_sequential_dataset_ids",
        _fake_mint,
    )

    result = {
        10: {
            "tables": [
                {"page": 10, "source_filename": "a.pdf"},
                {"page": 10, "source_filename": "a.pdf"},
            ]
        }
    }
    assign_table_ids_to_result(result, default_filename="a.pdf")
    assert result[10]["tables"][0]["table_id"] == "DDI_DES_DEL_VS_00001"
    assert result[10]["tables"][1]["table_id"] == "DDI_DES_DEL_VS_00002"
    assert result[10]["tables"][0]["dataset_id"] == "DDI_DES_DEL_VS_00001"
    assert "INFANT" not in result[10]["tables"][0]["table_id"]
    assert "_P" not in result[10]["tables"][0]["table_id"]


def test_assign_keeps_existing_sequential(monkeypatch):
    def _boom(cfg, count):
        raise AssertionError("should not mint when already sequential")

    monkeypatch.setattr(
        "app.services.ingestion.table_ids._mint_sequential_dataset_ids",
        _boom,
    )
    result = {
        5: {
            "tables": [
                {"page": 5, "table_id": "DDI_DES_DEL_VS_00099", "source_filename": "x.pdf"}
            ]
        }
    }
    assign_table_ids_to_result(result, default_filename="x.pdf")
    assert result[5]["tables"][0]["table_id"] == "DDI_DES_DEL_VS_00099"


def test_assign_and_find_batch_table(monkeypatch):
    seq = {"n": 0}

    def _fake_mint(cfg, count):
        out = []
        for _ in range(count):
            seq["n"] += 1
            out.append(format_sequential_dataset_id(seq["n"], config=cfg))
        return out

    monkeypatch.setattr(
        "app.services.ingestion.table_ids._mint_sequential_dataset_ids",
        _fake_mint,
    )
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
    assert tid == "DDI_DES_DEL_VS_00001"

    job = {"job_id": "batch", "result": result, "filename": "1 file"}
    found = find_table_in_job_result(job, tid)
    assert found is not None
    page_key, idx, table = found
    assert page_key == "__f0__48"
    assert idx == 0
    assert table["table_id"] == tid


def test_ensure_upgrades_legacy_locators(monkeypatch):
    seq = {"n": 40}

    def _fake_mint(cfg, count):
        out = []
        for _ in range(count):
            seq["n"] += 1
            out.append(format_sequential_dataset_id(seq["n"], config=cfg))
        return out

    monkeypatch.setattr(
        "app.services.ingestion.table_ids._mint_sequential_dataset_ids",
        _fake_mint,
    )
    monkeypatch.setattr(
        "app.services.ingestion.table_ids._migrate_snapshot_table_ids",
        lambda *a, **k: None,
    )
    job = {
        "job_id": "j1",
        "filename": "report.pdf",
        "source_type": "pdf",
        "reviews": {"DDI_DES_DEL_VS_P79": {"human_review_status": "ok"}},
        "result": {
            79: {
                "tables": [
                    {"page": 79, "table_id": "DDI_DES_DEL_VS_P79", "source_filename": "report.pdf"}
                ]
            }
        },
    }
    assert ensure_sequential_dataset_ids_on_job(job) is True
    tid = job["result"][79]["tables"][0]["table_id"]
    assert tid == "DDI_DES_DEL_VS_00041"
    assert "DDI_DES_DEL_VS_P79" not in job["reviews"]
    assert job["reviews"][tid]["human_review_status"] == "ok"
    # Second ensure is a no-op.
    assert ensure_sequential_dataset_ids_on_job(job) is False
