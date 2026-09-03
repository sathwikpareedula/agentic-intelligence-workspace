"""Runtime selection, provider adapter, and public grades workflow integration tests."""

import base64
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from openai import OpenAIError

from app.agent.models import Complete, ModelDecisionEnvelope, ToolCall
from app.agent.providers import OpenAIModelProvider
from app.config import ConfigurationError, Settings, get_settings
from app.dependencies import _demo_repository, _deterministic_provider
from app.main import app


ROOT = Path(__file__).parents[2]


class _Responses:
    def __init__(self, result=None, error=None) -> None:
        self.result = result
        self.error = error
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return SimpleNamespace(output_parsed=self.result)


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
    assert "secret-not-sent-in-payload" not in responses.kwargs["input"]


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
        assert str(exc) == "OpenAI orchestrator request failed."
        assert "provider detail" not in str(exc)
    else:
        raise AssertionError("Provider errors must be mapped to a stable public-safe error.")


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
