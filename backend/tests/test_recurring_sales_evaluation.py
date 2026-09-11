from pathlib import Path

from app.evaluation.recurring_sales import evaluate_recurring_sales_cases


ROOT = Path(__file__).resolve().parents[2]


def test_verified_recurring_sales_scenario_passes_all_cases() -> None:
    result = evaluate_recurring_sales_cases(ROOT / "evals" / "recurring_sales_cases.json")

    assert result["case_count"] == 12
    assert result["passed_count"] == 12
    assert result["failed_count"] == 0
