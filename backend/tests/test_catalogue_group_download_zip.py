"""Catalogue group ZIP must include every dataset in the release."""
from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.catalogue.group_export import (
    build_group_download_zip,
    build_groups_download_zip,
)
from app.services.grouping.matching import _groups_without_metadata


class _FakeCursor:
    def __init__(self, groups_by_id, datasets_by_mid, by_id):
        self._groups_by_id = groups_by_id
        self._datasets_by_mid = datasets_by_mid
        self._by_id = by_id
        self._result = []
        self._mode = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        q = " ".join(str(sql).lower().split())
        mid = params[0] if params else None
        if "from metadata_groups" in q:
            self._mode = "group"
            group = self._groups_by_id.get(mid) if mid else None
            self._result = [group] if group else []
        elif "dataset_id = any" in q:
            ids = list(params[0]) if params else []
            self._mode = "by_id"
            self._result = [self._by_id[i] for i in ids if i in self._by_id]
        elif "from datasets" in q and "metadata_id" in q:
            self._mode = "datasets"
            self._result = list(self._datasets_by_mid.get(mid, []))
        else:
            self._mode = None
            self._result = []

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)


class _FakeConn:
    def __init__(self, groups_by_id, datasets_by_mid, by_id=None):
        self._groups_by_id = groups_by_id
        self._datasets_by_mid = datasets_by_mid
        self._by_id = by_id or {}

    def cursor(self, cursor_factory=None):
        return _FakeCursor(self._groups_by_id, self._datasets_by_mid, self._by_id)


def _empty_group(metadata_id: str, title: str, table_ids: list[str]) -> dict:
    return {
        "metadata_id": metadata_id,
        "title": title,
        "description": "",
        "product": "",
        "category": "",
        "geography": "",
        "frequency": "",
        "time_period": "",
        "data_source": "",
        "last_updated_date": None,
        "future_release": "",
        "key_statistics": "",
        "remarks": "",
        "sector": "",
        "theme": "",
        "classifications": {},
        "nmds_concepts": [],
        "table_ids": table_ids,
    }


def test_build_group_download_zip_includes_all_datasets():
    group = _empty_group("META-1", "Transport chapter", ["DS_1", "DS_2", "DS_3"])
    datasets = [
        {"dataset_id": "DS_1", "title": "Table A", "table_id": "T1", "classifications": {}},
        {"dataset_id": "DS_2", "title": "Table A", "table_id": "T2", "classifications": {}},
        {"dataset_id": "DS_3", "title": "Table C", "table_id": "T3", "classifications": {}},
    ]
    rows_by_ds = {
        "DS_1": [{"col": "x", "n": 1}],
        "DS_2": [{"col": "y", "n": 2}],
        "DS_3": [{"col": "z", "n": 3}],
    }

    real_columns = build_group_download_zip.__globals__["_columns_and_rows_from_dataset"]

    def _fake_rows(conn, dataset_id):
        rows = rows_by_ds[dataset_id]
        cols = list(rows[0].keys())
        return cols, rows

    build_group_download_zip.__globals__["_columns_and_rows_from_dataset"] = _fake_rows
    try:
        payload, name = build_group_download_zip(
            _FakeConn({"META-1": group}, {"META-1": datasets}),
            "META-1",
        )
    finally:
        build_group_download_zip.__globals__["_columns_and_rows_from_dataset"] = real_columns

    assert name.endswith("_tables.zip")
    with zipfile.ZipFile(BytesIO(payload), "r") as zf:
        names = zf.namelist()
    assert len(names) == 3
    assert len(set(names)) == 3
    assert all(n.endswith(".xlsx") for n in names)
    assert all("/" not in n for n in names)


def test_build_groups_download_zip_includes_all_groups():
    group_a = _empty_group("META-A", "Group A", ["DS_A1", "DS_A2"])
    group_b = _empty_group("META-B", "Group B", ["DS_B1"])
    datasets_a = [
        {"dataset_id": "DS_A1", "title": "Alpha", "table_id": "TA1", "classifications": {}},
        {"dataset_id": "DS_A2", "title": "Beta", "table_id": "TA2", "classifications": {}},
    ]
    datasets_b = [
        {"dataset_id": "DS_B1", "title": "Gamma", "table_id": "TB1", "classifications": {}},
    ]
    rows_by_ds = {
        "DS_A1": [{"col": "a", "n": 1}],
        "DS_A2": [{"col": "b", "n": 2}],
        "DS_B1": [{"col": "c", "n": 3}],
    }

    real_columns = build_groups_download_zip.__globals__["_columns_and_rows_from_dataset"]

    def _fake_rows(conn, dataset_id):
        rows = rows_by_ds[dataset_id]
        return list(rows[0].keys()), rows

    build_groups_download_zip.__globals__["_columns_and_rows_from_dataset"] = _fake_rows
    try:
        payload, name = build_groups_download_zip(
            _FakeConn(
                {"META-A": group_a, "META-B": group_b},
                {"META-A": datasets_a, "META-B": datasets_b},
            ),
            ["META-A", "META-B", "META-A"],  # dedupe
        )
    finally:
        build_groups_download_zip.__globals__["_columns_and_rows_from_dataset"] = real_columns

    assert name.endswith("_all_tables.zip")
    with zipfile.ZipFile(BytesIO(payload), "r") as zf:
        names = zf.namelist()
    assert len(names) == 3
    assert all(n.endswith(".xlsx") for n in names)
    assert all("/" in n for n in names)
    folders = {n.split("/")[0] for n in names}
    assert folders == {"Group_A", "Group_B"}
    assert any(n.endswith("/Alpha.xlsx") for n in names)
    assert any(n.endswith("/Gamma.xlsx") for n in names)


def test_excel_without_metadata_groups_by_workbook():
    tables = [
        {"id": "a", "title": "Left", "source_type": "xlsx", "source_file": "chap10.xls", "sheet": "10.2a"},
        {"id": "b", "title": "Right", "source_type": "xlsx", "source_file": "chap10.xls", "sheet": "10.2a"},
        {"id": "c", "title": "Other", "source_type": "xlsx", "source_file": "other.xls", "sheet": "1"},
    ]
    result = _groups_without_metadata(tables)
    assert result["method"] == "workbook"
    assert len(result["groups"]) == 2
    by_file = {g["file_name"]: g for g in result["groups"]}
    assert len(by_file["chap10.xls"]["matched_tables"]) == 2
    assert len(by_file["other.xls"]["matched_tables"]) == 1
