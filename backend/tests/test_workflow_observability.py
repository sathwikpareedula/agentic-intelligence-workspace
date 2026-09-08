"""Deterministic workflow-run quality, drift, and observability tests."""

import base64

from pydantic import Field

from app.agent.models import ToolObservation
from app.agent.tools import ToolInput, ToolRegistry, TypedTool, dataset_tools
from app.models.workflows import WorkflowCreate, WorkflowStep
from app.services.workflows import InMemoryWorkflowRepository, WorkflowService


def _encoded(content: bytes) -> str:
    return base64.b64encode(content).decode()


def _inspect_workflow(service: WorkflowService, content: bytes):
    return service.create(
        WorkflowCreate(
            name="Observe recurring data",
            steps=[
                WorkflowStep(
                    tool="dataset.inspect",
                    arguments={"filename": "period.csv", "content_base64": _encoded(content)},
                )
            ],
        )
    )


def test_quality_snapshot_and_comparison_capture_missing_duplicates_and_categories() -> None:
    service = WorkflowService(InMemoryWorkflowRepository(), ToolRegistry(dataset_tools()))
    workflow = _inspect_workflow(
        service,
        b"id,category,value\n1,A,10\n2,B,\n2,B,\n",
    )
    first = service.rerun(workflow.workflow_id, {})
    second = service.rerun(
        workflow.workflow_id,
        {1: {"content_base64": _encoded(b"id,category,value\n1,A,10\n2,C,20\n3,C,30\n")}},
    )

    snapshot = first.input_snapshots[0]
    comparison = service.compare_runs(first.run_id, second.run_id)
    missing = next(item for item in comparison.quality if item.label == "Missing values · value")
    duplicates = next(item for item in comparison.quality if item.label == "Duplicate rows")
    categories = next(item for item in comparison.categories if item.column == "category")

    assert snapshot.missing_by_column["value"] == 2
    assert snapshot.duplicate_row_count == 1
    assert snapshot.categories["category"].values == ["A", "B"]
    assert missing.absolute_change == -2
    assert duplicates.absolute_change == -1
    assert categories.added == ["C"] and categories.removed == ["B"]
    assert categories.previous_run_id == first.run_id
    assert categories.current_run_id == second.run_id
    assert first.step_summaries[0].tool_name == "dataset.inspect"
    assert first.step_summaries[0].status == "succeeded"
    assert "anomaly" not in comparison.model_dump_json().casefold()


def test_schema_comparison_names_added_removed_columns_and_type_changes() -> None:
    service = WorkflowService(InMemoryWorkflowRepository(), ToolRegistry(dataset_tools()))
    workflow = _inspect_workflow(service, b"id,amount\n1,10\n")
    first = service.rerun(workflow.workflow_id, {})
    second = service.rerun(
        workflow.workflow_id,
        {1: {"content_base64": _encoded(b"identifier,amount\n1,text\n")}},
    )

    change = service.compare_runs(first.run_id, second.run_id).snapshots[0]

    assert change.status == "incompatible"
    assert change.added_columns == ["identifier"]
    assert change.removed_columns == ["id"]
    assert change.type_changes["amount"]["previous"] == "int64"
    assert change.type_changes["amount"]["current"] == "object"


class JoinDiagnosticInput(ToolInput):
    unmatched_rows: int = Field(ge=0)


def test_join_diagnostic_and_step_deltas_are_deterministic_and_linked() -> None:
    def diagnose(arguments: JoinDiagnosticInput) -> ToolObservation:
        return ToolObservation(
            success=True,
            summary="Recorded bounded join diagnostics.",
            warnings=["Unmatched rows remain"] if arguments.unmatched_rows else [],
            artifact_ids=["10000000-0000-0000-0000-000000000001"] if arguments.unmatched_rows == 5 else [],
            result={
                "join_diagnostics": {
                    "left_unmatched_rows": arguments.unmatched_rows,
                    "row_multiplication_occurred": False,
                }
            },
        )

    registry = ToolRegistry(
        [TypedTool("test.join_diagnostics", "Test-only deterministic join diagnostics.", JoinDiagnosticInput, diagnose)]
    )
    service = WorkflowService(InMemoryWorkflowRepository(), registry)
    workflow = service.create(
        WorkflowCreate(
            name="Join quality",
            steps=[WorkflowStep(tool="test.join_diagnostics", arguments={"unmatched_rows": 2})],
        )
    )
    first = service.rerun(workflow.workflow_id, {})
    second = service.rerun(workflow.workflow_id, {1: {"unmatched_rows": 5}})

    comparison = service.compare_runs(first.run_id, second.run_id)
    unmatched = next(item for item in comparison.quality if item.label.endswith("left unmatched rows"))

    assert unmatched.section == "join"
    assert unmatched.previous == 2 and unmatched.current == 5
    assert unmatched.absolute_change == 3
    assert unmatched.previous_run_id == first.run_id
    assert unmatched.current_run_id == second.run_id
    assert comparison.steps[0].warning_change == 0
    assert comparison.steps[0].artifact_change == 1
    assert second.diagnostics[0].diagnostic_id.startswith("step.1.join_diagnostics")


def test_large_category_sets_report_counts_without_partial_added_removed_claims() -> None:
    service = WorkflowService(InMemoryWorkflowRepository(), ToolRegistry(dataset_tools()))
    header = b"category\n"
    first_content = header + "".join(f"A{index}\n" for index in range(101)).encode()
    second_content = header + "".join(f"B{index}\n" for index in range(101)).encode()
    workflow = _inspect_workflow(service, first_content)
    first = service.rerun(workflow.workflow_id, {})
    second = service.rerun(
        workflow.workflow_id, {1: {"content_base64": _encoded(second_content)}}
    )

    category = service.compare_runs(first.run_id, second.run_id).categories[0]

    assert category.previous_unique_count == category.current_unique_count == 101
    assert category.values_complete is False
    assert category.added == [] and category.removed == []


def test_blocked_run_has_explicit_step_observability() -> None:
    service = WorkflowService(InMemoryWorkflowRepository(), ToolRegistry(dataset_tools()))
    workflow = service.create(
        WorkflowCreate(
            name="Pinned schema",
            steps=[
                WorkflowStep(
                    tool="dataset.inspect",
                    arguments={"filename": "data.csv", "content_base64": _encoded(b"id\n1\n")},
                    expected_columns=["id"],
                )
            ],
        )
    )
    blocked = service.rerun(
        workflow.workflow_id,
        {1: {"content_base64": _encoded(b"other\n1\n")}},
    )

    assert blocked.status == "failed"
    assert blocked.lifecycle[-1].state == "blocked"
    assert len(blocked.step_summaries) == 1
    assert blocked.step_summaries[0].tool_name == "dataset.inspect"
    assert blocked.step_summaries[0].status == "blocked"
    assert blocked.step_summaries[0].warning_count == 0
    assert "Schema drift" in blocked.step_summaries[0].summary
