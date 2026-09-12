"""Tests for provider-neutral product-specific model evaluation."""

import json
from pathlib import Path

import pytest

from app.agent.providers import FakeModelProvider, ModelProviderError, OllamaModelProvider, ProviderCallMetrics
from app.evaluation.model_quality import (
    FixtureProviderFactory,
    OllamaProviderFactory,
    evaluate_model_suite,
    evaluation_configuration,
)


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
                load_duration_ms=1.0,
                prompt_eval_duration_ms=2.0,
                output_eval_duration_ms=4.0,
                output_tokens_per_second=5.0,
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
    assert metrics["latency_ms_median"] == 10
    assert metrics["latency_ms_p95"] == 10
    assert metrics["load_duration_ms_total"] == metrics["measured_call_count"]
    assert metrics["output_tokens_per_second_mean"] == 5
    assert metrics["approximate_cost_usd"] > 0
    assert metrics["cost_basis"]["source"] == "operator_supplied"


def test_model_evaluation_reports_sanitized_provider_failure_reason() -> None:
    class FailingProvider:
        last_call_metrics = None

        def decide(self, goal, observations):
            raise ModelProviderError("provider_timeout", "Orchestrator provider timed out.")

    class FailingFactory(FixtureProviderFactory):
        provider_name = "failing-fixture"
        model_name = "failure-contract"

        def create(self, case, tool_specifications):
            return FailingProvider()

    result = evaluate_model_suite(ROOT / "evals" / "model_cases.json", FailingFactory())
    case = result["cases"][0]

    assert case["scenario_name"] == case["capability"]
    assert case["provider_error"] == "provider_timeout"
    assert case["provider_failure_reason"] == "Orchestrator provider timed out."
    assert case["structured_output_valid"] is False


def test_ollama_evaluation_factory_is_keyless_and_provider_native() -> None:
    factory = OllamaProviderFactory(
        model="llama3.2:3b",
        timeout_seconds=30,
        max_retries=1,
        max_output_tokens=1000,
    )
    suite = json.loads((ROOT / "evals" / "model_cases.json").read_text(encoding="utf-8"))
    case_payload = suite["cases"][0]
    from app.evaluation.model_quality import ModelEvaluationCase

    provider = factory.create(ModelEvaluationCase.model_validate(case_payload), [])
    assert isinstance(provider, OllamaModelProvider)
    assert provider.provider_name == "ollama"
    assert provider.model_name == "llama3.2:3b"


def test_model_evaluation_checkpoints_each_case_and_resumes_identical_configuration(tmp_path: Path) -> None:
    scenario_path = ROOT / "evals" / "model_cases.json"
    checkpoint_path = tmp_path / "checkpoint.json"

    class InterruptedProvider:
        last_call_metrics = None

        def decide(self, goal, observations):
            raise KeyboardInterrupt

    class InterruptingFactory(FixtureProviderFactory):
        def create(self, case, tool_specifications):
            if case.id == "correct_tool_selection":
                return InterruptedProvider()
            return super().create(case, tool_specifications)

    factory = InterruptingFactory()
    configuration = evaluation_configuration(
        scenario_path,
        factory,
        temperature=0,
        max_output_tokens=600,
        timeout_seconds=60,
        max_retries=1,
    )

    with pytest.raises(KeyboardInterrupt):
        evaluate_model_suite(
            scenario_path,
            factory,
            checkpoint_path=checkpoint_path,
            evaluation_configuration=configuration,
        )

    partial = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert partial["status"] == "PARTIAL"
    assert partial["evaluation_configuration"] == configuration
    assert partial["evaluations"][0]["status"] == "PARTIAL"
    assert partial["evaluations"][0]["deterministic_checks"]["completed_case_count"] == 1
    first = partial["evaluations"][0]["cases"][0]
    assert first["id"] == "goal_to_typed_plan"
    assert first["provider"] == "fixture"
    assert first["model"] == "offline-contract"
    assert first["structured_output_valid"] is True
    assert first["latency_ms"] is None
    assert not checkpoint_path.with_name(f".{checkpoint_path.name}.tmp").exists()

    class TrackingFactory(FixtureProviderFactory):
        def __init__(self):
            self.created = []

        def create(self, case, tool_specifications):
            self.created.append(case.id)
            return super().create(case, tool_specifications)

    resumed_factory = TrackingFactory()
    result = evaluate_model_suite(
        scenario_path,
        resumed_factory,
        checkpoint_path=checkpoint_path,
        evaluation_configuration=configuration,
        resume=True,
    )

    assert result["status"] == "COMPLETE"
    assert result["deterministic_checks"]["completed_case_count"] == 10
    assert "goal_to_typed_plan" not in resumed_factory.created
    assert len(resumed_factory.created) == 9
    complete = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert complete["status"] == "COMPLETE"
    assert len(complete["evaluations"][0]["cases"]) == 10


def test_model_evaluation_refuses_resume_when_configuration_differs(tmp_path: Path) -> None:
    scenario_path = ROOT / "evals" / "model_cases.json"
    checkpoint_path = tmp_path / "checkpoint.json"
    factory = FixtureProviderFactory()
    configuration = evaluation_configuration(
        scenario_path,
        factory,
        temperature=0,
        max_output_tokens=600,
        timeout_seconds=60,
        max_retries=1,
    )
    evaluate_model_suite(
        scenario_path,
        factory,
        checkpoint_path=checkpoint_path,
        evaluation_configuration=configuration,
    )
    changed = {**configuration, "max_output_tokens": 601}

    with pytest.raises(ValueError, match="configuration differs"):
        evaluate_model_suite(
            scenario_path,
            factory,
            checkpoint_path=checkpoint_path,
            evaluation_configuration=changed,
            resume=True,
        )
