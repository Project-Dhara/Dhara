"""Published dataset_id resolution (sequential catalogue ids vs Excel / KYDS)."""
from __future__ import annotations

from app.db.repositories.datasets import (
    allocate_sequential_dataset_id,
    prefer_existing_catalogue_dataset_id,
    resolve_catalogue_dataset_id,
)


class _Nested:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_pdf_review_locator_not_used_as_catalogue_id():
    """Preview ``…_P79`` must not become the published PK; allocate instead."""
    allocated = []

    def _fake_alloc(session, config=None):
        allocated.append(True)
        return "DDI_DES_DEL_VS_00001"

    class _EmptyResult:
        def first(self):
            return None

    class _Session:
        def begin_nested(self):
            return _Nested()

        def execute(self, stmt, params=None):
            return _EmptyResult()

    import app.db.repositories.datasets as mod

    original = mod.allocate_sequential_dataset_id
    mod.allocate_sequential_dataset_id = _fake_alloc
    try:
        tid = resolve_catalogue_dataset_id(
            {
                "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "table_id": "DDI_DES_DEL_VS_P79",
            },
            0,
            session=_Session(),
        )
    finally:
        mod.allocate_sequential_dataset_id = original

    assert tid == "DDI_DES_DEL_VS_00001"
    assert allocated


def test_excel_ddi_id_preferred_over_source_table_label():
    tid = resolve_catalogue_dataset_id(
        {
            "id": "DDI_DEL_DES_VS_B14_RURAL_2024_V1",
            "table_id": "Table : B-14",
        },
        0,
    )
    assert tid == "DDI_DEL_DES_VS_B14_RURAL_2024_V1"


def test_explicit_dataset_id_wins():
    tid = resolve_catalogue_dataset_id(
        {
            "dataset_id": "DDI_DES_DEL_VS_CUSTOM",
            "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "table_id": "DDI_DES_DEL_VS_P79",
        },
        0,
    )
    assert tid == "DDI_DES_DEL_VS_CUSTOM"


def test_prefer_existing_skips_review_locator():
    assert (
        prefer_existing_catalogue_dataset_id(
            {
                "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "table_id": "DDI_DES_DEL_VS_P79",
            }
        )
        is None
    )


def test_allocate_sequential_never_reuses():
    """Counter advances past existing rows and skips collisions."""
    state = {"last": 41, "datasets": {"DDI_DES_DEL_VS_00042"}}

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

        def first(self):
            return self._rows[0] if self._rows else None

        def one(self):
            return self._rows[0]

    class _Session:
        def begin_nested(self):
            return _Nested()

        def execute(self, stmt, params=None):
            sql = str(stmt).lower()
            params = params or {}
            if "create table if not exists dataset_id_counters" in sql:
                return _Result([])
            if "from datasets where dataset_id like" in sql:
                return _Result([(d,) for d in state["datasets"] if d.startswith("DDI_DES_DEL_VS_")])
            if "insert into dataset_id_counters" in sql:
                return _Result([])
            if "set last_value = greatest" in sql:
                state["last"] = max(state["last"], int(params.get("floor") or 0))
                return _Result([])
            if "set last_value = last_value + 1" in sql:
                state["last"] += 1
                return _Result([(state["last"],)])
            if "select 1 from datasets where dataset_id" in sql:
                ds = params.get("ds")
                return _Result([(1,)] if ds in state["datasets"] else [])
            return _Result([])

    sid = allocate_sequential_dataset_id(_Session())
    assert sid == "DDI_DES_DEL_VS_00043"
    # Second allocation continues (never reuse 42 or 43 until counter advances).
    state["datasets"].add(sid)
    sid2 = allocate_sequential_dataset_id(_Session())
    assert sid2 == "DDI_DES_DEL_VS_00044"


def test_allocate_falls_back_when_counter_table_missing():
    """Publish must still mint a free sequential id without dataset_id_counters."""
    state = {"datasets": {"DDI_DES_DEL_VS_00001", "DDI_DES_DEL_VS_00002"}}

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

        def first(self):
            return self._rows[0] if self._rows else None

    class _Session:
        def begin_nested(self):
            raise RuntimeError("counters ddl blocked")

        def execute(self, stmt, params=None):
            sql = str(stmt).lower()
            params = params or {}
            if "from datasets where dataset_id like" in sql:
                return _Result([(d,) for d in sorted(state["datasets"])])
            if "select 1 from datasets where dataset_id" in sql:
                ds = params.get("ds")
                return _Result([(1,)] if ds in state["datasets"] else [])
            return _Result([])

    sid = allocate_sequential_dataset_id(_Session())
    assert sid == "DDI_DES_DEL_VS_00003"


def test_republish_reuses_existing_by_review_table_id():
    class _Result:
        def __init__(self, row):
            self._row = row

        def first(self):
            return self._row

    class _Session:
        def begin_nested(self):
            return _Nested()

        def execute(self, stmt, params=None):
            if params and params.get("c") == "DDI_DES_DEL_VS_P79":
                return _Result(("DDI_DES_DEL_VS_00007",))
            return _Result(None)

    tid = resolve_catalogue_dataset_id(
        {
            "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "table_id": "DDI_DES_DEL_VS_P79",
        },
        0,
        session=_Session(),
    )
    assert tid == "DDI_DES_DEL_VS_00007"
