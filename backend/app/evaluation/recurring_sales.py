"""Controlled end-to-end evaluation for the verified recurring sales workflow."""

from __future__ import annotations

import argparse
import base64
from dataclasses import replace
import json
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from app.agent.tools import ToolRegistry, dataset_tools, template_transform_tool
from app.config import get_settings
from app.main import app
from app.services.artifacts import InMemoryArtifactRepository
from app.services.workflows import InMemoryWorkflowRepository, WorkflowService


SAMPLE_ROOT = Path(__file__).resolve().parents[3] / "sample_data"


def evaluate_recurring_sales_cases(path: Path) -> dict:
    specification = json.loads(path.read_text(encoding="utf-8"))
    observed = _run_flagship_scenario()
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
        "scope": (
            "Controlled public-API workflow save, two-period execution, verified artifact, "
            "run history, deterministic comparison, provenance, and blocked drift; no hosted model or live database."
        ),
    }


def _run_flagship_scenario() -> dict[str, bool]:
    artifacts = InMemoryArtifactRepository()
    workflows = WorkflowService(
        InMemoryWorkflowRepository(),
        ToolRegistry([*dataset_tools(), template_transform_tool(artifacts)]),
        artifacts,
    )
    previous_artifacts = app.state.artifact_repository
    previous_workflows = app.state.workflow_service
    settings = replace(get_settings(), app_mode="demo")
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.artifact_repository = artifacts
    app.state.workflow_service = workflows
    client = TestClient(app)
    try:
        transform_arguments = _create_verified_transform_definition(client)
        august_orders = (SAMPLE_ROOT / "raw_orders.xlsx").read_bytes()
        workflow_response = client.post(
            "/workflows",
            json={
                "name": "Verified recurring sales submission",
                "steps": [
                    {
                        "tool": "analytics.execute",
                        "arguments": {
                            "filename": "august_orders.xlsx",
                            "content_base64": _encoded(august_orders),
                            "plan": {
                                "analysis": "metrics",
                                "metrics": [
                                    {"name": "count", "alias": "orders"},
                                    {"name": "sum", "column": "eligible_sales", "alias": "eligible_sales"},
                                    {"name": "sum", "column": "returns", "alias": "returns"},
                                    {"name": "distinct_count", "column": "customer_id", "alias": "customers"},
                                ],
                            },
                        },
                        "expected_columns": ["order_id", "customer_id", "gross_sales", "returns", "eligible_sales"],
                    },
                    {"tool": "template.transform", "arguments": transform_arguments},
                ],
            },
        )
        workflow_response.raise_for_status()
        workflow = workflow_response.json()
        workflow_id = workflow["workflow_id"]

        first = client.post(f"/workflows/{workflow_id}/runs", json={"step_overrides": {}})
        first.raise_for_status()
        first_run = first.json()

        september_orders = _september_orders()
        september_customers = _september_customers()
        september_sources = [
            {
                **transform_arguments["sources"][0],
                "filename": "september_orders.csv",
                "content_base64": _encoded(september_orders),
            },
            {
                **transform_arguments["sources"][1],
                "filename": "september_customers.csv",
                "content_base64": _encoded(september_customers),
            },
        ]
        second = client.post(
            f"/workflows/{workflow_id}/runs",
            json={
                "step_overrides": {
                    "1": {"filename": "september_orders.csv", "content_base64": _encoded(september_orders)},
                    "2": {"sources": september_sources},
                }
            },
        )
        second.raise_for_status()
        second_run = second.json()
        if first_run["status"] != "completed" or second_run["status"] != "completed":
            raise AssertionError(
                f"Flagship period run failed: first={first_run.get('error')!r}, second={second_run.get('error')!r}"
            )

        comparison_response = client.post(
            "/workflow-runs/compare",
            json={"previous_run_id": first_run["run_id"], "current_run_id": second_run["run_id"]},
        )
        if comparison_response.status_code != 200:
            raise AssertionError(f"Flagship comparison failed: {comparison_response.text}")
        comparison = comparison_response.json()
        history_response = client.get(f"/workflows/{workflow_id}/runs?limit=10")
        history_response.raise_for_status()
        history = history_response.json()["runs"]

        bad = client.post(
            f"/workflows/{workflow_id}/runs",
            json={"step_overrides": {"1": {"filename": "bad_period.csv", "content_base64": _encoded(b"order_id,customer_id\nX,C001\n")}}},
        )
        bad.raise_for_status()
        blocked_run = bad.json()
        blocked_detail = client.get(f"/workflow-runs/{blocked_run['run_id']}")
        blocked_detail.raise_for_status()

        eligible_change = next(item for item in comparison["metrics"] if item["label"] == "eligible_sales")
        order_change = next(item for item in comparison["metrics"] if item["label"] == "orders")
        current_artifact = second_run["artifacts"][0]
        artifact_download = client.get(current_artifact["download_url"])
        category_change = next(
            item for item in comparison["categories"]
            if item["input_key"] == "step.1.input" and item["column"] == "order_id"
        )
        return {
            "A_workflow_persisted": client.get(f"/workflows/{workflow_id}").status_code == 200,
            "B_distinct_immutable_runs": first_run["run_id"] != second_run["run_id"] and len(history) >= 2,
            "C_definition_identity": first_run["definition_fingerprint"] == second_run["definition_fingerprint"],
            "D_verified_runs": first_run["verification"]["status"] == "verified" and second_run["verification"]["status"] == "verified",
            "E_exact_metric_change": eligible_change["absolute_change"] == 730 and order_change["absolute_change"] == 1,
            "F_row_count_change": any(item["absolute_change"] == 1 for item in comparison["row_counts"]),
            "G_real_artifact": artifact_download.status_code == 200 and len(artifact_download.content) > 1_000,
            "H_comparison_provenance": (
                eligible_change["previous"]["run_id"] == first_run["run_id"]
                and eligible_change["current"]["run_id"] == second_run["run_id"]
            ),
            "I_source_snapshots": bool(first_run["input_snapshots"]) and bool(second_run["input_snapshots"]),
            "J_category_drift": category_change["values_complete"] and len(category_change["added"]) == 4 and len(category_change["removed"]) == 3,
            "K_policy_provenance": second_run["step_summaries"][1]["source_count"] > 0,
            "L_blocked_drift_recorded": (
                blocked_run["status"] == "failed"
                and blocked_run["lifecycle"][-1]["state"] == "blocked"
                and blocked_detail.json()["run_id"] == blocked_run["run_id"]
            ),
        }
    finally:
        app.state.artifact_repository = previous_artifacts
        app.state.workflow_service = previous_workflows
        app.dependency_overrides.pop(get_settings, None)


def _create_verified_transform_definition(client: TestClient) -> dict:
    proposal_files = [
        ("target", ("required_template.xlsx", (SAMPLE_ROOT / "required_template.xlsx").read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ("sources", ("raw_orders.xlsx", (SAMPLE_ROOT / "raw_orders.xlsx").read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ("sources", ("customer_master.csv", (SAMPLE_ROOT / "customer_master.csv").read_bytes(), "text/csv")),
    ]
    proposal = client.post(
        "/template-transforms/proposals", files=proposal_files, data={"source_roles": '["orders","customers"]'}
    )
    proposal.raise_for_status()
    plan = proposal.json()["plan"]
    plan["joins"] = [{
        "right_role": "customers", "left_on": ["orders.customer_id"], "right_on": ["cust_id"], "how": "left",
        "block_many_to_many": True, "block_row_multiplication": True, "max_unmatched_left_percentage": 0,
    }]
    plan["derivations"] = [
        {
            "target_field": "Net Sales", "operation": "subtract", "separator": " ", "constant": None, "policy_query": None,
            "inputs": [
                {"source_role": "orders", "source_field": "gross_sales", "transformation": "normalize_currency"},
                {"source_role": "orders", "source_field": "returns", "transformation": "none"},
            ],
        },
        {
            "target_field": "Commission", "operation": "policy_multiply", "separator": " ", "constant": None,
            "policy_query": "commission policy rate",
            "inputs": [{"source_role": "target", "source_field": "Net Sales", "transformation": "none"}],
        },
    ]
    plan["unique_fields"] = ["Order ID"]
    execution = client.post(
        "/template-transforms/executions",
        files=[*proposal_files, ("policy", ("reporting_policy.pdf", (SAMPLE_ROOT / "reporting_policy.pdf").read_bytes(), "application/pdf"))],
        data={"source_roles": '["orders","customers"]', "plan": json.dumps(plan)},
    )
    execution.raise_for_status()
    body = execution.json()
    if body["status"] != "completed":
        raise AssertionError(f"Canonical transform setup failed: {body['status']}")
    saved = client.get(f"/workflows/{body['saved_workflow']['workflow_id']}")
    saved.raise_for_status()
    return saved.json()["steps"][0]["arguments"]


def _september_orders() -> bytes:
    return (
        "order_id,customer_id,gross_sales,returns,eligible_sales\n"
        'O-2001,C001,"$1,200.00",100,1100\n'
        'O-2002,C002,"$800.00",50,750\n'
        'O-2003,C003,"$600.00",20,580\n'
        'O-2004,C004,"$400.00",0,400\n'
    ).encode()


def _september_customers() -> bytes:
    return (
        "cust_id,customer_name,territory\n"
        "C001,Acme North,North\n"
        "C002,Bright South,South\n"
        "C003,West Retail,West\n"
        "C004,Central Goods,Central\n"
    ).encode()


def _encoded(content: bytes) -> str:
    return base64.b64encode(content).decode("ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the verified recurring sales workflow evaluation.")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    result = evaluate_recurring_sales_cases(args.path)
    print(json.dumps(result, indent=2))
    if result["failed_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
