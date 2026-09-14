"""Runtime selection, provider adapter, and public grades workflow integration tests."""

import base64
import json
import logging
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import httpx
from openai import APITimeoutError, BadRequestError, OpenAI, OpenAIError

from app.agent.models import Complete, ModelDecisionEnvelope, ToolCall
from app.agent.providers import OllamaModelProvider, OpenAIModelProvider
from app.agent.tools import ToolRegistry, dataset_tools
from app.config import ConfigurationError, Settings, get_settings
from app.dependencies import _demo_repository, _deterministic_provider, build_orchestrator_provider
from app.main import app
from app.repositories.executions import InMemoryExecutionRepository
from app.services.artifacts import InMemoryArtifactRepository
from app.services.workflows import InMemoryWorkflowRepository, WorkflowService


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
        result = self.result
        if isinstance(result, ModelDecisionEnvelope):
            result = _wire_decision(kwargs["text_format"], result.decision)
        return SimpleNamespace(output_parsed=result, usage=self.usage)


class _Client:
    def __init__(self, responses: _Responses) -> None:
        self.responses = responses


class _SequentialResponses:
    def __init__(self, decisions: list[ToolCall | Complete]) -> None:
        self._decisions = iter(decisions)
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_parsed=_wire_decision(kwargs["text_format"], next(self._decisions)),
            usage=SimpleNamespace(input_tokens=100, output_tokens=10, total_tokens=110),
        )


def _wire_decision(response_model, decision: ToolCall | Complete):
    if isinstance(decision, ToolCall):
        payload = {
            "type": "tool_call",
            "tool": decision.tool,
            "arguments_json": json.dumps(decision.arguments, separators=(",", ":")),
        }
    else:
        payload = decision.model_dump(mode="json")
    return response_model.model_validate({"decision": payload})


_UNSUPPORTED_OPENAI_SCHEMA_KEYWORDS = {
    "oneOf",
    "minLength",
    "maxLength",
    "allOf",
    "not",
    "dependentRequired",
    "dependentSchemas",
    "if",
    "then",
    "else",
}


def _strict_schema_violations(value, path: str = "$") -> list[str]:
    violations: list[str] = []
    if isinstance(value, dict):
        for keyword in _UNSUPPORTED_OPENAI_SCHEMA_KEYWORDS.intersection(value):
            violations.append(f"{path}: unsupported {keyword}")
        if value.get("type") == "object":
            properties = value.get("properties")
            if not isinstance(properties, dict):
                violations.append(f"{path}: missing properties")
            else:
                required = value.get("required")
                if not isinstance(required, list) or set(required) != set(properties):
                    violations.append(f"{path}: not all properties required")
            if value.get("additionalProperties") is not False:
                violations.append(f"{path}: object is not closed")
        for key, nested in value.items():
            violations.extend(_strict_schema_violations(nested, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            violations.extend(_strict_schema_violations(nested, f"{path}[{index}]"))
    return violations


def _tool_name_constants(value) -> set[str]:
    names: set[str] = set()
    if isinstance(value, dict):
        tool_schema = value.get("properties", {}).get("tool")
        if isinstance(tool_schema, dict) and isinstance(tool_schema.get("const"), str):
            names.add(tool_schema["const"])
        for nested in value.values():
            names.update(_tool_name_constants(nested))
    elif isinstance(value, list):
        for nested in value:
            names.update(_tool_name_constants(nested))
    return names


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
        assert "cannot contain credentials" in str(exc)
        assert "password" not in str(exc)
    else:
        raise AssertionError("Base URLs with embedded credentials must fail configuration validation.")


def test_orchestrator_base_url_requires_https_except_literal_loopback(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "demo")

    for accepted in (
        "https://api.openai.com/v1",
        "https://compatible.example/v1",
        "http://localhost:8080/v1",
        "http://127.0.0.1:8080/v1",
        "http://[::1]:8080/v1",
    ):
        monkeypatch.setenv("ORCHESTRATOR_BASE_URL", accepted)
        assert Settings.from_env().orchestrator_base_url == accepted

    for rejected in (
        "http://example.com/v1",
        "http://8.8.8.8/v1",
        "https://user:password@compatible.example/v1",
        "https://compatible.example/v1?token=fake",
        "https://compatible.example/v1#fragment",
        "https://compatible.example:not-a-port/v1",
        "https://compatible.example:/v1",
        "https://[::1",
    ):
        monkeypatch.setenv("ORCHESTRATOR_BASE_URL", rejected)
        try:
            Settings.from_env()
        except ConfigurationError as exc:
            assert rejected not in str(exc)
        else:
            raise AssertionError(f"Unsafe provider URL must fail configuration validation: {rejected}")


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


def test_openai_provider_builds_supported_strict_schema_from_allowed_tools() -> None:
    responses = _Responses(ModelDecisionEnvelope(decision=Complete(answer="Ready")))
    provider = OpenAIModelProvider(
        "test-key",
        "test-model",
        [
            {"name": "resource.list", "description": "List resources.", "input_schema": {"type": "object"}},
            {
                "name": "analytics.execute",
                "description": "Run deterministic analytics.",
                "input_schema": {
                    "type": "object",
                    "properties": {"dataset": {"type": "string"}, "plan": {"type": "object"}},
                },
            },
        ],
        3.0,
        0,
        client=_Client(responses),
    )

    assert provider.decide("Finish", []).answer == "Ready"

    response_model = responses.kwargs["text_format"]
    schema = response_model.model_json_schema()
    assert response_model is not ModelDecisionEnvelope
    assert response_model.__name__ == "ModelDecisionEnvelope"
    assert schema["type"] == "object"
    assert "anyOf" not in schema
    assert _strict_schema_violations(schema) == []
    assert "anyOf" in schema["properties"]["decision"]
    variants = schema["properties"]["decision"]["anyOf"]
    assert len(variants) == 3
    assert "arguments_json" in json.dumps(schema)
    assert '"arguments"' not in json.dumps(schema)


def test_openai_provider_serializes_strict_schema_through_real_sdk_offline() -> None:
    captured: dict = {}
    allowed_tools = {"resource.list", "dataset.inspect"}

    def respond(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "resp_offline_test",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "model": "test-model",
                "output": [
                    {
                        "id": "msg_offline_test",
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "annotations": [],
                                "text": '{"decision":{"type":"complete","answer":"Ready","claims":[]}}',
                            }
                        ],
                    }
                ],
                "parallel_tool_calls": False,
                "tools": [],
                "usage": {
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "total_tokens": 2,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
            },
        )

    sdk_client = OpenAI(
        api_key="offline-test-key",
        base_url="https://offline.invalid/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    try:
        provider = OpenAIModelProvider(
            "offline-test-key",
            "test-model",
            [
                {"name": "resource.list", "input_schema": {"type": "object"}},
                {"name": "dataset.inspect", "input_schema": {"type": "object"}},
            ],
            3.0,
            0,
            client=sdk_client,
        )
        assert provider.decide("Finish", []).answer == "Ready"
    finally:
        sdk_client.close()

    response_format = captured["text"]["format"]
    serialized_schema = json.dumps(response_format["schema"], separators=(",", ":"))
    assert response_format["type"] == "json_schema"
    assert response_format["strict"] is True
    assert response_format["name"] == "ModelDecisionEnvelope"
    assert response_format["schema"]["type"] == "object"
    assert "anyOf" not in response_format["schema"]
    assert _strict_schema_violations(response_format["schema"]) == []
    assert _tool_name_constants(response_format["schema"]) == allowed_tools
    assert "workflow.delete" not in serialized_schema


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


def test_openai_provider_logs_controlled_metadata_without_upstream_text_or_secrets(caplog) -> None:
    sensitive_values = (
        "sk-test-secret-long-value",
        "@",
        "password=fake-password",
        "token=fake-token",
        "private validation goal",
        "provider-freeform-type",
        "provider-freeform-code",
        "provider-freeform-body",
    )

    with caplog.at_level(logging.WARNING, logger="app.agent.providers"):
        for api_key in sensitive_values[:2]:
            request = httpx.Request("POST", "https://api.openai.com/v1/responses?token=fake-token")
            response = httpx.Response(400, request=request, headers={"x-request-id": "req_schema_123"})
            upstream = BadRequestError(
                " ".join(sensitive_values),
                response=response,
                body={
                    "type": sensitive_values[5],
                    "code": sensitive_values[6],
                    "message": sensitive_values[7],
                },
            )
            provider = OpenAIModelProvider(
                api_key,
                "test-model",
                [],
                3.0,
                0,
                client=_Client(_Responses(error=upstream)),
            )
            try:
                provider.decide(sensitive_values[4], [])
            except RuntimeError as exc:
                assert exc.code == "provider_failure"
                assert str(exc) == "Orchestrator provider request failed."
            else:
                raise AssertionError("The provider error must still fail closed.")

    logged = caplog.text
    assert logged.count("openai_provider_error") == 2
    assert '"exception":"BadRequestError"' in logged
    assert '"status":400' in logged
    assert '"request_id":"req_schema_123"' in logged
    assert '"error_code":"provider_failure"' in logged
    for sensitive in sensitive_values:
        assert sensitive not in logged


def test_openai_provider_drops_unbounded_provider_request_id(caplog) -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(400, request=request, headers={"x-request-id": "arbitrary free-form identifier"})
    upstream = BadRequestError("provider text", response=response, body={"message": "provider body"})
    provider = OpenAIModelProvider(
        "x",
        "test-model",
        [],
        3.0,
        0,
        client=_Client(_Responses(error=upstream)),
    )

    with caplog.at_level(logging.WARNING, logger="app.agent.providers"):
        try:
            provider.decide("private validation goal", [])
        except RuntimeError:
            pass
        else:
            raise AssertionError("The provider error must still fail closed.")

    assert '"request_id":null' in caplog.text
    assert "arbitrary free-form identifier" not in caplog.text
    assert "provider text" not in caplog.text
    assert "provider body" not in caplog.text


def test_openai_provider_rejects_unsafe_direct_configuration() -> None:
    invalid = (
        {"base_url": "https://user:secret@provider.invalid/v1"},
        {"base_url": "https://provider.invalid/v1?token=fake"},
        {"base_url": "https://provider.invalid/v1#fragment"},
        {"base_url": "https://provider.invalid:not-a-port/v1"},
        {"base_url": "https://provider.invalid:/v1"},
        {"base_url": "https://[::1"},
        {"base_url": "http://example.com/v1"},
        {"base_url": "http://8.8.8.8/v1"},
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


def test_openai_provider_accepts_https_and_literal_loopback_http() -> None:
    for base_url in (
        "https://api.openai.com/v1",
        "https://compatible.example/v1",
        "http://localhost:8080/v1",
        "http://127.0.0.1:8080/v1",
        "http://[::1]:8080/v1",
    ):
        provider = OpenAIModelProvider(
            "test-key",
            "test-model",
            [],
            3.0,
            0,
            base_url=base_url,
            client=_Client(_Responses(ModelDecisionEnvelope(decision=Complete(answer="Ready")))),
        )
        assert provider.decide("Finish", []).answer == "Ready"


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


def test_openai_provider_rejects_malformed_encoded_tool_arguments() -> None:
    for arguments_json in (
        "",
        "   ",
        "not-json",
        "[]",
        '{"dataset":"first.csv","dataset":"second.csv"}',
        '{"threshold":NaN}',
        "{}" + (" " * 100_000),
    ):
        provider = OpenAIModelProvider(
            "test-key",
            "test-model",
            [{"name": "dataset.inspect", "input_schema": {"type": "object"}}],
            3.0,
            0,
            client=_Client(
                _Responses(
                    result={
                        "decision": {
                            "type": "tool_call",
                            "tool": "dataset.inspect",
                            "arguments_json": arguments_json,
                        }
                    }
                )
            ),
        )

        try:
            provider.decide("Inspect", [])
        except RuntimeError as exc:
            assert exc.code == "malformed_response"
            assert str(exc) == "Orchestrator provider returned malformed structured output."
        else:
            raise AssertionError("Malformed encoded arguments must fail closed.")


def test_openai_provider_applies_canonical_validation_after_wire_decode() -> None:
    provider = OpenAIModelProvider(
        "test-key",
        "test-model",
        [],
        3.0,
        0,
        client=_Client(
            _Responses(
                result={
                    "decision": {
                        "type": "complete",
                        "answer": "",
                        "claims": [],
                    }
                }
            )
        ),
    )

    try:
        provider.decide("Finish", [])
    except RuntimeError as exc:
        assert exc.code == "malformed_response"
    else:
        raise AssertionError("Canonical response validation must remain authoritative after wire parsing.")


def test_openai_provider_rejects_tool_outside_supplied_registry() -> None:
    provider = OpenAIModelProvider(
        "test-key",
        "test-model",
        [{"name": "dataset.inspect", "input_schema": {"type": "object"}}],
        3.0,
        0,
        client=_Client(
            _Responses(
                result={
                    "decision": {
                        "type": "tool_call",
                        "tool": "sql.execute",
                        "arguments_json": "{}",
                    }
                }
            )
        ),
    )

    try:
        provider.decide("Inspect", [])
    except RuntimeError as exc:
        assert exc.code == "malformed_response"
    else:
        raise AssertionError("A tool outside the supplied registry must fail closed.")


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


def test_production_api_executes_through_openai_adapter_and_persists_usage(monkeypatch, tmp_path) -> None:
    responses = _SequentialResponses(
        [
            ToolCall(tool="resource.list", arguments={}),
            ToolCall(tool="dataset.inspect", arguments={"dataset": "sales.csv"}),
            ToolCall(
                tool="analytics.execute",
                arguments={
                    "dataset": "sales.csv",
                    "plan": {
                        "analysis": "metrics",
                        "group_by": ["region"],
                        "metrics": [{"name": "sum", "column": "amount", "alias": "total_amount"}],
                        "expected_columns": ["region", "amount"],
                    },
                },
            ),
            Complete(answer="The bound sales dataset was inspected and analyzed deterministically."),
        ]
    )
    captured_client_options: dict = {}

    def build_client(**kwargs):
        captured_client_options.update(kwargs)
        return _Client(responses)

    artifacts = InMemoryArtifactRepository()
    executions = InMemoryExecutionRepository()
    workflows = WorkflowService(InMemoryWorkflowRepository(), ToolRegistry(dataset_tools()), artifacts)
    monkeypatch.setattr("app.agent.providers.OpenAI", build_client)
    monkeypatch.setattr("app.api.agent.get_artifact_repository", lambda settings: artifacts)
    monkeypatch.setattr("app.api.agent.get_execution_repository", lambda settings: executions)
    monkeypatch.setattr("app.api.agent.get_workflow_service", lambda settings: workflows)
    monkeypatch.setenv("APP_MODE", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured.invalid/workspace")
    monkeypatch.setenv("ARTIFACT_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "embedding-secret")
    monkeypatch.setenv("ORCHESTRATOR_PROVIDER", "openai")
    monkeypatch.setenv("ORCHESTRATOR_API_KEY", "orchestrator-secret")
    monkeypatch.setenv("ORCHESTRATOR_MODEL", "hosted-test-model")
    _clear_runtime_caches()

    try:
        response = TestClient(app).post(
            "/agent/tasks",
            json={
                "goal": "Inspect the bound sales dataset and sum amount by region.",
                "resources": {
                    "datasets": [
                        {
                            "filename": "sales.csv",
                            "content_base64": base64.b64encode(b"region,amount\nNorth,100\n").decode("ascii"),
                        }
                    ]
                },
            },
        )
    finally:
        _clear_runtime_caches()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert [step["requested_tool"] for step in body["trace"]] == [
        "resource.list",
        "dataset.inspect",
        "analytics.execute",
    ]
    assert body["trace"][2]["success"] is True
    assert body["provider_usage"] == {
        "provider": "openai",
        "model": "hosted-test-model",
        "provider_calls": 4,
        "latency_ms": body["provider_usage"]["latency_ms"],
        "input_tokens": 400,
        "output_tokens": 40,
        "total_tokens": 440,
        "approximate_cost_usd": None,
        "cost_basis": None,
    }
    assert body["provider_usage"]["latency_ms"] >= 0
    assert body["task_id"] in {str(task_id) for task_id in executions.executions}
    assert "api_key" in captured_client_options
    assert captured_client_options["timeout"] == 30.0
    assert captured_client_options["max_retries"] == 2
    assert len(responses.calls) == 4
    assert all(call["text_format"].__name__ == "ModelDecisionEnvelope" for call in responses.calls)
    assert all(call["text_format"] is not ModelDecisionEnvelope for call in responses.calls)
    assert all(call["store"] is False and call["parallel_tool_calls"] is False for call in responses.calls)
    assert all("orchestrator-secret" not in call["input"] for call in responses.calls)


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
