"""Tests for provider-neutral product-specific model evaluation."""

import json
from pathlib import Path

from app.agent.providers import FakeModelProvider, ProviderCallMetrics
from app.evaluation.model_quality import FixtureProviderFactory, evaluate_model_suite


ROOT = Path(__file__).parents[2]


def test_offline_model_evaluation_passes_all_product_cases() -> None:
    result = evaluate_model_suite(ROOT / "evals" / "model_cases.json", FixtureProviderFactory())

    checks = result["deterministic_checks"]
    assert checks["case_count"] == 10
    assert checks["passed_count"] == 10
    assert checks["invalid_tool_arguments"] == 0
    assert checks["hallucinated_tool_arguments"] == 0
    assert checks["unnecessary_tool_calls"] == 0
    assert result["provider_metrics"]["total_tokens"] is None
    assert result["model_quality_judgment"]["status"] == "not_supplied"
    assert "no hosted request" in result["scope"]


def test_model_evaluation_detects_invented_bound_resource(tmp_path: Path) -> None:
    payload = json.loads((ROOT / "evals" / "model_cases.json").read_text(encoding="utf-8"))
    case = next(item for item in payload["cases"] if item["id"] == "no_invented_resources")
    case["fixture_decisions"][1]["arguments"]["dataset"] = "invented.csv"
    path = tmp_path / "invented-resource.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_model_suite(path, FixtureProviderFactory())

    assert result["deterministic_checks"]["failed_count"] == 1
    assert result["deterministic_checks"]["hallucinated_tool_arguments"] == 1
    failed = next(item for item in result["cases"] if item["id"] == "no_invented_resources")
    assert failed["deterministic_checks"]["no_hallucinated_resources"] is False


def test_model_evaluation_aggregates_usage_and_operator_supplied_cost() -> None:
    class MeasuredProvider:
        def __init__(self, decisions):
            self._delegate = FakeModelProvider(decisions)
            self.last_call_metrics = None

        def decide(self, goal, observations):
            decision = self._delegate.decide(goal, observations)
            self.last_call_metrics = ProviderCallMetrics(
                latency_ms=10.0,
                input_tokens=100,
                output_tokens=20,
                total_tokens=120,
            )
            return decision

    class MeasuredFactory(FixtureProviderFactory):
        provider_name = "measured-fixture"

        def create(self, case, tool_specifications):
            del tool_specifications
            return MeasuredProvider(case.fixture_decisions)

    result = evaluate_model_suite(
        ROOT / "evals" / "model_cases.json",
        MeasuredFactory(),
        input_cost_per_million=2.0,
        output_cost_per_million=8.0,
    )

    metrics = result["provider_metrics"]
    assert metrics["measured_call_count"] > 10
    assert metrics["total_tokens"] == metrics["measured_call_count"] * 120
    assert metrics["approximate_cost_usd"] > 0
    assert metrics["cost_basis"]["source"] == "operator_supplied"
