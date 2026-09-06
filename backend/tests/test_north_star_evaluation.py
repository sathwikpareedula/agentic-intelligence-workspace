"""Regression coverage for the controlled north-star evaluator."""

from pathlib import Path

from app.evaluation.north_star import evaluate_north_star_cases


ROOT = Path(__file__).parents[2]


def test_controlled_north_star_evaluation_passes_all_cases() -> None:
    result = evaluate_north_star_cases(
        ROOT / "evals" / "north_star_cases.json",
        ROOT / "sample_data",
    )

    assert result["case_count"] == 14
    assert result["passed_count"] == 14
    assert result["failed_count"] == 0
    assert result["case_pass_rate"] == 1.0
    assert "offline scripted provider" in result["scope"]
