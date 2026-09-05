"""Tests for the controlled generalized-agent evaluation harness."""

from pathlib import Path

from app.evaluation.agent import evaluate_agent_cases


ROOT = Path(__file__).parents[2]


def test_controlled_agent_evaluation_passes_all_cases() -> None:
    result = evaluate_agent_cases(ROOT / "evals" / "agent_cases.json")

    assert result["case_count"] == 5
    assert result["passed_count"] == 5
    assert result["failed_count"] == 0
    assert result["case_pass_rate"] == 1.0
    assert "scripted-provider" in result["scope"]
