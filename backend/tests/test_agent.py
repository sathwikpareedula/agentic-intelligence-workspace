"""Tests for the bounded single orchestrator and typed tool system."""

import base64

from fastapi.testclient import TestClient
from pydantic import Field

from app.agent.models import Complete, ToolCall, ToolObservation
from app.agent.orchestrator import AgentOrchestrator
from app.agent.providers import FakeModelProvider
from app.agent.tools import ToolInput, ToolRegistry, TypedTool, dataset_tools
from app.main import app


class NumberInput(ToolInput):
    value: int = Field(ge=0)


def _number_tool(fail_once: bool = False):
    calls = 0

    def run(arguments: NumberInput) -> ToolObservation:
        nonlocal calls
        calls += 1
        if fail_once and calls == 1:
            raise RuntimeError("temporary failure")
        return ToolObservation(
            success=True,
            summary=f"Observed {arguments.value}.",
            result={"value": arguments.value},
            artifact_ids=["artifact-1"],
            source_ids=["source-1"],
        )

    return TypedTool("number.read", "Read a bounded number.", NumberInput, run)


def test_successful_multistep_execution_has_complete_trace() -> None:
    provider = FakeModelProvider(
        [ToolCall(tool="number.read", arguments={"value": 2}), ToolCall(tool="number.read", arguments={"value": 3}), Complete(answer="Done")]
    )
    result = AgentOrchestrator(provider, ToolRegistry([_number_tool()])).execute("Read two numbers")

    assert result.status == "completed"
    assert result.answer == "Done"
    assert [step.step for step in result.trace] == [1, 2]
    assert result.trace[0].validated_arguments == {"value": 2}
    assert result.trace[0].artifact_ids == ["artifact-1"]
    assert result.trace[0].source_ids == ["source-1"]
    assert result.trace[0].duration_ms >= 0


def test_invalid_arguments_and_unknown_tool_are_observed_for_replanning() -> None:
    provider = FakeModelProvider(
        [
            ToolCall(tool="number.read", arguments={"value": -1}),
            ToolCall(tool="missing", arguments={}),
            ToolCall(tool="number.read", arguments={"value": 4}),
            Complete(answer="Recovered"),
        ]
    )
    result = AgentOrchestrator(provider, ToolRegistry([_number_tool()])).execute("Recover")

    assert result.status == "completed"
    assert [step.error_code for step in result.trace] == ["invalid_arguments", "unknown_tool", None]
    assert result.trace[0].validated_arguments is None


def test_recoverable_tool_failure_can_be_replanned() -> None:
    provider = FakeModelProvider(
        [ToolCall(tool="number.read", arguments={"value": 1}), ToolCall(tool="number.read", arguments={"value": 1}), Complete(answer="Recovered")]
    )
    result = AgentOrchestrator(provider, ToolRegistry([_number_tool(fail_once=True)])).execute("Retry")

    assert [step.success for step in result.trace] == [False, True]
    assert result.trace[0].error_code == "tool_error"
    assert result.status == "completed"


def test_iteration_limit_stops_unbounded_agent() -> None:
    provider = FakeModelProvider([ToolCall(tool="number.read", arguments={"value": 1}) for _ in range(4)])
    result = AgentOrchestrator(provider, ToolRegistry([_number_tool()])).execute("Loop", max_iterations=3)

    assert result.status == "iteration_limit"
    assert len(result.trace) == 3
    assert "3-iteration" in result.failure_reason


def test_existing_dataset_capability_is_wrapped_without_file_body_in_trace() -> None:
    encoded = base64.b64encode(b"name,score\nAda,91\nLin,88\n").decode()
    provider = FakeModelProvider([ToolCall(tool="dataset.inspect", arguments={"filename": "grades.csv", "content_base64": encoded}), Complete(answer="Inspected")])
    result = AgentOrchestrator(provider, ToolRegistry(dataset_tools())).execute("Inspect grades")

    assert result.trace[0].success is True
    assert result.trace[0].validated_arguments["content_base64"].startswith("<redacted:")
    assert result.status == "completed"


def test_agent_api_boundary_and_validation() -> None:
    client = TestClient(app)
    unavailable = client.post("/agent/tasks", json={"goal": "Do work"})
    invalid = client.post("/agent/tasks", json={"goal": "", "max_iterations": 0})
    assert unavailable.status_code == 503
    assert invalid.status_code == 422

    app.state.agent_orchestrator = AgentOrchestrator(FakeModelProvider([Complete(answer="Finished")]), ToolRegistry())
    try:
        response = client.post("/agent/tasks", json={"goal": "Do work"})
        assert response.status_code == 200
        assert response.json()["status"] == "completed"
    finally:
        del app.state.agent_orchestrator
