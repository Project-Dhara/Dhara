"""Classification Fill-with-AI definitions: schema, compact, partial batches."""

from __future__ import annotations

import json

from app.services.metadata.definitions_llm import (
    DEFINITION_BATCH_SIZE_COMPACT,
    _definition_response_format,
    _parse_definitions_json,
    fill_classification_definitions,
    resolve_definitions_compact,
)


def test_definition_schema_includes_every_key_and_forbids_extras():
    values = ["Rural", "Urban", "Total"]
    fmt = _definition_response_format(values)
    assert fmt["type"] == "json_schema"
    schema = fmt["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == set(values)
    assert set(schema["required"]) == set(values)
    for v in values:
        assert schema["properties"][v] == {"type": "string"}


def test_parse_definitions_tolerates_fenced_and_trailing_commas():
    values = ["A", "B"]
    text = '```json\n{"A": "Alpha gloss here", "B": "Beta short label",}\n```'
    out = _parse_definitions_json(text, values)
    assert out["A"].startswith("Alpha")
    assert out["B"].startswith("Beta")


def test_parse_definitions_case_insensitive_keys():
    values = ["Rural"]
    out = _parse_definitions_json('{"rural": "Countryside area"}', values)
    assert out == {"Rural": "Countryside area"}


def test_compact_for_gemma3_1b_self_hosted():
    assert resolve_definitions_compact(self_hosted=True, model="gemma3:1b") is True
    assert resolve_definitions_compact(self_hosted=False, model="gpt-4o-mini") is False


def test_partial_batches_keep_earlier_defs_when_later_fails(monkeypatch):
    """batch1+2 OK, batch3 raises → merged has first batches only; errors non-empty."""
    monkeypatch.setattr(
        "app.services.metadata.definitions_llm.DEFINITION_BATCH_SIZE_COMPACT",
        15,
    )
    # 45 values → 3 compact batches of 15
    values = [f"v{i:02d}" for i in range(45)]
    calls = {"n": 0}

    def complete_fn(prompt, max_tokens, **kwargs):
        calls["n"] += 1
        rf = kwargs.get("response_format") or {}
        schema = rf["json_schema"]["schema"]
        keys = list(schema["required"])
        assert schema["additionalProperties"] is False
        assert len(keys) == 15
        if calls["n"] <= 2:
            return json.dumps({k: f"def for {k}" for k in keys})
        raise TimeoutError("batch3 timed out")

    defs, errors = fill_classification_definitions(
        complete_fn,
        "sector",
        values,
        {"title": "demo"},
        compact=True,
        deadline_monotonic=1e18,  # plenty of time; continue after batch fail
    )

    assert calls["n"] == 3
    assert len(defs) == 30
    for i in range(30):
        assert f"v{i:02d}" in defs
    for i in range(30, 45):
        assert f"v{i:02d}" not in defs
    assert len(errors) == 1
    assert errors[0]["column"] == "sector"
    assert errors[0]["batch"] == 2
    assert "timed out" in errors[0]["error"].lower() or "Timeout" in errors[0]["error"]


def test_deadline_exhausted_stops_further_batches(monkeypatch):
    monkeypatch.setattr(
        "app.services.metadata.definitions_llm.DEFINITION_BATCH_SIZE_COMPACT",
        15,
    )
    values = [f"v{i:02d}" for i in range(45)]
    calls = {"n": 0}

    def complete_fn(prompt, max_tokens, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            keys = kwargs["response_format"]["json_schema"]["schema"]["required"]
            return json.dumps({k: f"d {k}" for k in keys})
        raise RuntimeError("boom")

    # Already past deadline → after first failure, remaining < 8s → stop
    defs, errors = fill_classification_definitions(
        complete_fn,
        "col",
        values,
        {},
        compact=True,
        deadline_monotonic=0.0,
    )
    assert len(defs) == 15
    assert len(errors) == 1
    # Second batch failed; third never attempted
    assert calls["n"] == 2


def test_fill_definitions_response_keeps_partial_alongside_errors(monkeypatch):
    """Route contract: partial column defs appear under definitions AND in errors.

    Mirrors packaging in catalogue_standards.fill_definitions without importing
    FastAPI (system test envs may lack it).
    """
    monkeypatch.setattr(
        "app.services.metadata.definitions_llm.DEFINITION_BATCH_SIZE_COMPACT",
        15,
    )
    values = [f"v{i:02d}" for i in range(45)]
    calls = {"n": 0}

    def complete_fn(prompt, max_tokens, **kwargs):
        calls["n"] += 1
        keys = kwargs["response_format"]["json_schema"]["schema"]["required"]
        if calls["n"] <= 2:
            return json.dumps({k: f"def {k}" for k in keys})
        raise TimeoutError("batch3 timed out")

    # Simulate per-column loop used by the route.
    out: dict = {}
    errors: list = []
    defs, batch_errors = fill_classification_definitions(
        complete_fn,
        "sector",
        values,
        {},
        compact=True,
        deadline_monotonic=1e18,
    )
    if defs:
        out["sector"] = defs
    errors.extend(batch_errors)
    # Column must not be replaced with {} on a later-batch failure.
    response = {"definitions": out, "errors": errors}

    assert "sector" in response["definitions"]
    assert len(response["definitions"]["sector"]) == 30
    assert response["errors"], "failed remainder must be listed"
    assert response["errors"][0]["column"] == "sector"
    assert response["definitions"]["sector"] != {}
    assert DEFINITION_BATCH_SIZE_COMPACT == 15
