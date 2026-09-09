"""Controlled evaluation for deterministic analytics and safe SQL refusals."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.agent.models import AnswerClaim, ToolObservation
from app.agent.tools import ToolRegistry, dataset_tools
from app.agent.verification import EvidenceVerifier
from app.models.analytics import AnalyticsPlan, MetricSpec
from app.models.workflows import WorkflowCreate, WorkflowStep
from app.services.analytics import AnalyticsError, execute_uploaded_analytics
from app.services.artifacts import InMemoryArtifactRepository
from app.services.postgres_source import PostgresSourceError, validate_select
from app.services.workflows import InMemoryWorkflowRepository, WorkflowService

SALES = Path(__file__).resolve().parents[3] / "sample_data" / "analytics_sales.csv"
SERIES = b"period,value,other\n1,10,4\n2,20,8\n3,40,16\n"


def evaluate_analytics_cases(path: Path) -> dict:
    specification = json.loads(path.read_text(encoding="utf-8"))
    sales = SALES.read_bytes()
    observed = {
        "A_count": _try(lambda: execute_uploaded_analytics("analytics_sales.csv", sales, AnalyticsPlan(metrics=[MetricSpec(name="count")])).verification_facts["metric.count"] == 3),
        "B_grouped_sum": _try(lambda: execute_uploaded_analytics("analytics_sales.csv", sales, AnalyticsPlan(group_by=["region"], metrics=[MetricSpec(name="sum", column="net_sales")])).rows[0]["sum_net_sales"] == 1350),
        "C_mean_median": _mean_median(sales),
        "D_percent_change": _try(lambda: execute_uploaded_analytics("s.csv", SERIES, AnalyticsPlan(analysis="percent_change", value_column="value", order_column="period")).verification_facts["percent_change.last"] == 100),
        "E_target_variance": _try(lambda: execute_uploaded_analytics("analytics_sales.csv", sales, AnalyticsPlan(analysis="target_variance", group_by=["region"], value_column="net_sales", second_column="target")).verification_facts["target.worst_region_shortfall"] == 650),
        "F_ranking": _try(lambda: execute_uploaded_analytics("analytics_sales.csv", sales, AnalyticsPlan(analysis="rank", value_column="net_sales")).verification_facts["rank.top_value"] == 900),
        "G_rolling_average": _try(lambda: execute_uploaded_analytics("s.csv", SERIES, AnalyticsPlan(analysis="rolling_mean", value_column="value", order_column="period", window=2)).verification_facts["rolling.mean.last"] == 30),
        "H_correlation": _try(lambda: abs(execute_uploaded_analytics("s.csv", SERIES, AnalyticsPlan(analysis="correlation", value_column="value", second_column="other")).verification_facts["correlation.pearson"] - 1) < 1e-9),
        "I_null_handling": _nulls(),
        "J_invalid_type_refusal": _raises("not numeric", b"value\nx\n", AnalyticsPlan(metrics=[MetricSpec(name="sum", column="value")])),
        "K_destructive_sql_refusal": _sql("DELETE FROM t"),
        "L_multi_statement_refusal": _sql("SELECT 1; SELECT 2"),
        "M_writable_cte_refusal": _sql("WITH x AS (INSERT INTO t SELECT 1) SELECT * FROM x"),
        "N_exact_deterministic_fact": _try(lambda: execute_uploaded_analytics("analytics_sales.csv", sales, AnalyticsPlan(analysis="target_variance", group_by=["region"], value_column="net_sales", second_column="target", contributor_column="salesperson")).verification_facts["target.top_contributor"] == 1350),
        "O_grounded_explanation": _grounded(sales),
        "P_workflow_rerun": _workflow(sales, True),
        "Q_schema_drift": _workflow(sales, False),
        "R_visualization_selection": _visualizations(sales),
    }
    cases = [{"id": item["id"], "name": item["name"], "passed": bool(observed.get(item["id"])), "observed": observed.get(item["id"])} for item in specification["cases"]]
    passed = sum(item["passed"] for item in cases)
    return {
        "case_count": len(cases),
        "passed_count": passed,
        "failed_count": len(cases) - passed,
        "case_pass_rate": passed / len(cases) if cases else 0,
        "cases": cases,
        "scope": "Controlled deterministic analytics evaluation; no hosted model. Live Postgres SQL execution is not required for refusal cases.",
    }


def _mean_median(sales: bytes) -> bool:
    result = execute_uploaded_analytics(
        "analytics_sales.csv",
        sales,
        AnalyticsPlan(metrics=[MetricSpec(name="mean", column="net_sales"), MetricSpec(name="median", column="net_sales")]),
    )
    return result.verification_facts["metric.mean_net_sales"] == 2150 / 3 and result.verification_facts["metric.median_net_sales"] == 800


def _nulls() -> bool:
    excluded = execute_uploaded_analytics("n.csv", b"value\n1\nNA\n3\n", AnalyticsPlan(metrics=[MetricSpec(name="mean", column="value")]))
    failed = _raises("fail on nulls", b"value\n1\nNA\n", AnalyticsPlan(metrics=[MetricSpec(name="sum", column="value")], nulls="fail"))
    return excluded.verification_facts["metric.mean_value"] == 2 and failed


def _grounded(sales: bytes) -> bool:
    executed = execute_uploaded_analytics(
        "analytics_sales.csv",
        sales,
        AnalyticsPlan(analysis="target_variance", group_by=["region"], value_column="net_sales", second_column="target"),
    )
    report = EvidenceVerifier().verify(
        [AnswerClaim(text="Largest shortfall is 650", kind="numeric", value=650, evidence_keys=["target.worst_region_shortfall"])],
        [ToolObservation(success=True, summary=executed.explanation, result=executed.model_dump(mode="json"))],
    )
    return report.status == "verified" and "North" in executed.explanation


def _workflow(sales: bytes, matching: bool) -> bool:
    import base64

    plan = AnalyticsPlan(metrics=[MetricSpec(name="count")], expected_columns=["region", "salesperson", "net_sales", "target", "month"])
    workflows = WorkflowService(InMemoryWorkflowRepository(), ToolRegistry(dataset_tools()), InMemoryArtifactRepository())
    workflow = workflows.create(
        WorkflowCreate(
            name="analytics eval",
            steps=[
                WorkflowStep(
                    tool="analytics.execute",
                    arguments={"filename": "analytics_sales.csv", "content_base64": base64.b64encode(sales).decode(), "plan": plan.model_dump(mode="json")},
                    expected_columns=["region", "salesperson", "net_sales", "target", "month"],
                )
            ],
        )
    )
    if matching:
        return workflows.rerun(workflow.workflow_id, {}).status == "completed"
    replacement = base64.b64encode(b"region\nEast\n").decode()
    return workflows.rerun(workflow.workflow_id, {1: {"content_base64": replacement}}).status == "failed"


def _visualizations(sales: bytes) -> bool:
    grouped = execute_uploaded_analytics(
        "analytics_sales.csv",
        sales,
        AnalyticsPlan(group_by=["region"], metrics=[MetricSpec(name="sum", column="net_sales")]),
    )
    trend = execute_uploaded_analytics(
        "s.csv",
        SERIES,
        AnalyticsPlan(analysis="percent_change", value_column="value", order_column="period"),
    )
    scalar = execute_uploaded_analytics(
        "analytics_sales.csv",
        sales,
        AnalyticsPlan(metrics=[MetricSpec(name="sum", column="net_sales")]),
    )
    return (
        grouped.visualization.kind == "bar"
        and grouped.visualization.x_field == "region"
        and trend.visualization.kind == "line"
        and trend.visualization.x_field == "period"
        and scalar.visualization.kind == "metric"
    )


def _sql(statement: str) -> bool:
    try:
        validate_select(statement)
    except PostgresSourceError:
        return True
    return False


def _raises(match: str, content: bytes, plan: AnalyticsPlan) -> bool:
    try:
        execute_uploaded_analytics("x.csv", content, plan)
    except AnalyticsError as exc:
        return match in str(exc)
    return False


def _try(callback) -> bool:
    try:
        return bool(callback())
    except Exception:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Run controlled analytics evaluations.")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    result = evaluate_analytics_cases(args.path)
    print(json.dumps(result, indent=2))
    if result["failed_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
