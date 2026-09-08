"""Controlled evaluation for immutable workflow runs and deterministic comparisons."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

from app.agent.tools import ToolRegistry, dataset_tools
from app.models.workflows import WorkflowCreate, WorkflowStep
from app.services.workflows import InMemoryWorkflowRepository, WorkflowError, WorkflowService

SAMPLE_ROOT = Path(__file__).resolve().parents[3] / "sample_data"

def evaluate_workflow_run_cases(path: Path) -> dict:
    specification = json.loads(path.read_text(encoding="utf-8"))
    observed = _observed_cases()
    cases = [
        {
            "id": item["id"],
            "name": item["name"],
            "passed": bool(observed.get(item["id"])),
            "observed": observed.get(item["id"]),
        }
        for item in specification["cases"]
    ]
    passed = sum(item["passed"] for item in cases)
    return {
        "case_count": len(cases),
        "passed_count": passed,
        "failed_count": len(cases) - passed,
        "case_pass_rate": passed / len(cases) if cases else 0,
        "cases": cases,
        "scope": "Controlled deterministic workflow-run history and comparison evaluation; no hosted model or live database.",
    }


def _observed_cases() -> dict[str, bool]:
    repository = InMemoryWorkflowRepository()
    service = WorkflowService(repository, ToolRegistry(dataset_tools()))
    august = (SAMPLE_ROOT / "analytics_sales.csv").read_bytes()
    september = (SAMPLE_ROOT / "analytics_sales_september.csv").read_bytes()
    workflow = _workflow(service, august)
    first = service.rerun(workflow.workflow_id, {})
    second = service.rerun(
        workflow.workflow_id,
        {1: {"content_base64": _encoded(september)}},
    )
    comparison = service.compare_runs(first.run_id, second.run_id)
    preserved_value = service.get_run(first.run_id).facts[0].value
    first.facts[0].value = -1
    other = _workflow(service, august)
    other_run = service.rerun(other.workflow_id, {})
    incompatible_refused = False
    try:
        service.compare_runs(first.run_id, other_run.run_id)
    except WorkflowError:
        incompatible_refused = True
    drift = service.rerun(
        workflow.workflow_id,
        {1: {"content_base64": _encoded(b"region,salesperson\nNorth,Alice\n")}},
    )
    return {
        "A_distinct_runs": first.run_id != second.run_id,
        "B_history_order": [item.run_id for item in service.list_runs(workflow.workflow_id, 2, 0)] == [drift.run_id, second.run_id],
        "C_immutable_history": service.get_run(first.run_id).facts[0].value == preserved_value,
        "D_definition_identity": first.definition_fingerprint == second.definition_fingerprint,
        "E_exact_metric_change": any(item.metric == "sum" and item.absolute_change == 175 and abs((item.percent_change or 0) - 12.962962962962962) < 1e-9 for item in comparison.metrics),
        "F_added_group": any(item.status == "added" for item in comparison.metrics),
        "G_row_count_change": comparison.row_counts[0].absolute_change == 1,
        "H_run_provenance": all(item.current is None or item.current.run_id == second.run_id for item in comparison.metrics),
        "I_incompatible_refusal": incompatible_refused,
        "J_schema_drift_recorded": drift.status == "failed" and drift.lifecycle[-1].state == "blocked" and drift.drift_findings[0].kind == "schema",
    }


def _workflow(service: WorkflowService, content: bytes):
    return service.create(
        WorkflowCreate(
            name="workflow run evaluation",
            steps=[
                WorkflowStep(
                    tool="analytics.execute",
                    arguments={
                        "filename": "period.csv",
                        "content_base64": _encoded(content),
                        "plan": {
                            "analysis": "metrics",
                            "group_by": ["region"],
                            "metrics": [{"name": "sum", "column": "net_sales"}],
                        },
                    },
                    expected_columns=["region", "salesperson", "net_sales", "target", "month"],
                )
            ],
        )
    )


def _encoded(content: bytes) -> str:
    return base64.b64encode(content).decode()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run workflow history/comparison evaluations.")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    result = evaluate_workflow_run_cases(args.path)
    print(json.dumps(result, indent=2))
    if result["failed_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
