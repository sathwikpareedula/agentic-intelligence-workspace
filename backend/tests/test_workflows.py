"""Reusable deterministic workflow recipe tests."""

import base64

from fastapi.testclient import TestClient

from app.agent.tools import ToolRegistry, dataset_tools
from app.main import app
from app.models.workflows import WorkflowCreate, WorkflowStep
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
