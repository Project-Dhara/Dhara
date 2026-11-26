"""Realistic Ollama / OpenAI error strings for format vs context classifiers."""

from app.services.llm_errors import (
    classify_llm_api_error,
    is_context_length_error,
    is_format_unsupported_error,
)

# --- Fixtures: OpenAI ---
OPENAI_CONTEXT = (
    "Error code: 400 - {'error': {'message': \"This model's maximum context length "
    "is 8192 tokens. However, your messages resulted in 12040 tokens. "
    "Please reduce the length of the messages.\", 'type': 'invalid_request_error', "
    "'param': 'messages', 'code': 'context_length_exceeded'}}"
)
OPENAI_FORMAT = (
    "Error code: 400 - {'error': {'message': \"Invalid parameter: 'response_format' "
    "of type 'json_schema' is not supported with this model.\", "
    "'type': 'invalid_request_error', 'param': 'response_format', 'code': None}}"
)

# --- Fixtures: Ollama ---
OLLAMA_CONTEXT = (
    "POST http://127.0.0.1:11434/v1/chat/completions: "
    "error making request: the input length exceeds the context length "
    "(prompt too long for n_ctx)"
)
OLLAMA_FORMAT = (
    "Error code: 400 - {'error': {'message': "
    "'json_schema response_format is not supported by this model', 'type': 'api_error'}}"
)
OLLAMA_UNSUPPORTED_PARAM = (
    "400 Bad Request: unknown parameter: response_format"
)


def test_openai_context_length():
    assert is_context_length_error(OPENAI_CONTEXT)
    assert not is_format_unsupported_error(OPENAI_CONTEXT)
    assert classify_llm_api_error(OPENAI_CONTEXT) == "context"


def test_openai_format_unsupported():
    assert is_format_unsupported_error(OPENAI_FORMAT)
    assert not is_context_length_error(OPENAI_FORMAT)
    assert classify_llm_api_error(OPENAI_FORMAT) == "format"


def test_ollama_context_length():
    assert is_context_length_error(OLLAMA_CONTEXT)
    assert classify_llm_api_error(OLLAMA_CONTEXT) == "context"


def test_ollama_format_unsupported():
    assert is_format_unsupported_error(OLLAMA_FORMAT)
    assert classify_llm_api_error(OLLAMA_FORMAT) == "format"


def test_ollama_unknown_parameter():
    assert is_format_unsupported_error(OLLAMA_UNSUPPORTED_PARAM)
    assert classify_llm_api_error(OLLAMA_UNSUPPORTED_PARAM) == "format"


def test_unmatched_is_other(caplog):
    msg = "Error code: 503 - service unavailable upstream"
    assert classify_llm_api_error(msg) == "other"
    assert "did not match" in caplog.text or "service unavailable" in caplog.text
