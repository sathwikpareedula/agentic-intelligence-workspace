"""Provider-neutral evaluation of model decisions for the workspace product."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
from statistics import mean
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.models import Complete, ModelDecision, ToolCall, ToolObservation
from app.agent.providers import FakeModelProvider, ModelProvider, ModelProviderError, OpenAIModelProvider
from app.agent.tools import (
    BoundAnalyticsInput,
    BoundDatasetReferenceInput,
    BoundWorkflowCompareInput,
    GeneralDocumentSearchInput,
    ResourceListInput,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ScenarioStep(StrictModel):
    tool: str = Field(min_length=1, max_length=100)
    required_arguments: dict[str, Any] = Field(default_factory=dict)
    observation: ToolObservation


class CaseExpectation(StrictModel):
    tool_sequence: list[str] = Field(default_factory=list)
    resource_argument_paths: dict[str, list[str]] = Field(default_factory=dict)
    allowed_resource_ids: list[str] = Field(default_factory=list)
    allowed_source_ids: list[str] = Field(default_factory=list)
    required_source_ids: list[str] = Field(default_factory=list)
    allowed_evidence_keys: list[str] = Field(default_factory=list)
    allowed_numbers: list[str] = Field(default_factory=list)
    required_answer_terms: list[str] = Field(default_factory=list)
    forbidden_answer_terms: list[str] = Field(default_factory=list)
    completion_kind: Literal["answer", "clarification", "refusal"] = "answer"
    max_tool_calls: int = Field(default=8, ge=0, le=25)


class ModelEvaluationCase(StrictModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_]+$")
    capability: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=10000)
    tools: list[str] = Field(default_factory=list)
    steps: list[ScenarioStep] = Field(default_factory=list)
    fixture_decisions: list[ModelDecision] = Field(default_factory=list)
    expectation: CaseExpectation


class EvaluationSuite(StrictModel):
    version: int = Field(ge=1)
    cases: list[ModelEvaluationCase] = Field(min_length=1)


class HumanJudgment(StrictModel):
    case_id: str
    score: int = Field(ge=1, le=5)
    notes: str = Field(min_length=1, max_length=2000)


class HumanJudgmentFile(StrictModel):
    judgments: list[HumanJudgment]


class ProviderFactory(Protocol):
    provider_name: str
    model_name: str
    mode: Literal["offline", "live"]

    def create(self, case: ModelEvaluationCase, tool_specifications: list[dict[str, Any]]) -> ModelProvider: ...


class FixtureProviderFactory:
    provider_name = "fixture"
    model_name = "offline-contract"
    mode: Literal["offline"] = "offline"

    def create(self, case: ModelEvaluationCase, tool_specifications: list[dict[str, Any]]) -> ModelProvider:
        del tool_specifications
        return FakeModelProvider(case.fixture_decisions)


class OpenAIProviderFactory:
    provider_name = "openai"
    mode: Literal["live"] = "live"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        max_output_tokens: int,
        base_url: str | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("A non-empty model evaluation API key is required.")
        self._api_key = api_key
        self.model_name = model
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._max_output_tokens = max_output_tokens
        self._base_url = base_url

    def create(self, case: ModelEvaluationCase, tool_specifications: list[dict[str, Any]]) -> ModelProvider:
        del case
        return OpenAIModelProvider(
            self._api_key,
            self.model_name,
            tool_specifications,
            self._timeout_seconds,
            self._max_retries,
            self._base_url,
            self._max_output_tokens,
        )


_TOOL_MODELS: dict[str, type[BaseModel]] = {
    "resource.list": ResourceListInput,
    "dataset.inspect": BoundDatasetReferenceInput,
    "analytics.execute": BoundAnalyticsInput,
    "document.search": GeneralDocumentSearchInput,
    "workflow.compare_runs": BoundWorkflowCompareInput,
}

_TOOL_DESCRIPTIONS = {
    "resource.list": "List the exact resources authorized for this task before selecting one.",
    "dataset.inspect": "Inspect one bound dataset's columns and quality metadata.",
    "analytics.execute": "Run a typed deterministic analytical plan on one bound dataset.",
    "document.search": "Retrieve grounded document evidence with source provenance.",
    "workflow.compare_runs": "Compare two completed bound workflow runs using persisted deterministic facts.",
}

_NUMBER = re.compile(r"(?<![A-Za-z0-9])[-+]?\d+(?:,\d{3})*(?:\.\d+)?%?")


def evaluate_model_suite(
    path: Path,
    factory: ProviderFactory,
    *,
    input_cost_per_million: float | None = None,
    output_cost_per_million: float | None = None,
    judgments_path: Path | None = None,
) -> dict[str, Any]:
    suite = EvaluationSuite.model_validate_json(path.read_text(encoding="utf-8"))
    judgments = _load_judgments(judgments_path)
    results = [_evaluate_case(case, factory) for case in suite.cases]
    deterministic = _aggregate_deterministic(results)
    usage = _aggregate_usage(results, input_cost_per_million, output_cost_per_million)
    quality = _quality_judgment(results, judgments)
    return {
        "suite_version": suite.version,
        "mode": factory.mode,
        "provider": factory.provider_name,
        "model": factory.model_name,
        "deterministic_checks": deterministic,
        "provider_metrics": usage,
        "model_quality_judgment": quality,
        "cases": results,
        "scope": (
            "Offline fixture-provider contract evaluation; no hosted request was made."
            if factory.mode == "offline"
            else "Opt-in live model decision evaluation; deterministic tools are simulated from controlled observations."
        ),
    }


def _evaluate_case(case: ModelEvaluationCase, factory: ProviderFactory) -> dict[str, Any]:
    tool_models = _case_tool_models(case)
    specifications = [
        {
            "name": name,
            "description": _TOOL_DESCRIPTIONS[name],
            "input_schema": model.model_json_schema(),
        }
        for name, model in tool_models.items()
    ]
    provider = factory.create(case, specifications)
    observations: list[ToolObservation] = []
    calls: list[dict[str, Any]] = []
    call_metrics: list[dict[str, Any]] = []
    completed: Complete | None = None
    provider_error: str | None = None
    next_step = 0
    max_turns = max(2, min(25, len(case.steps) + 5))

    for _ in range(max_turns):
        try:
            decision = provider.decide(case.goal, observations)
        except ModelProviderError as exc:
            provider_error = exc.code
            break
        except Exception:
            provider_error = "provider_failure"
            break
        metrics = getattr(provider, "last_call_metrics", None)
        if metrics is not None:
            call_metrics.append({
                "latency_ms": metrics.latency_ms,
                "input_tokens": metrics.input_tokens,
                "output_tokens": metrics.output_tokens,
                "total_tokens": metrics.total_tokens,
            })
        if isinstance(decision, Complete):
            completed = decision
            break

        call = _validate_call(decision, tool_models, case.expectation)
        calls.append(call)
        expected_step = case.steps[next_step] if next_step < len(case.steps) else None
        if not call["arguments_valid"]:
            observation = ToolObservation(
                success=False,
                summary="The controlled tool rejected invalid structured arguments.",
                error_code="invalid_arguments",
            )
        elif expected_step is None or decision.tool != expected_step.tool:
            observation = ToolObservation(
                success=False,
                summary="The selected tool is not the next required action in this controlled scenario.",
                error_code="unexpected_tool",
            )
        elif not _contains_subset(decision.arguments, expected_step.required_arguments):
            call["expected_arguments_match"] = False
            observation = ToolObservation(
                success=False,
                summary="The tool arguments do not match the controlled scenario requirements.",
                error_code="invalid_arguments",
            )
        else:
            call["expected_arguments_match"] = True
            observation = expected_step.observation
            next_step += 1
        observations.append(
            observation.model_copy(update={"tool_name": decision.tool, "arguments": decision.arguments})
        )

    scores = _score_case(case, calls, completed, next_step, provider_error)
    return {
        "id": case.id,
        "capability": case.capability,
        "passed": all(scores.values()),
        "deterministic_checks": scores,
        "tool_sequence": [call["tool"] for call in calls],
        "invalid_tool_arguments": sum(not call["arguments_valid"] for call in calls),
        "hallucinated_tool_arguments": sum(bool(call["hallucinated_resources"]) for call in calls),
        "unnecessary_tool_calls": max(0, len(calls) - len(case.expectation.tool_sequence)),
        "provider_error": provider_error,
        "provider_calls": call_metrics,
    }


def _case_tool_models(case: ModelEvaluationCase) -> dict[str, type[BaseModel]]:
    unknown = sorted(set(case.tools) - set(_TOOL_MODELS))
    if unknown:
        raise ValueError(f"Evaluation case '{case.id}' names unsupported tools: {', '.join(unknown)}")
    return {name: _TOOL_MODELS[name] for name in case.tools}


def _validate_call(
    decision: ToolCall,
    tool_models: dict[str, type[BaseModel]],
    expectation: CaseExpectation,
) -> dict[str, Any]:
    model = tool_models.get(decision.tool)
    valid = model is not None
    if model is not None:
        try:
            model.model_validate(decision.arguments)
        except ValidationError:
            valid = False
    hallucinated = []
    for path in expectation.resource_argument_paths.get(decision.tool, []):
        value = _path_value(decision.arguments, path)
        if value is not None and str(value) not in expectation.allowed_resource_ids:
            hallucinated.append({"path": path, "value": str(value)})
    return {
        "tool": decision.tool,
        "arguments_valid": valid,
        "hallucinated_resources": hallucinated,
        "expected_arguments_match": None,
    }


def _score_case(
    case: ModelEvaluationCase,
    calls: list[dict[str, Any]],
    completed: Complete | None,
    consumed_steps: int,
    provider_error: str | None,
) -> dict[str, bool]:
    expectation = case.expectation
    answer = completed.answer if completed is not None else ""
    answer_lower = answer.lower()
    claims = completed.claims if completed is not None else []
    actual_sources = {source for claim in claims for source in claim.source_ids}
    actual_evidence_keys = {key for claim in claims for key in claim.evidence_keys}
    allowed_numbers = {_normalize_number(value) for value in expectation.allowed_numbers}
    actual_numbers = {_normalize_number(value) for value in _NUMBER.findall(answer)}
    numeric_faithful = actual_numbers.issubset(allowed_numbers)
    for claim in claims:
        if claim.kind == "numeric" and claim.value is not None:
            numeric_faithful = numeric_faithful and _numeric_claim_allowed(claim.value, allowed_numbers)
    evidence_faithful = (
        actual_sources.issubset(set(expectation.allowed_source_ids))
        and set(expectation.required_source_ids).issubset(actual_sources)
        and actual_evidence_keys.issubset(set(expectation.allowed_evidence_keys))
    )
    answer_terms = all(term.lower() in answer_lower for term in expectation.required_answer_terms)
    forbidden_terms = all(term.lower() not in answer_lower for term in expectation.forbidden_answer_terms)
    uncertainty_correct = completed is not None
    if expectation.completion_kind in {"clarification", "refusal"}:
        uncertainty_correct = uncertainty_correct and not calls if not case.steps else uncertainty_correct
    return {
        "task_success": (
            provider_error is None
            and completed is not None
            and consumed_steps == len(case.steps)
            and answer_terms
            and forbidden_terms
            and numeric_faithful
            and evidence_faithful
        ),
        "structured_output_valid": provider_error is None and completed is not None,
        "correct_tool_sequence": [call["tool"] for call in calls] == expectation.tool_sequence,
        "valid_structured_arguments": all(
            call["arguments_valid"] and call["expected_arguments_match"] is not False for call in calls
        ),
        "no_hallucinated_resources": all(not call["hallucinated_resources"] for call in calls),
        "tool_call_budget": len(calls) <= expectation.max_tool_calls,
        "evidence_faithful": evidence_faithful and numeric_faithful,
        "uncertainty_or_refusal_correct": uncertainty_correct,
    }


def _contains_subset(value: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(value, dict) and all(
            key in value and _contains_subset(value[key], child) for key, child in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(value, list) and len(value) == len(expected) and all(
            _contains_subset(actual, wanted) for actual, wanted in zip(value, expected, strict=True)
        )
    return value == expected


def _path_value(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _normalize_number(value: str) -> str:
    return value.replace(",", "").lstrip("+")


def _numeric_claim_allowed(value: float, allowed: set[str]) -> bool:
    candidates = {f"{value:g}", str(value)}
    return any(_normalize_number(candidate) in allowed for candidate in candidates)


def _aggregate_deterministic(results: list[dict[str, Any]]) -> dict[str, Any]:
    checks = list(results[0]["deterministic_checks"])
    case_count = len(results)
    passed = sum(result["passed"] for result in results)
    return {
        "case_count": case_count,
        "passed_count": passed,
        "failed_count": case_count - passed,
        "task_success_rate": passed / case_count,
        "check_rates": {
            check: sum(result["deterministic_checks"][check] for result in results) / case_count
            for check in checks
        },
        "invalid_tool_arguments": sum(result["invalid_tool_arguments"] for result in results),
        "hallucinated_tool_arguments": sum(result["hallucinated_tool_arguments"] for result in results),
        "unnecessary_tool_calls": sum(result["unnecessary_tool_calls"] for result in results),
    }


def _aggregate_usage(
    results: list[dict[str, Any]],
    input_cost_per_million: float | None,
    output_cost_per_million: float | None,
) -> dict[str, Any]:
    calls = [call for result in results for call in result["provider_calls"]]
    latencies = [call["latency_ms"] for call in calls]
    input_tokens = _sum_available(call["input_tokens"] for call in calls)
    output_tokens = _sum_available(call["output_tokens"] for call in calls)
    total_tokens = _sum_available(call["total_tokens"] for call in calls)
    cost = None
    if input_cost_per_million is not None and output_cost_per_million is not None:
        if input_tokens is not None and output_tokens is not None:
            cost = (
                input_tokens * input_cost_per_million / 1_000_000
                + output_tokens * output_cost_per_million / 1_000_000
            )
    return {
        "measured_call_count": len(calls),
        "latency_ms_total": sum(latencies) if latencies else None,
        "latency_ms_mean": mean(latencies) if latencies else None,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "approximate_cost_usd": cost,
        "cost_basis": (
            {
                "input_usd_per_million_tokens": input_cost_per_million,
                "output_usd_per_million_tokens": output_cost_per_million,
                "source": "operator_supplied",
            }
            if input_cost_per_million is not None and output_cost_per_million is not None
            else None
        ),
    }


def _sum_available(values) -> int | None:
    items = list(values)
    if not items or any(item is None for item in items):
        return None
    return sum(items)


def _load_judgments(path: Path | None) -> dict[str, HumanJudgment]:
    if path is None:
        return {}
    parsed = HumanJudgmentFile.model_validate_json(path.read_text(encoding="utf-8"))
    result = {item.case_id: item for item in parsed.judgments}
    if len(result) != len(parsed.judgments):
        raise ValueError("Human judgment case IDs must be unique.")
    return result


def _quality_judgment(results: list[dict[str, Any]], judgments: dict[str, HumanJudgment]) -> dict[str, Any]:
    unknown = sorted(set(judgments) - {result["id"] for result in results})
    if unknown:
        raise ValueError(f"Human judgments name unknown cases: {', '.join(unknown)}")
    if not judgments:
        return {
            "status": "not_supplied",
            "mean_score": None,
            "scored_case_count": 0,
            "rubric": "Human reviewer scores semantic usefulness, clarity, and appropriate uncertainty from 1 to 5.",
        }
    return {
        "status": "partial" if len(judgments) < len(results) else "complete",
        "mean_score": mean(item.score for item in judgments.values()),
        "scored_case_count": len(judgments),
        "rubric": "Human reviewer scores semantic usefulness, clarity, and appropriate uncertainty from 1 to 5.",
        "judgments": [item.model_dump(mode="json") for item in judgments.values()],
    }


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("Cost rates cannot be negative.")
    return parsed


def _live_factories(args) -> list[OpenAIProviderFactory]:
    api_key = (
        os.getenv("MODEL_EVAL_API_KEY")
        or os.getenv("ORCHESTRATOR_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    if not api_key:
        raise SystemExit(
            "Live evaluation requires MODEL_EVAL_API_KEY, ORCHESTRATOR_API_KEY, or OPENAI_API_KEY."
        )
    models = args.model or [item.strip() for item in os.getenv("MODEL_EVAL_MODELS", "").split(",") if item.strip()]
    if not models:
        raise SystemExit("Live evaluation requires at least one --model or MODEL_EVAL_MODELS value.")
    return [
        OpenAIProviderFactory(
            api_key=api_key,
            model=model,
            timeout_seconds=args.timeout_seconds,
            max_retries=args.max_retries,
            max_output_tokens=args.max_output_tokens,
            base_url=args.base_url or os.getenv("ORCHESTRATOR_BASE_URL"),
        )
        for model in models
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate workspace-specific model planning and evidence behavior.")
    parser.add_argument("path", type=Path, help="Path to model evaluation scenarios JSON.")
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--provider", choices=("openai",), default="openai")
    parser.add_argument("--model", action="append", help="Live model name; repeat to compare models.")
    parser.add_argument("--base-url", help="Optional Responses-compatible HTTP(S) base URL.")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--max-output-tokens", type=int, default=3000)
    parser.add_argument("--input-cost-per-million", type=_positive_float)
    parser.add_argument("--output-cost-per-million", type=_positive_float)
    parser.add_argument("--judgments", type=Path, help="Optional human model-quality judgments JSON.")
    parser.add_argument("--output", type=Path, help="Optional JSON report path.")
    args = parser.parse_args()
    if (args.input_cost_per_million is None) != (args.output_cost_per_million is None):
        parser.error("Supply both input and output cost rates, or neither.")
    if not 0 < args.timeout_seconds <= 120:
        parser.error("Timeout must be greater than zero and at most 120 seconds.")
    if not 0 <= args.max_retries <= 5:
        parser.error("Retries must be between zero and five.")
    if not 0 < args.max_output_tokens <= 20_000:
        parser.error("Output tokens must be between 1 and 20,000.")

    factories: list[ProviderFactory]
    if args.mode == "offline":
        factories = [FixtureProviderFactory()]
    else:
        factories = _live_factories(args)
    reports = [
        evaluate_model_suite(
            args.path,
            factory,
            input_cost_per_million=args.input_cost_per_million,
            output_cost_per_million=args.output_cost_per_million,
            judgments_path=args.judgments,
        )
        for factory in factories
    ]
    result: dict[str, Any] = {"evaluations": reports}
    rendered = json.dumps(result, indent=2)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if any(report["deterministic_checks"]["failed_count"] for report in reports):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
