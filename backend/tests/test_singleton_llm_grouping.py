"""Strict singleton LLM merge gates for automatic grouping."""
from __future__ import annotations

from pdf.pdf_grouping import (
    _titles_pair_compatible,
    _titles_strictly_compatible,
    _validate_singleton_merges,
    merge_singleton_groups_strict,
)


def _singleton_group(tid: str, title: str) -> dict:
    return {
        "name": title,
        "tables": [{"id": tid, "title": title}],
        "table_pks": [tid],
    }


def test_compatible_near_duplicate_titles():
    a = "LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT"
    b = "LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT OF MOTHER"
    assert _titles_pair_compatible(a, b)
    assert _titles_strictly_compatible([a, b])


def test_incompatible_different_subjects():
    a = "LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT"
    b = "INFANT DEATHS BY AGE GROUP AND SEX"
    assert not _titles_pair_compatible(a, b)
    assert not _titles_strictly_compatible([a, b])


def test_validate_rejects_low_overlap_even_if_llm_says_high():
    g1 = _singleton_group("1", "LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT")
    g2 = _singleton_group("2", "INFANT DEATHS BY AGE GROUP AND SEX")
    by_id = {"1": g1, "2": g2}
    merges = [
        {"table_ids": ["1", "2"], "name": "Vital events", "confidence": "high"}
    ]
    assert _validate_singleton_merges(merges, by_id) == []


def test_validate_accepts_compatible_high_confidence():
    g1 = _singleton_group("1", "LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT")
    g2 = _singleton_group(
        "2", "LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT OF MOTHER"
    )
    by_id = {"1": g1, "2": g2}
    merges = [
        {"table_ids": ["1", "2"], "name": "Live births", "confidence": "high"}
    ]
    assert _validate_singleton_merges(merges, by_id) == [["1", "2"]]


def test_validate_requires_explicit_high_confidence():
    g1 = _singleton_group("1", "LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT")
    g2 = _singleton_group(
        "2", "LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT OF MOTHER"
    )
    by_id = {"1": g1, "2": g2}
    merges = [
        {"table_ids": ["1", "2"], "name": "Live births", "confidence": "medium"}
    ]
    assert _validate_singleton_merges(merges, by_id) == []


def test_merge_without_api_key_is_noop(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    groups = [
        _singleton_group("1", "LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT"),
        _singleton_group(
            "2", "LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT OF MOTHER"
        ),
    ]
    out, changed = merge_singleton_groups_strict(groups, api_key=None)
    assert changed is False
    assert out == groups


def test_merge_maps_surrogate_ids_from_llm(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fake_batched(items, *, api_key):
        by_title = {it["title"]: it["id"] for it in items}
        return [
            {
                "table_ids": [
                    by_title["LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT"],
                    by_title["LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT OF MOTHER"],
                ],
                "name": "Live births",
                "confidence": "high",
            }
        ]

    monkeypatch.setattr(
        "pdf.pdf_grouping._call_singleton_merge_llm_batched", fake_batched
    )
    multi = {
        "name": "Already grouped",
        "tables": [
            {"id": "a", "title": "X (URBAN)"},
            {"id": "b", "title": "X (RURAL)"},
        ],
        "table_pks": ["a", "b"],
    }
    g1 = _singleton_group(
        "uuid-aaaa-1111", "LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT"
    )
    g2 = _singleton_group(
        "uuid-bbbb-2222",
        "LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT OF MOTHER",
    )
    g3 = _singleton_group("uuid-cccc-3333", "COMPLETELY UNRELATED TITLE ABOUT TAXES")
    out, changed = merge_singleton_groups_strict(
        [multi, g1, g2, g3], api_key="test-key"
    )
    assert changed is True
    assert any(
        len(g["tables"]) == 2 and {t["id"] for t in g["tables"]} == {"a", "b"}
        for g in out
    )
    merged = [
        g
        for g in out
        if {t["id"] for t in g["tables"]} == {"uuid-aaaa-1111", "uuid-bbbb-2222"}
    ]
    assert len(merged) == 1
    assert any(len(g["tables"]) == 1 and g["tables"][0]["id"] == "uuid-cccc-3333" for g in out)


def test_surrogate_id_remap_in_llm_response(monkeypatch):
    """Model returns t1/t2; caller must map back to real UUIDs."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    class FakeResp:
        class Choice:
            class Msg:
                content = (
                    '{"merges":[{"table_ids":["t1","t2"],'
                    '"name":"Live births","confidence":"high"}]}'
                )

            message = Msg()

        choices = [Choice()]

    class FakeClient:
        def __init__(self, api_key=None):
            self.api_key = api_key

        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return FakeResp()

    import pdf.pdf_grouping as mod

    monkeypatch.setattr(mod, "OpenAI", FakeClient, raising=False)

    # Patch openai import inside the function
    import sys
    import types

    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = FakeClient
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    from pdf.pdf_grouping import _call_singleton_merge_llm

    items = [
        {"id": "uuid-1", "title": "LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT"},
        {
            "id": "uuid-2",
            "title": "LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT OF MOTHER",
        },
    ]
    merges = _call_singleton_merge_llm(items, api_key="k")
    assert merges == [
        {
            "table_ids": ["uuid-1", "uuid-2"],
            "name": "Live births",
            "confidence": "high",
        }
    ]
