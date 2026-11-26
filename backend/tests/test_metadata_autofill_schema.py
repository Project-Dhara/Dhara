"""Schema shape, compact selection, format cache, and deadline-aware _complete."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.ingestion.wizard.extractor import (
    LlmContextLengthExceeded,
    LlmDeadlineExceeded,
    TableExtractor,
    clear_format_level_cache,
    get_cached_format_level,
    set_cached_format_level,
)
from app.services.metadata.nmds_llm import (
    METADATA_FIELDS,
    METADATA_JSON_SCHEMA,
    METADATA_RESPONSE_FORMAT,
    generate_metadata_with_llm,
    use_compact_metadata_prompt,
)
from app.services.metadata.sdg_llm import (
    SDG_METADATA_FIELDS,
    SDG_METADATA_JSON_SCHEMA,
)


def test_metadata_schema_is_strict_nullable():
    assert METADATA_JSON_SCHEMA["additionalProperties"] is False
    assert set(METADATA_JSON_SCHEMA["required"]) == set(METADATA_FIELDS)
    for field in METADATA_FIELDS:
        prop = METADATA_JSON_SCHEMA["properties"][field]
        assert prop == {"type": ["string", "null"]}
        assert "minLength" not in prop
        assert "pattern" not in prop
    assert METADATA_RESPONSE_FORMAT["type"] == "json_schema"
    assert METADATA_RESPONSE_FORMAT["json_schema"]["strict"] is True


def test_sdg_schema_is_strict_nullable():
    assert SDG_METADATA_JSON_SCHEMA["additionalProperties"] is False
    assert set(SDG_METADATA_JSON_SCHEMA["required"]) == set(SDG_METADATA_FIELDS)
    for field in SDG_METADATA_FIELDS:
        assert SDG_METADATA_JSON_SCHEMA["properties"][field] == {"type": ["string", "null"]}


def test_compact_heuristic_and_override(monkeypatch):
    assert use_compact_metadata_prompt(self_hosted=True, model="gemma3:1b") is True
    assert use_compact_metadata_prompt(self_hosted=True, model="llama3.2:1b") is True
    assert use_compact_metadata_prompt(self_hosted=True, model="qwen2.5:3b") is False
    assert use_compact_metadata_prompt(self_hosted=False, model="gemma3:1b") is False

    monkeypatch.setenv("DHARA_METADATA_COMPACT", "1")
    assert use_compact_metadata_prompt(self_hosted=False, model="gpt-4o") is True
    monkeypatch.setenv("DHARA_METADATA_COMPACT", "0")
    assert use_compact_metadata_prompt(self_hosted=True, model="gemma3:1b") is False
    monkeypatch.delenv("DHARA_METADATA_COMPACT", raising=False)


def test_generate_compact_passes_schema_and_low_tokens():
    calls = []

    def complete_fn(prompt, max_tokens, **kwargs):
        calls.append((prompt, max_tokens, kwargs))
        return json.dumps({f: None for f in METADATA_FIELDS})

    generate_metadata_with_llm(
        {"sheets": [{"sheet_name": "s", "tables": [{"title_context": "T", "column_names": ["a"], "sample_rows": []}]}]},
        kyds={},
        complete_fn=complete_fn,
        compact=True,
        deadline_monotonic=time.monotonic() + 60,
    )
    assert len(calls) == 1
    prompt, max_tokens, kwargs = calls[0]
    assert max_tokens == 700
    assert kwargs.get("temperature") == 0.1
    assert kwargs.get("response_format") == METADATA_RESPONSE_FORMAT
    assert "Return only the JSON object." in prompt
    # Data first: JSON blob before instructions.
    assert prompt.strip().startswith("{")


def test_format_cache_ttl(monkeypatch):
    clear_format_level_cache()
    set_cached_format_level("http://127.0.0.1:11434/v1", "gemma3:1b", "none")
    assert get_cached_format_level("http://127.0.0.1:11434/v1", "gemma3:1b") == "none"

    # Expire immediately.
    import app.services.ingestion.wizard.extractor as ex

    monkeypatch.setattr(ex, "_FORMAT_CACHE_TTL_SEC", 0)
    set_cached_format_level("http://127.0.0.1:11434/v1", "gemma3:1b", "none")
    time.sleep(0.01)
    assert get_cached_format_level("http://127.0.0.1:11434/v1", "gemma3:1b") is None
    clear_format_level_cache()


class _FakeChoice:
    def __init__(self, content, finish_reason="stop"):
        self.message = SimpleNamespace(content=content)
        self.finish_reason = finish_reason


class _FakeResp:
    def __init__(self, content, finish_reason="stop"):
        self.choices = [_FakeChoice(content, finish_reason)]


def _extractor_with_mock_client():
    clear_format_level_cache()
    ex = TableExtractor(api_key="ollama", provider="self-hosted", base_url="http://127.0.0.1:11434/v1", model="gemma3:1b")
    return ex


def test_complete_steps_down_only_on_format_error():
    ex = _extractor_with_mock_client()
    creates = []

    def fake_create(**kwargs):
        creates.append(kwargs.get("response_format"))
        fmt = kwargs.get("response_format") or {}
        if isinstance(fmt, dict) and fmt.get("type") == "json_schema":
            raise Exception("Invalid parameter: 'response_format' of type 'json_schema' is not supported")
        return _FakeResp('{"title":"ok"}')

    client = MagicMock()
    client.chat.completions.create.side_effect = fake_create

    with patch.object(ex, "_openai_client_for_timeout", return_value=client):
        text = ex._complete(
            "hi",
            100,
            response_format=METADATA_RESPONSE_FORMAT,
            deadline_monotonic=time.monotonic() + 60,
        )
    assert text == '{"title":"ok"}'
    assert creates[0]["type"] == "json_schema"
    assert creates[1] == {"type": "json_object"}
    assert get_cached_format_level("http://127.0.0.1:11434/v1", "gemma3:1b") == "json_object"
    clear_format_level_cache()


def test_complete_context_length_fail_fast():
    ex = _extractor_with_mock_client()

    def fake_create(**kwargs):
        raise Exception(
            "This model's maximum context length is 8192 tokens. "
            "However, your messages resulted in 12040 tokens."
        )

    client = MagicMock()
    client.chat.completions.create.side_effect = fake_create

    with patch.object(ex, "_openai_client_for_timeout", return_value=client):
        with pytest.raises(LlmContextLengthExceeded):
            ex._complete(
                "hi",
                100,
                response_format=METADATA_RESPONSE_FORMAT,
                deadline_monotonic=time.monotonic() + 60,
            )
    clear_format_level_cache()


def test_complete_skips_retries_when_deadline_exhausted():
    ex = _extractor_with_mock_client()
    with pytest.raises(LlmDeadlineExceeded):
        ex._complete(
            "hi",
            100,
            response_format=METADATA_RESPONSE_FORMAT,
            deadline_monotonic=time.monotonic() - 1,
        )


def test_complete_uses_cached_format_level():
    ex = _extractor_with_mock_client()
    set_cached_format_level("http://127.0.0.1:11434/v1", "gemma3:1b", "json_object")
    creates = []

    def fake_create(**kwargs):
        creates.append(kwargs.get("response_format"))
        return _FakeResp("{}")

    client = MagicMock()
    client.chat.completions.create.side_effect = fake_create
    with patch.object(ex, "_openai_client_for_timeout", return_value=client):
        ex._complete(
            "hi",
            50,
            response_format=METADATA_RESPONSE_FORMAT,
            deadline_monotonic=time.monotonic() + 60,
        )
    assert creates[0] == {"type": "json_object"}
    clear_format_level_cache()
