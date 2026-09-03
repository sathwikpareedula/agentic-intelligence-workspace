"""Controlled product evaluation harness tests."""

import json
from pathlib import Path
import sys

import pytest

from app.evaluation.product import evaluate_product_cases, main


ROOT = Path(__file__).parents[2]


def test_controlled_product_evaluation() -> None:
    result = evaluate_product_cases(ROOT / "evals" / "product_cases.json", ROOT / "sample_data")

    assert result["case_count"] == 7
    assert result["passed_count"] == 7
    assert result["failed_count"] == 0
    assert result["case_pass_rate"] == 1.0
    assert all(case["passed"] for case in result["cases"])


def test_product_evaluation_reports_ground_truth_regression(tmp_path: Path) -> None:
    cases = json.loads((ROOT / "evals" / "product_cases.json").read_text(encoding="utf-8"))
    cases["grade_required_final"] = 100.0
    path = tmp_path / "product_cases.json"
    path.write_text(json.dumps(cases), encoding="utf-8")

    result = evaluate_product_cases(path, ROOT / "sample_data")

    failed = [case["name"] for case in result["cases"] if not case["passed"]]
    assert result["passed_count"] == 6
    assert result["failed_count"] == 1
    assert failed == ["grade_required_final"]


def test_product_evaluation_cli_resolves_samples_and_fails_on_regression(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cases = json.loads((ROOT / "evals" / "product_cases.json").read_text(encoding="utf-8"))
    cases["grade_required_final"] = 100.0
    path = tmp_path / "product_cases.json"
    path.write_text(json.dumps(cases), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["product-eval", str(path), "--sample-root", str(ROOT / "sample_data")],
    )

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 1
