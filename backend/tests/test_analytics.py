"""Tests for typed deterministic analytics and safe SQL refusals."""

from __future__ import annotations

import base64
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.agent.models import AgentDatasetResource, AgentTaskResources, AnswerClaim
from app.agent.tools import ToolRegistry, dataset_tools, general_task_tools
from app.agent.verification import EvidenceVerifier
from app.main import app
from app.models.analytics import AnalyticsPlan, MetricSpec
from app.models.workflows import WorkflowCreate, WorkflowStep
from app.services.analytics import AnalyticsError, execute_dataset_analytics, execute_uploaded_analytics
from app.services.artifacts import InMemoryArtifactRepository
from app.services.datasets import load_dataset
from app.services.postgres_source import PostgresSourceError, validate_select
from app.services.workflows import InMemoryWorkflowRepository, WorkflowService

client = TestClient(app)
SALES = b"""region,salesperson,net_sales,target,month
North,Alice,900,2000,2026-08
North,Alice,450,2000,2026-08
South,Bob,800,1000,2026-08
"""


def _plan(**kwargs) -> AnalyticsPlan:
    return AnalyticsPlan(**kwargs)


def test_count_sum_mean_median() -> None:
    dataset = load_dataset("analytics_sales.csv", SALES)
    result = execute_dataset_analytics(
        dataset,
        _plan(analysis="metrics", metrics=[
            MetricSpec(name="count"),
            MetricSpec(name="sum", column="net_sales"),
            MetricSpec(name="mean", column="net_sales"),
            MetricSpec(name="median", column="net_sales"),
        ]),
    )
    facts = result.verification_facts
    assert facts["metric.count"] == 3
    assert facts["metric.sum_net_sales"] == 2150
    assert facts["metric.mean_net_sales"] == pytest.approx(2150 / 3)
    assert facts["metric.median_net_sales"] == 800


def test_grouped_aggregation_and_ranking() -> None:
    result = execute_uploaded_analytics(
        "analytics_sales.csv",
        SALES,
        _plan(
            analysis="metrics",
            group_by=["region"],
            metrics=[MetricSpec(name="sum", column="net_sales")],
            ascending=False,
        ),
    )
    assert result.rows[0]["region"] == "North"
    assert result.rows[0]["sum_net_sales"] == 1350
    ranked = execute_uploaded_analytics(
        "analytics_sales.csv",
        SALES,
        _plan(analysis="rank", value_column="net_sales", ascending=False),
    )
    assert ranked.rows[0]["salesperson"] == "Alice"
    assert ranked.verification_facts["rank.top_value"] == 900


def test_percent_change_rolling_correlation_and_target_variance() -> None:
    series = b"period,value,other\n1,10,4\n2,20,8\n3,40,16\n"
    change = execute_uploaded_analytics("series.csv", series, _plan(analysis="percent_change", value_column="value", order_column="period"))
    assert change.verification_facts["percent_change.last"] == 100
    rolling = execute_uploaded_analytics("series.csv", series, _plan(analysis="rolling_mean", value_column="value", order_column="period", window=2))
    assert rolling.verification_facts["rolling.mean.last"] == 30
    corr = execute_uploaded_analytics("series.csv", series, _plan(analysis="correlation", value_column="value", second_column="other"))
    assert corr.verification_facts["correlation.pearson"] == pytest.approx(1.0)
    variance = execute_uploaded_analytics(
        "analytics_sales.csv",
        SALES,
        _plan(
            analysis="target_variance",
            group_by=["region"],
            value_column="net_sales",
            second_column="target",
            contributor_column="salesperson",
            expected_columns=["region", "salesperson", "net_sales", "target", "month"],
        ),
    )
    assert variance.verification_facts["target.worst_region_shortfall"] == 650
    assert variance.verification_facts["target.top_contributor"] == 1350
    assert "North" in variance.explanation
    assert "Alice" in variance.explanation


def test_nulls_division_by_zero_and_invalid_types() -> None:
    with pytest.raises(AnalyticsError, match="Division by zero"):
        execute_uploaded_analytics("z.csv", b"period,value\n1,0\n2,10\n", _plan(analysis="percent_change", value_column="value", order_column="period"))
    with pytest.raises(AnalyticsError, match="not numeric"):
        execute_uploaded_analytics("t.csv", b"label,value\na,x\n", _plan(analysis="metrics", metrics=[MetricSpec(name="sum", column="value")]))
    with pytest.raises(AnalyticsError, match="fail on nulls"):
        execute_uploaded_analytics(
            "n.csv",
            b"value\n1\nNA\n",
            _plan(analysis="metrics", metrics=[MetricSpec(name="sum", column="value")], nulls="fail"),
        )


def test_schema_mismatch_and_unsafe_sql() -> None:
    with pytest.raises(AnalyticsError, match="schema"):
        execute_uploaded_analytics(
            "analytics_sales.csv",
            SALES,
            _plan(analysis="metrics", expected_columns=["nope"]),
        )
    with pytest.raises(PostgresSourceError):
        validate_select("DELETE FROM t")
    with pytest.raises(PostgresSourceError):
        validate_select("SELECT 1; SELECT 2")
    with pytest.raises(PostgresSourceError):
        validate_select("WITH x AS (INSERT INTO t SELECT 1) SELECT * FROM x")


def test_facts_ground_verifier_and_workflow_rerun() -> None:
    dataset = load_dataset("analytics_sales.csv", SALES)
    executed = execute_dataset_analytics(
        dataset,
        _plan(analysis="target_variance", group_by=["region"], value_column="net_sales", second_column="target", contributor_column="salesperson"),
    )
    report = EvidenceVerifier().verify(
        [AnswerClaim(text="North shortfall is 650", kind="numeric", value=650, evidence_keys=["target.worst_region_shortfall"])],
        [_obs(executed)],
    )
    assert report.status == "verified"
    encoded = base64.b64encode(SALES).decode()
    workflows = WorkflowService(InMemoryWorkflowRepository(), ToolRegistry(dataset_tools()), InMemoryArtifactRepository())
    workflow = workflows.create(
        WorkflowCreate(
            name="Analytics shortfall",
            steps=[
                WorkflowStep(
                    tool="analytics.execute",
                    arguments={
                        "filename": "analytics_sales.csv",
                        "content_base64": encoded,
                        "plan": executed.plan.model_dump(mode="json"),
                    },
                    expected_columns=["region", "salesperson", "net_sales", "target", "month"],
                )
            ],
        )
    )
    run = workflows.rerun(workflow.workflow_id, {})
    assert run.status == "completed"
    drifted = workflows.rerun(workflow.workflow_id, {1: {"content_base64": base64.b64encode(b"region\nEast\n").decode()}})
    assert drifted.status == "failed"


def test_agent_requires_bound_inspected_dataset() -> None:
    resources = AgentTaskResources(
        datasets=[AgentDatasetResource(filename="analytics_sales.csv", content_base64=base64.b64encode(SALES).decode())]
    )
    registry = ToolRegistry(general_task_tools(None, resources, InMemoryArtifactRepository()))
    inspect = registry.get("dataset.inspect")
    assert inspect is not None
    inspect.handler(inspect.input_model(dataset="analytics_sales.csv"))
    analytics = registry.get("analytics.execute")
    assert analytics is not None
    observation = analytics.handler(
        analytics.input_model(
            dataset="analytics_sales.csv",
            plan=_plan(analysis="metrics", metrics=[MetricSpec(name="sum", column="net_sales")]).model_dump(),
        )
    )
    assert observation.success
    assert observation.result["verification_facts"]["metric.sum_net_sales"] == 2150
    with pytest.raises(Exception):
        analytics.handler(analytics.input_model(dataset="other.csv", plan=_plan().model_dump()))


def test_analytics_api_validate_and_execute() -> None:
    plan = _plan(analysis="metrics", metrics=[MetricSpec(name="count")])
    validated = client.post("/analytics/validate", json=plan.model_dump(mode="json"))
    assert validated.status_code == 200
    executed = client.post(
        "/analytics/execute",
        files={"file": ("analytics_sales.csv", SALES, "text/csv")},
        data={"request": plan.model_dump_json()},
    )
    assert executed.status_code == 200
    assert executed.json()["verification_facts"]["metric.count"] == 3


def _obs(executed):
    from app.agent.models import ToolObservation

    return ToolObservation(success=True, summary=executed.explanation, result=executed.model_dump(mode="json"))
