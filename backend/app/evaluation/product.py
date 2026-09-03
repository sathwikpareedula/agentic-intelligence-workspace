"""Controlled deterministic evaluation for product-critical trust behavior."""

import argparse
import base64
import json
from pathlib import Path
from uuid import UUID

import pandas as pd

from app.agent.models import AnswerClaim, ToolObservation
from app.agent.providers import DeterministicGradesDemoProvider
from app.agent.tools import ToolRegistry, dataset_tools
from app.agent.verification import EvidenceVerifier
from app.models.grades import PolicyEvidence
from app.models.retrieval import SourceReference
from app.models.workflows import WorkflowCreate, WorkflowStep
from app.services.grades import calculate_required_final
from app.services.sales_report import build_august_sales_report
from app.services.workflows import InMemoryWorkflowRepository, WorkflowService


def _source(seed: int = 1, filename: str = "syllabus.pdf") -> SourceReference:
    return SourceReference(
        document_id=UUID(int=seed),
        filename=filename,
        page_number=1,
        chunk_id=UUID(int=seed + 100),
    )


def evaluate_product_cases(path: Path, sample_root: Path) -> dict:
    expected = json.loads(path.read_text(encoding="utf-8"))
    cases = []

    grades = pd.read_csv(sample_root / "grades.csv")
    policy = [PolicyEvidence(
        text="Grading policy: An A requires at least 90%. The final exam is 30% of the course grade.",
        source=_source(),
    )]
    grade_result = calculate_required_final(grades, policy)
    cases.append(_case(
        "grade_required_final",
        grade_result.status == "required" and grade_result.required_final_percentage == expected["grade_required_final"],
        {"status": grade_result.status, "required_final_percentage": grade_result.required_final_percentage},
    ))

    insufficient = calculate_required_final(
        grades,
        [PolicyEvidence(text="Consult the grading policy.", source=_source(2))],
    )
    cases.append(_case("grade_insufficient_evidence", insufficient.status == "insufficient_evidence", {"status": insufficient.status}))

    conflicting = calculate_required_final(
        grades,
        policy + [PolicyEvidence(text="An A requires at least 93%. The final exam is 40%.", source=_source(3))],
    )
    cases.append(_case("grade_conflicting_evidence", conflicting.status == "conflicting_evidence", {"status": conflicting.status}))

    verification = EvidenceVerifier().verify(
        [AnswerClaim(text="Required final is 99", kind="numeric", value=99)],
        [ToolObservation(success=True, summary="calculated", result={"required_final_percentage": 94.666667})],
    )
    cases.append(_case("numeric_verification_rejects_mismatch", verification.status == "unsupported", {"status": verification.status}))

    provider = DeterministicGradesDemoProvider()
    first = provider.decide("What score is required?", [])
    second = provider.decide("What score is required?", [ToolObservation(success=True, summary="inspected", result={})])
    cases.append(_case(
        "grades_tool_selection",
        getattr(first, "tool", None) == "dataset.inspect" and getattr(second, "tool", None) == "document.search",
        {"first": getattr(first, "tool", None), "second": getattr(second, "tool", None)},
    ))

    encoded = base64.b64encode(b"region,amount\nNorth,100\n").decode("ascii")
    registry = ToolRegistry(dataset_tools())
    workflows = WorkflowService(InMemoryWorkflowRepository(), registry)
    workflow = workflows.create(WorkflowCreate(
        name="Schema evaluation",
        steps=[WorkflowStep(
            tool="dataset.inspect",
            arguments={"filename": "sales.csv", "content_base64": encoded},
            expected_columns=["region", "amount"],
        )],
    ))
    drifted = workflows.rerun(
        workflow.workflow_id,
        {1: {"content_base64": base64.b64encode(b"territory,revenue\nNorth,100\n").decode("ascii")}},
    )
    cases.append(_case(
        "workflow_schema_drift",
        drifted.status == "failed" and bool(drifted.error and "Schema drift detected" in drifted.error),
        {"status": drifted.status, "failed_step": drifted.failed_step},
    ))

    sales = build_august_sales_report(
        pd.read_csv(sample_root / "august_transactions.csv"),
        pd.read_csv(sample_root / "sales_customers.csv"),
        pd.read_csv(sample_root / "sales_targets.csv"),
        [PolicyEvidence(
            text="August commission policy: Salespeople earn a commission rate of 5% of completed net sales after discounts.",
            source=_source(4, "commission_policy.pdf"),
        )],
    )
    regional = sales.regional_performance.set_index("region")
    commissions = sales.commissions.set_index("salesperson")
    sales_expected = expected["sales"]
    sales_passed = (
        sales.regional_performance.iloc[0]["region"] == sales_expected["largest_underperformance_region"]
        and sales.regional_performance.iloc[0]["underperformance"] == sales_expected["largest_underperformance"]
        and regional.loc["North", "net_sales"] == sales_expected["north_net_sales"]
        and commissions.loc["Alice", "commission"] == sales_expected["alice_commission"]
        and sales.join_diagnostics.left_unmatched_rows == sales_expected["left_unmatched_rows"]
    )
    cases.append(_case(
        "august_sales_ground_truth",
        bool(sales_passed),
        {
            "largest_underperformance_region": sales.regional_performance.iloc[0]["region"],
            "largest_underperformance": sales.regional_performance.iloc[0]["underperformance"],
            "north_net_sales": regional.loc["North", "net_sales"],
            "alice_commission": commissions.loc["Alice", "commission"],
            "left_unmatched_rows": sales.join_diagnostics.left_unmatched_rows,
        },
    ))

    passed = sum(case["passed"] for case in cases)
    return {
        "case_count": len(cases),
        "passed_count": passed,
        "failed_count": len(cases) - passed,
        "case_pass_rate": passed / len(cases) if cases else 0.0,
        "cases": cases,
        "scope": "Controlled deterministic product behavior; no hosted model, hosted embeddings, or live database.",
    }


def _case(name: str, passed: bool, observed: dict) -> dict:
    return {"name": name, "passed": bool(passed), "observed": observed}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run controlled product trust evaluations.")
    parser.add_argument("path", type=Path, help="Path to product evaluation ground truth JSON.")
    parser.add_argument("--sample-root", type=Path, help="Path to the sample-data directory.")
    args = parser.parse_args()
    sample_root = args.sample_root or args.path.resolve().parent.parent / "sample_data"
    result = evaluate_product_cases(args.path, sample_root)
    print(json.dumps(result, indent=2))
    if result["failed_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
