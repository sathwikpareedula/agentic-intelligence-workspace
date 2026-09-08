"""Reusable deterministic workflow recipe tests."""

import base64
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from app.agent.models import AgentTaskResources, ToolObservation
from app.agent.tools import ToolRegistry, dataset_tools, general_task_tools
from app.main import app
from app.models.workflows import (
    RunFact,
    RunArtifact,
    RunVerificationSummary,
    WorkflowCreate,
    WorkflowRun,
    WorkflowStep,
)
from app.services.artifacts import InMemoryArtifactRepository
from app.services.workflows import InMemoryWorkflowRepository, WorkflowError, WorkflowService


def _encoded(content: bytes) -> str:
    return base64.b64encode(content).decode()


def test_workflow_execute_save_rerun_and_schema_drift() -> None:
    registry = ToolRegistry(dataset_tools())
    service = WorkflowService(InMemoryWorkflowRepository(), registry)
    original = {"filename": "sales.csv", "content_base64": _encoded(b"region,amount\nNorth,100\nSouth,50\n")}
    initial = registry.get("dataset.inspect").handler(registry.get("dataset.inspect").input_model.model_validate(original))
    assert initial.success

    workflow = service.create(WorkflowCreate(name="Inspect sales", steps=[WorkflowStep(tool="dataset.inspect", arguments=original, expected_columns=["region", "amount"])]))
    fetched = service.get(workflow.workflow_id)
    rerun = service.rerun(workflow.workflow_id, {1: {"content_base64": _encoded(b"region,amount\nWest,75\n")}})
    drift = service.rerun(workflow.workflow_id, {1: {"content_base64": _encoded(b"territory,revenue\nWest,75\n")}})

    assert fetched.version == 1
    assert rerun.status == "completed"
    assert rerun.observations[0].result["row_count"] == 1
    assert drift.status == "failed"
    assert drift.failed_step == 1
    assert "Schema drift detected" in drift.error


def test_workflow_api_save_get_and_rerun() -> None:
    previous_service = app.state.workflow_service
    app.state.workflow_service = WorkflowService(InMemoryWorkflowRepository(), ToolRegistry(dataset_tools()))
    client = TestClient(app)
    payload = {
        "name": "Inspect",
        "steps": [{"tool": "dataset.inspect", "arguments": {"filename": "data.csv", "content_base64": _encoded(b"id\n1\n")}, "expected_columns": ["id"]}],
    }
    try:
        saved = client.post("/workflows", json=payload)
        assert saved.status_code == 201
        workflow_id = saved.json()["workflow_id"]
        assert client.get(f"/workflows/{workflow_id}").status_code == 200
        rerun = client.post(f"/workflows/{workflow_id}/runs", json={"step_overrides": {"1": {"content_base64": _encoded(b"id\n2\n")}}})
        assert rerun.status_code == 200
        assert rerun.json()["status"] == "completed"
    finally:
        app.state.workflow_service = previous_service


def test_rerun_rejects_overrides_for_nonexistent_steps() -> None:
    service = WorkflowService(InMemoryWorkflowRepository(), ToolRegistry(dataset_tools()))
    arguments = {"filename": "data.csv", "content_base64": _encoded(b"id\n1\n")}
    workflow = service.create(
        WorkflowCreate(name="Inspect once", steps=[WorkflowStep(tool="dataset.inspect", arguments=arguments)])
    )

    try:
        service.rerun(workflow.workflow_id, {2: {}})
    except WorkflowError as exc:
        assert "nonexistent step" in str(exc)
    else:
        raise AssertionError("Out-of-range workflow overrides must fail explicitly.")


def _analytics_workflow(service: WorkflowService, content: bytes, *, expected: bool = True):
    return service.create(
        WorkflowCreate(
            name="Period sales metrics",
            steps=[
                WorkflowStep(
                    tool="analytics.execute",
                    arguments={
                        "filename": "period.csv",
                        "content_base64": _encoded(content),
                        "plan": {
                            "analysis": "metrics",
                            "group_by": ["region"],
                            "metrics": [
                                {"name": "count", "alias": "rows"},
                                {"name": "sum", "column": "revenue", "alias": "revenue"},
                                {"name": "distinct_count", "column": "customer", "alias": "customers"},
                            ],
                        },
                    },
                    expected_columns=["region", "customer", "revenue"] if expected else None,
                )
            ],
        )
    )


def test_immutable_run_history_and_deterministic_comparison() -> None:
    repository = InMemoryWorkflowRepository()
    service = WorkflowService(repository, ToolRegistry(dataset_tools()))
    workflow = _analytics_workflow(
        service,
        b"region,customer,revenue\nNorth,A,100\nSouth,B,200\n",
    )
    first = service.rerun(workflow.workflow_id, {})
    second = service.rerun(
        workflow.workflow_id,
        {1: {"content_base64": _encoded(b"region,customer,revenue\nNorth,A,125\nSouth,B,250\nSouth,C,50\nEast,D,10\n")}},
    )

    history = service.list_runs(workflow.workflow_id)
    comparison = service.compare_runs(first.run_id, second.run_id)
    first.facts[0].value = -999

    assert [run.run_id for run in history] == [second.run_id, first.run_id]
    assert service.get_run(first.run_id).facts[0].value != -999
    assert first.run_id != second.run_id
    assert first.definition_fingerprint == second.definition_fingerprint
    assert first.lifecycle[-1].state == "succeeded"
    assert first.verification.status == "verified"
    assert second.input_snapshots[0].row_count == 4
    revenue_changes = [item for item in comparison.metrics if item.metric == "sum"]
    assert any(item.absolute_change == 25 and item.percent_change == 25 for item in revenue_changes)
    assert any(item.absolute_change == 100 and item.percent_change == 50 for item in revenue_changes)
    assert any(item.status == "added" for item in comparison.metrics)
    assert comparison.row_counts[0].absolute_change == 2
    assert comparison.snapshots[0].status == "content_changed"
    assert all(item.previous is None or item.previous.run_id == first.run_id for item in comparison.metrics)
    assert all(item.current is None or item.current.run_id == second.run_id for item in comparison.metrics)


def test_zero_denominator_and_removed_metrics_do_not_invent_values() -> None:
    repository = InMemoryWorkflowRepository()
    service = WorkflowService(repository, ToolRegistry(dataset_tools()))
    workflow = _analytics_workflow(service, b"region,customer,revenue\nNorth,A,0\n")
    first = service.rerun(workflow.workflow_id, {})
    second = service.rerun(
        workflow.workflow_id,
        {1: {"content_base64": _encoded(b"region,customer,revenue\nNorth,B,10\n")}},
    )
    third = service.rerun(
        workflow.workflow_id,
        {1: {"content_base64": _encoded(b"region,customer,revenue\nSouth,C,10\n")}},
    )

    zero_comparison = service.compare_runs(first.run_id, second.run_id)
    changed_sum = next(item for item in zero_comparison.metrics if item.metric == "sum")
    group_comparison = service.compare_runs(second.run_id, third.run_id)
    removed = next(item for item in group_comparison.metrics if item.status == "removed" and item.metric == "sum")
    added = next(item for item in group_comparison.metrics if item.status == "added" and item.metric == "sum")

    assert changed_sum.absolute_change == 10 and changed_sum.percent_change is None
    assert "previous value is zero" in changed_sum.percent_change_reason
    assert removed.current is None and removed.absolute_change is None
    assert added.previous is None and added.percent_change is None
    assert "not treated as zero" in added.percent_change_reason


def test_schema_and_type_drift_are_recorded_as_blocked_runs() -> None:
    service = WorkflowService(InMemoryWorkflowRepository(), ToolRegistry(dataset_tools()))
    workflow = _analytics_workflow(service, b"region,customer,revenue\nNorth,A,10\n")

    missing = service.rerun(
        workflow.workflow_id,
        {1: {"content_base64": _encoded(b"region,customer\nNorth,A\n")}},
    )
    changed_type = service.rerun(
        workflow.workflow_id,
        {1: {"content_base64": _encoded(b"region,customer,revenue\nNorth,A,unknown\n")}},
    )

    assert missing.status == "failed" and missing.lifecycle[-1].state == "blocked"
    assert missing.drift_findings[0].kind == "schema"
    assert service.get_run(missing.run_id).error == missing.error
    assert changed_type.status == "failed" and changed_type.drift_findings[0].kind == "type"


def test_comparison_reports_schema_changes_for_compatible_unpinned_workflow() -> None:
    repository = InMemoryWorkflowRepository()
    service = WorkflowService(repository, ToolRegistry(dataset_tools()))
    workflow = service.create(
        WorkflowCreate(
            name="Inspect evolving input",
            steps=[WorkflowStep(tool="dataset.inspect", arguments={"filename": "data.csv", "content_base64": _encoded(b"id\n1\n")})],
        )
    )
    first = service.rerun(workflow.workflow_id, {})
    second = service.rerun(
        workflow.workflow_id,
        {1: {"content_base64": _encoded(b"id,name\n2,new\n")}},
    )

    comparison = service.compare_runs(first.run_id, second.run_id)

    assert comparison.snapshots[0].status == "incompatible"


def test_comparison_rejects_unrelated_failed_ambiguous_and_nonfinite_runs() -> None:
    repository = InMemoryWorkflowRepository()
    service = WorkflowService(repository, ToolRegistry(dataset_tools()))
    workflow_a = _analytics_workflow(service, b"region,customer,revenue\nNorth,A,1\n")
    workflow_b = _analytics_workflow(service, b"region,customer,revenue\nNorth,A,2\n")
    run_a = service.rerun(workflow_a.workflow_id, {})
    run_b = service.rerun(workflow_b.workflow_id, {})
    failed = service.rerun(
        workflow_a.workflow_id,
        {1: {"content_base64": _encoded(b"bad\n1\n")}},
    )

    with pytest.raises(WorkflowError, match="same workflow"):
        service.compare_runs(run_a.run_id, run_b.run_id)
    with pytest.raises(WorkflowError, match="completed"):
        service.compare_runs(run_a.run_id, failed.run_id)

    duplicate = run_a.model_copy(deep=True)
    duplicate.run_id = uuid4()
    duplicate.facts.append(duplicate.facts[0].model_copy(deep=True))
    repository.save_run(duplicate, {})
    with pytest.raises(WorkflowError, match="ambiguous fact"):
        service.compare_runs(run_a.run_id, duplicate.run_id)
    with pytest.raises(ValidationError):
        RunFact(
            fact_id="bad", step=1, key="bad", metric="sum", value=float("inf"),
            label="bad", calculation="bad",
        )


def test_warning_verification_and_artifact_changes_are_explicit() -> None:
    repository = InMemoryWorkflowRepository()
    service = WorkflowService(repository, ToolRegistry(dataset_tools()))
    workflow = _analytics_workflow(service, b"region,customer,revenue\nNorth,A,1\n")
    now = datetime.now(timezone.utc)
    fact = RunFact(
        fact_id="step.1.metric.total", step=1, key="metric.total", metric="sum",
        value=10, label="Total", calculation="sum(value)",
    )
    previous = WorkflowRun(
        workflow_id=workflow.workflow_id, version=1, status="completed", observations=[],
        facts=[fact], warnings=["Missing target"],
        verification=RunVerificationSummary(status="verified_with_warnings", fact_count=1, warning_count=1),
        started_at=now - timedelta(days=1), completed_at=now - timedelta(days=1),
    )
    current = WorkflowRun(
        workflow_id=workflow.workflow_id, version=1, status="completed", observations=[],
        facts=[fact.model_copy(update={"value": 12})],
        artifacts=[RunArtifact(artifact_id=uuid4(), filename="current.csv")],
        verification=RunVerificationSummary(status="verified", fact_count=1, warning_count=0),
        started_at=now, completed_at=now,
    )
    repository.save_run(previous, {})
    repository.save_run(current, {})

    comparison = service.compare_runs(previous.run_id, current.run_id)

    assert comparison.verification_previous.status == "verified_with_warnings"
    assert comparison.verification_current.status == "verified"
    assert comparison.warnings[0].change == -1
    assert comparison.artifact_count_previous == 0
    assert comparison.artifact_count_current == 1


def test_workflow_run_history_api_and_agent_binding() -> None:
    previous_service = app.state.workflow_service
    service = WorkflowService(InMemoryWorkflowRepository(), ToolRegistry(dataset_tools()))
    workflow = _analytics_workflow(service, b"region,customer,revenue\nNorth,A,10\n")
    first = service.rerun(workflow.workflow_id, {})
    second = service.rerun(
        workflow.workflow_id,
        {1: {"content_base64": _encoded(b"region,customer,revenue\nNorth,A,12\n")}},
    )
    app.state.workflow_service = service
    client = TestClient(app)
    try:
        listed = client.get(f"/workflows/{workflow.workflow_id}/runs")
        detail = client.get(f"/workflow-runs/{first.run_id}")
        compared = client.post(
            "/workflow-runs/compare",
            json={"previous_run_id": str(first.run_id), "current_run_id": str(second.run_id)},
        )
        workflows = client.get("/workflows")
        missing = client.get(f"/workflow-runs/{uuid4()}")
        same_run = client.post(
            "/workflow-runs/compare",
            json={"previous_run_id": str(first.run_id), "current_run_id": str(first.run_id)},
        )
    finally:
        app.state.workflow_service = previous_service

    assert listed.status_code == detail.status_code == compared.status_code == workflows.status_code == 200
    assert listed.json()["runs"][0]["run_id"] == str(second.run_id)
    assert "observations" not in listed.json()["runs"][0]
    assert "observations" not in detail.json()
    assert "steps" not in workflows.json()["workflows"][0]
    assert compared.json()["observed_only"] is True
    assert missing.status_code == 404
    assert same_run.status_code == 422

    artifacts = InMemoryArtifactRepository()
    registry = ToolRegistry(
        general_task_tools(None, AgentTaskResources(workflow_ids=[workflow.workflow_id]), artifacts, service)
    )
    list_tool = registry.get("workflow.list_runs")
    get_tool = registry.get("workflow.get_run")
    compare_tool = registry.get("workflow.compare_runs")
    assert list_tool.handler(list_tool.input_model(workflow_id=workflow.workflow_id)).success
    assert get_tool.handler(get_tool.input_model(run_id=first.run_id)).success
    assert compare_tool.handler(compare_tool.input_model(previous_run_id=first.run_id, current_run_id=second.run_id)).success
    with pytest.raises(ValueError, match="not bound"):
        get_tool.handler(get_tool.input_model(run_id=uuid4()))
