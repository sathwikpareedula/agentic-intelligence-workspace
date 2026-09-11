"""Contract and failure tests for the native local Ollama provider."""

import json
from urllib.request import ProxyHandler

from app.agent.models import Complete, ToolCall, ToolObservation
from app.agent.providers import ModelProviderError, OllamaModelProvider, _NoOllamaRedirects, _OLLAMA_URL_OPENER


class RecordingTransport:
    def __init__(self, response=None, error=None) -> None:
        self.response = response
        self.error = error
        self.calls = []

    def __call__(self, url, payload, timeout_seconds):
        self.calls.append((url, payload, timeout_seconds))
        if self.error is not None:
            raise self.error
        return self.response


def _response(decision, **metrics):
    return {
        "model": "fixture-model",
        "message": {"role": "assistant", "content": json.dumps({"decision": decision})},
        "done": True,
        **metrics,
    }


def _provider(transport, *, tools=None, retries=0, base_url=None):
    return OllamaModelProvider(
        "fixture-model",
        tools or [],
        3.0,
        retries,
        base_url,
        512,
        transport=transport,
    )


def test_ollama_provider_uses_native_chat_schema_and_bounded_options() -> None:
    transport = RecordingTransport(
        _response({"type": "tool_call", "tool": "dataset.inspect", "arguments": {"dataset": "orders.csv"}})
    )
    tools = [{"name": "dataset.inspect", "input_schema": {"type": "object"}}]
    provider = _provider(transport, tools=tools)

    decision = provider.decide(
        "Inspect the bound dataset.",
        [ToolObservation(success=True, summary="Listed resources", result={"datasets": ["orders.csv"]})],
    )

    assert isinstance(decision, ToolCall)
    assert decision.tool == "dataset.inspect"
    url, payload, timeout = transport.calls[0]
    assert url == "http://127.0.0.1:11434/api/chat"
    assert timeout == 3.0
    assert payload["stream"] is False
    assert payload["format"]["additionalProperties"] is False
    assert payload["options"] == {"temperature": 0, "num_predict": 512, "num_ctx": 8192}
    assert payload["messages"][0]["role"] == "system"
    user_payload = json.loads(payload["messages"][1]["content"])
    assert user_payload["available_tools"] == tools
    assert user_payload["observations"][0]["result"]["datasets"] == ["orders.csv"]


def test_ollama_provider_fails_closed_on_malformed_json_and_schema() -> None:
    malformed = [
        {"message": {"content": "not-json"}},
        {"message": {"content": json.dumps({"decision": {"type": "complete", "answer": "ok", "extra": True}})}},
        {"message": {"content": json.dumps({"decision": {"type": "tool_call", "tool": "x", "arguments": []}})}},
    ]
    for response in malformed:
        provider = _provider(RecordingTransport(response))
        try:
            provider.decide("Finish", [])
        except ModelProviderError as exc:
            assert exc.code == "malformed_response"
            assert str(exc) == "Orchestrator provider returned malformed structured output."
        else:
            raise AssertionError("Malformed Ollama output must fail closed.")


def test_ollama_provider_rejects_tools_outside_supplied_set() -> None:
    provider = _provider(
        RecordingTransport(_response({"type": "tool_call", "tool": "workflow.delete", "arguments": {}})),
        tools=[{"name": "dataset.inspect", "input_schema": {"type": "object"}}],
    )

    try:
        provider.decide("Inspect only", [])
    except ModelProviderError as exc:
        assert exc.code == "malformed_response"
        assert "outside the supplied tool set" in str(exc)
    else:
        raise AssertionError("An Ollama decision cannot escape the supplied tool set.")


def test_ollama_provider_maps_timeout_and_unavailable_without_source_content() -> None:
    for error, expected_code, expected_message in (
        (TimeoutError("sensitive prompt text"), "provider_timeout", "Orchestrator provider timed out."),
        (ConnectionError("sensitive prompt text"), "provider_unavailable", "Orchestrator provider is unavailable."),
    ):
        transport = RecordingTransport(error=error)
        provider = _provider(transport, retries=1)
        try:
            provider.decide("private goal", [])
        except ModelProviderError as exc:
            assert exc.code == expected_code
            assert str(exc) == expected_message
            assert "sensitive" not in str(exc)
            assert len(transport.calls) == 2
        else:
            raise AssertionError("Ollama transport failures must map to stable safe errors.")


def test_ollama_provider_parses_local_usage_and_runtime_metrics() -> None:
    provider = _provider(
        RecordingTransport(
            _response(
                {"type": "complete", "answer": "Ready", "claims": []},
                prompt_eval_count=120,
                eval_count=30,
                load_duration=250_000_000,
                prompt_eval_duration=600_000_000,
                eval_duration=2_000_000_000,
            )
        )
    )

    decision = provider.decide("Finish", [])

    assert isinstance(decision, Complete)
    metrics = provider.last_call_metrics
    assert metrics is not None
    assert metrics.input_tokens == 120
    assert metrics.output_tokens == 30
    assert metrics.total_tokens == 150
    assert metrics.load_duration_ms == 250
    assert metrics.prompt_eval_duration_ms == 600
    assert metrics.output_eval_duration_ms == 2000
    assert metrics.output_tokens_per_second == 15


def test_ollama_provider_rejects_remote_or_credentialed_base_urls() -> None:
    for url in (
        "http://169.254.169.254:11434/api",
        "https://ollama.example/api",
        "http://user:password@127.0.0.1:11434/api",
        "http://127.0.0.1:11434/api?target=private",
        "http://127.0.0.1:11434/other",
    ):
        try:
            _provider(RecordingTransport(), base_url=url)
        except ValueError as exc:
            assert "password" not in str(exc)
            assert "target" not in str(exc)
        else:
            raise AssertionError("Unsafe Ollama base URLs must fail closed.")


def test_ollama_transport_disables_redirects_and_environment_proxies() -> None:
    redirect_handler = next(handler for handler in _OLLAMA_URL_OPENER.handlers if isinstance(handler, _NoOllamaRedirects))

    assert redirect_handler.redirect_request(None, None, 302, "Found", {}, "http://remote.invalid") is None
    assert not any(isinstance(handler, ProxyHandler) for handler in _OLLAMA_URL_OPENER.handlers)


def test_ollama_provider_bounds_serialized_context() -> None:
    provider = _provider(RecordingTransport(_response({"type": "complete", "answer": "Ready"})))
    observation = ToolObservation(success=True, summary="bounded", result={"values": ["x" * 12_001]})

    decision = provider.decide("Finish", [observation])

    assert isinstance(decision, Complete)
    sent = json.loads(provider._transport.calls[0][1]["messages"][1]["content"])
    assert all(value.endswith("<truncated>") for value in sent["observations"][0]["result"]["values"])


def test_ollama_provider_rejects_total_context_overflow_before_transport() -> None:
    transport = RecordingTransport(_response({"type": "complete", "answer": "Ready"}))
    provider = _provider(transport)
    observation = ToolObservation(success=True, summary="bounded", result={"values": ["x" * 12_001] * 3})

    try:
        provider.decide("Finish", [observation])
    except ModelProviderError as exc:
        assert exc.code == "provider_input_too_large"
        assert "safety bound" in str(exc)
        assert transport.calls == []
    else:
        raise AssertionError("Oversized Ollama context must fail before making a request.")
