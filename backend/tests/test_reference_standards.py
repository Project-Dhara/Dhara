"""Settings shows bundled LGD codes (read-only) next to the selectable NCO standard."""
import asyncio
import contextlib
import json

from app.api.routes import catalogue_standards as routes
from app.services.classification.lgd_directory import find_hierarchy_path
from app.services.standards import reference_standards as ref


def _bundled_total() -> int:
    data = json.loads(find_hierarchy_path().read_text(encoding="utf-8"))
    return sum(ref._count_entities(data).values())


def test_lgd_reference_entry_is_read_only_and_counts_codes():
    entries = ref.list_reference_standards()
    assert len(entries) == 1
    lgd = entries[0]
    assert lgd["kind"] == "lgd" and lgd["name"] == "LGD codes"
    assert lgd["row_count"] == _bundled_total() > 0
    assert lgd["uploaded_by"] == "system"
    # Never selectable: must not look like a classification standard row.
    assert "is_selected" not in lgd
    assert sum(lgd["breakdown"].values()) == lgd["row_count"]
    assert lgd["summary"].startswith("1 state")


def test_missing_lgd_file_returns_empty(monkeypatch):
    def _missing():
        raise FileNotFoundError("no hierarchy")

    monkeypatch.setattr(ref, "find_hierarchy_path", _missing)
    assert ref.list_reference_standards() == []


def test_standards_route_keeps_nco_list_and_adds_reference(monkeypatch):
    nco = [{"id": 1, "name": "NCO 2015", "is_selected": True, "row_count": 3}]

    @contextlib.contextmanager
    def _scope():
        yield object()

    monkeypatch.setattr(routes, "session_scope", _scope)
    monkeypatch.setattr(routes, "dbapi_connection", lambda s: s)
    monkeypatch.setattr(routes, "ensure_bundled_classification_standard", lambda c: None)
    monkeypatch.setattr(routes, "list_classification_standards", lambda c: nco)

    out = asyncio.run(routes.get_classification_standards(user_email="u@example.com"))
    assert out["standards"] == nco  # NCO list untouched (Classify relies on is_selected here)
    assert [s["kind"] for s in out["reference_standards"]] == ["lgd"]
