"""Runtime selection, provider adapter, and public grades workflow integration tests."""

import base64
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import httpx
from openai import APITimeoutError, OpenAIError

from app.agent.models import Complete, ModelDecisionEnvelope, ToolCall
from app.agent.providers import OllamaModelProvider, OpenAIModelProvider
from app.config import ConfigurationError, Settings, get_settings
from app.dependencies import _demo_repository, _deterministic_provider, build_orchestrator_provider
from app.main import app


ROOT = Path(__file__).parents[2]


class _Responses:
    def __init__(self, result=None, error=None, usage=None) -> None:
        self.result = result
        self.error = error
        self.usage = usage
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return SimpleNamespace(output_parsed=self.result, usage=self.usage)


class _Client:
    def __init__(self, responses: _Responses) -> None:
        self.responses = responses


def _clear_runtime_caches() -> None:
    get_settings.cache_clear()
    _demo_repository.cache_clear()
    _deterministic_provider.cache_clear()


def test_settings_require_explicit_valid_mode(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "demo")
    assert Settings.from_env().app_mode == "demo"

    monkeypatch.setenv("APP_MODE", "automatic")
    try:
        Settings.from_env()
    except ConfigurationError as exc:
        assert "APP_MODE must be one of" in str(exc)
    else:
        raise AssertionError("An ambiguous runtime mode must fail configuration validation.")


def test_orchestrator_settings_support_dedicated_key_and_credential_free_base_url(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "demo")
    monkeypatch.setenv("ORCHESTRATOR_API_KEY", "dedicated-secret")
    monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "https://compatible.example/v1/")
    monkeypatch.setenv("ORCHESTRATOR_MODEL", "compatible-model")

    settings = Settings.from_env()

    assert settings.orchestrator_api_key == "dedicated-secret"
    assert settings.orchestrator_base_url == "https://compatible.example/v1"
    assert settings.orchestrator_model == "compatible-model"

    monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "https://user:password@compatible.example/v1")
    try:
        Settings.from_env()
    except ConfigurationError as exc:
        assert "without embedded credentials" in str(exc)
        assert "password" not in str(exc)
    else:
        raise AssertionError("Base URLs with embedded credentials must fail configuration validation.")


def test_orchestrator_settings_bound_provider_resource_controls(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "demo")
    for name, value, expected in (
        ("ORCHESTRATOR_TIMEOUT_SECONDS", "121", "at most 120"),
        ("ORCHESTRATOR_MAX_RETRIES", "6", "at most 5"),
        ("ORCHESTRATOR_MAX_OUTPUT_TOKENS", "20001", "at most 20000"),
    ):
        monkeypatch.setenv(name, value)
        try:
            Settings.from_env()
        except ConfigurationError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError(f"{name} must have an enforced upper bound.")
        monkeypatch.delenv(name)

    monkeypatch.setenv("ORCHESTRATOR_INPUT_COST_PER_MILLION", "2")
    try:
        Settings.from_env()
    except ConfigurationError as exc:
        assert "both orchestrator cost rates" in str(exc)
    else:
        raise AssertionError("Partial provider pricing must fail closed.")
    monkeypatch.setenv("ORCHESTRATOR_OUTPUT_COST_PER_MILLION", "8")
    settings = Settings.from_env()
    assert settings.orchestrator_input_cost_per_million == 2
    assert settings.orchestrator_output_cost_per_million == 8


def test_ollama_settings_are_keyless_local_and_reject_remote_or_cost_configuration(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "production")
    monkeypatch.setenv("ORCHESTRATOR_PROVIDER", "ollama")
    monkeypatch.setenv("ORCHESTRATOR_MODEL", "gemma3:4b")
    monkeypatch.delenv("ORCHESTRATOR_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)

    settings = Settings.from_env()
    provider = build_orchestrator_provider(settings, [])
    assert settings.orchestrator_api_key is None
    assert isinstance(provider, OllamaModelProvider)
    assert provider.model_name == "gemma3:4b"

    monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "http://metadata.google.internal:11434/api")
    try:
        Settings.from_env()
    except ConfigurationError as exc:
        assert "loopback Ollama" in str(exc)
    else:
        raise AssertionError("Remote Ollama URLs must fail closed.")

    monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "http://localhost:11434/api")
    monkeypatch.setenv("ORCHESTRATOR_INPUT_COST_PER_MILLION", "0")
    monkeypatch.setenv("ORCHESTRATOR_OUTPUT_COST_PER_MILLION", "0")
    try:
        Settings.from_env()
    except ConfigurationError as exc:
        assert "monetary token rates" in str(exc)
    else:
        raise AssertionError("Local execution must not report invented monetary cost.")


def test_cors_origins_are_explicit_bounded_and_credential_free(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "demo")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://workspace.example, http://localhost:3000/")
    assert Settings.from_env().cors_allowed_origins == (
        "https://workspace.example",
        "http://localhost:3000",
    )

    for invalid in (
        "*",
        "https://user:secret@workspace.example",
        "https://workspace.example/application",
        "https://workspace.example?token=secret",
        "https://workspace.example:not-a-port",
        "https://workspace.example,https://workspace.example",
    ):
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", invalid)
        try:
            Settings.from_env()
        except ConfigurationError as exc:
            assert "secret" not in str(exc)
        else:
            raise AssertionError("Unsafe or ambiguous CORS origins must fail configuration validation.")


def test_openai_provider_validates_structured_decisions_without_logging_credentials() -> None:
    responses = _Responses(ModelDecisionEnvelope(decision=ToolCall(tool="dataset.inspect", arguments={})))
    provider = OpenAIModelProvider(
        "secret-not-sent-in-payload",
        "test-model",
        [{"name": "dataset.inspect", "input_schema": {"type": "object"}}],
        3.0,
        1,
        client=_Client(responses),
    )

    decision = provider.decide("Inspect", [])

    assert decision.tool == "dataset.inspect"
    assert responses.kwargs["model"] == "test-model"
    assert responses.kwargs["store"] is False
    assert responses.kwargs["parallel_tool_calls"] is False
    assert responses.kwargs["max_output_tokens"] == 3000
    assert "secret-not-sent-in-payload" not in responses.kwargs["input"]


def test_openai_provider_configures_base_url_timeout_and_sdk_retries(monkeypatch) -> None:
    captured = {}

    def build_client(**kwargs):
        captured.update(kwargs)
        return _Client(_Responses(ModelDecisionEnvelope(decision=Complete(answer="Ready"))))

    monkeypatch.setattr("app.agent.providers.OpenAI", build_client)
    provider = OpenAIModelProvider(
        "private-key",
        "compatible-model",
        [],
        7.5,
        3,
        "https://compatible.example/v1",
        2048,
    )

    assert provider.decide("Finish", []).answer == "Ready"
    assert "api_key" in captured
    assert captured["base_url"] == "https://compatible.example/v1"
    assert captured["timeout"] == 7.5
    assert captured["max_retries"] == 3


def test_openai_provider_exposes_only_non_sensitive_call_metrics() -> None:
    responses = _Responses(
        ModelDecisionEnvelope(decision=Complete(answer="Ready")),
        usage=SimpleNamespace(input_tokens=125, output_tokens=25, total_tokens=150),
    )
    provider = OpenAIModelProvider(
        "private-key",
        "test-model",
        [],
        3.0,
        0,
        client=_Client(responses),
    )

    assert provider.decide("Finish", []).answer == "Ready"
    metrics = provider.last_call_metrics
    assert metrics is not None
    assert metrics.input_tokens == 125
    assert metrics.output_tokens == 25
    assert metrics.total_tokens == 150
    assert metrics.latency_ms >= 0
    assert "private-key" not in repr(metrics)


def test_openai_provider_maps_provider_errors() -> None:
    provider = OpenAIModelProvider(
        "test-key",
        "test-model",
        [],
        3.0,
        0,
        client=_Client(_Responses(error=OpenAIError("provider detail"))),
    )

    try:
        provider.decide("Inspect", [])
    except RuntimeError as exc:
        assert str(exc) == "Orchestrator provider request failed."
        assert exc.code == "provider_failure"
        assert "provider detail" not in str(exc)
    else:
        raise AssertionError("Provider errors must be mapped to a stable public-safe error.")


def test_openai_provider_rejects_unsafe_direct_configuration() -> None:
    invalid = (
        {"base_url": "https://user:secret@provider.invalid/v1"},
        {"timeout_seconds": 121},
        {"max_retries": 6},
        {"max_output_tokens": 20_001},
    )
    for override in invalid:
        options = {
            "api_key": "test-key",
            "model": "test-model",
            "tool_specifications": [],
            "timeout_seconds": 3.0,
            "max_retries": 0,
            "max_output_tokens": 3000,
            "client": _Client(_Responses()),
            **override,
        }
        try:
            OpenAIModelProvider(**options)
        except ValueError as exc:
            assert "secret" not in str(exc)
        else:
            raise AssertionError("Unsafe direct provider configuration must fail closed.")


def test_openai_provider_rejects_malformed_structured_output() -> None:
    provider = OpenAIModelProvider(
        "test-key",
        "test-model",
        [],
        3.0,
        0,
        client=_Client(_Responses(result={"decision": {"type": "tool_call", "tool": "x", "arguments": [], "extra": True}})),
    )

    try:
        provider.decide("Inspect", [])
    except RuntimeError as exc:
        assert exc.code == "malformed_response"
        assert "malformed structured output" in str(exc)
    else:
        raise AssertionError("Malformed provider output must fail closed.")


def test_openai_provider_maps_timeout_without_exposing_request_details() -> None:
    timeout = APITimeoutError(httpx.Request("POST", "https://provider.invalid/v1/responses?token=secret"))
    provider = OpenAIModelProvider(
        "test-key",
        "test-model",
        [],
        1.0,
        0,
        client=_Client(_Responses(error=timeout)),
    )

    try:
        provider.decide("Inspect", [])
    except RuntimeError as exc:
        assert exc.code == "provider_timeout"
        assert str(exc) == "Orchestrator provider timed out."
        assert "secret" not in str(exc)
    else:
        raise AssertionError("Provider timeouts must be mapped to a stable public-safe error.")


def test_runtime_reports_demo_configured_and_unavailable_provider_states(monkeypatch, tmp_path) -> None:
    client = TestClient(app)

    monkeypatch.setenv("APP_MODE", "demo")
    _clear_runtime_caches()
    assert client.get("/runtime").json()["orchestrator_status"] == "demo"

    monkeypatch.setenv("APP_MODE", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured.invalid/workspace")
    monkeypatch.setenv("ARTIFACT_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "embedding-secret")
    monkeypatch.setenv("ORCHESTRATOR_API_KEY", "orchestrator-secret")
    monkeypatch.setenv("ORCHESTRATOR_PROVIDER", "openai")
    _clear_runtime_caches()
    configured = client.get("/runtime").json()
    assert configured["status"] == "ready"
    assert configured["orchestrator_status"] == "configured"
    assert "secret" not in str(configured)

    monkeypatch.setenv("ORCHESTRATOR_PROVIDER", "ollama")
    monkeypatch.setenv("ORCHESTRATOR_MODEL", "gemma3:4b")
    monkeypatch.delenv("ORCHESTRATOR_API_KEY")
    _clear_runtime_caches()
    local = client.get("/runtime").json()
    assert local["orchestrator_provider"] == "ollama"
    assert local["orchestrator_status"] == "configured"
    assert local["orchestrator_model"] == "gemma3:4b"

    monkeypatch.setenv("ORCHESTRATOR_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY")
    _clear_runtime_caches()
    unavailable = client.get("/runtime").json()
    assert unavailable["status"] == "not_ready"
    assert unavailable["orchestrator_status"] == "unavailable"
    _clear_runtime_caches()


def test_demo_mode_grades_workflow_through_public_http_api(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "demo")
    _clear_runtime_caches()
    client = TestClient(app)
    grades = (ROOT / "sample_data" / "grades.csv").read_bytes()
    syllabus = (ROOT / "sample_data" / "syllabus.pdf").read_bytes()

    try:
        runtime = client.get("/runtime")
        inspected = client.post("/datasets/inspect", files={"file": ("grades.csv", grades, "text/csv")})
        ingested = client.post("/documents", files={"file": ("syllabus.pdf", syllabus, "application/pdf")})
        assert runtime.status_code == 200
        assert runtime.json()["mode"] == "demo"
        assert client.get("/ready").status_code == 200
        assert inspected.status_code == 200
        assert ingested.status_code == 201

        task = client.post(
            "/agent/tasks",
            json={
                "goal": "According to the grading policy, what score do I need on my final to finish with an A?",
                "resources": {
                    "dataset": {
                        "filename": "grades.csv",
                        "content_base64": base64.b64encode(grades).decode("ascii"),
                    },
                    "document_id": ingested.json()["document_id"],
                },
            },
        )
    finally:
        _clear_runtime_caches()

    assert task.status_code == 200
    body = task.json()
    assert body["status"] == "completed"
    assert "94.67%" in body["answer"]
    assert [step["requested_tool"] for step in body["trace"]] == [
        "dataset.inspect",
        "document.search",
        "grades.required_final",
    ]
    assert body["verification"]["status"] == "verified"
    assert body["citations"][0]["filename"] == "syllabus.pdf"
    assert body["citations"][0]["page_number"] == 1
