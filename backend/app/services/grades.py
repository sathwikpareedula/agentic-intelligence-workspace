"""Evidence-bound, deterministic weighted-grade calculation."""

import re

import pandas as pd

from app.models.grades import PolicyEvidence, RequiredFinalResult


class GradeCalculationError(Exception):
    """Raised when grade data is malformed or incomplete."""


def calculate_required_final(frame: pd.DataFrame, evidence: list[PolicyEvidence], target_letter: str = "A") -> RequiredFinalResult:
    required_columns = {"category", "score", "weight"}
    missing = sorted(required_columns - set(frame.columns))
    if missing:
        raise GradeCalculationError(f"Grade dataset is missing required column(s): {', '.join(missing)}.")

    target_values: set[float] = set()
    final_values: set[float] = set()
    target_pattern = re.compile(rf"\b{re.escape(target_letter)}\b[^.\n]{{0,80}}?(?:at least|minimum(?: of)?|requires?)\s*(\d+(?:\.\d+)?)\s*%", re.I)
    reverse_target_pattern = re.compile(rf"(?:at least|minimum(?: of)?)\s*(\d+(?:\.\d+)?)\s*%[^.\n]{{0,50}}?\b{re.escape(target_letter)}\b", re.I)
    final_pattern = re.compile(r"final(?: exam)?[^.\n]{0,80}?(\d+(?:\.\d+)?)\s*%", re.I)
    used_sources = []
    for item in evidence:
        targets = target_pattern.findall(item.text) + reverse_target_pattern.findall(item.text)
        finals = final_pattern.findall(item.text)
        if targets or finals:
            used_sources.append(item.source)
        target_values.update(float(value) for value in targets)
        final_values.update(float(value) for value in finals)

    if len(target_values) > 1 or len(final_values) > 1:
        return RequiredFinalResult(
            status="conflicting_evidence", target_letter=target_letter, message="Retrieved policy evidence contains conflicting thresholds or final-exam weights.", citations=used_sources
        )
    if not target_values or not final_values:
        return RequiredFinalResult(
            status="insufficient_evidence", target_letter=target_letter, message="The evidence does not establish both the target threshold and final-exam weight.", citations=used_sources
        )
    target = next(iter(target_values))
    final_weight = next(iter(final_values))
    if not 0 <= final_weight <= 100 or not 0 <= target <= 100:
        raise GradeCalculationError("Policy percentages must be between 0 and 100.")

    working = frame.copy()
    working["category"] = working["category"].astype(str).str.strip().str.lower()
    working["score"] = pd.to_numeric(working["score"], errors="coerce")
    working["weight"] = pd.to_numeric(working["weight"], errors="coerce")
    final_rows = working[working["category"].str.contains(r"\bfinal(?: exam)?\b", regex=True)]
    if len(final_rows) != 1:
        raise GradeCalculationError("Grade dataset must contain exactly one final-exam category.")
    dataset_final_weight = float(final_rows.iloc[0]["weight"])
    if abs(dataset_final_weight - final_weight) > 1e-9:
        return RequiredFinalResult(
            status="conflicting_evidence", target_letter=target_letter, target_percentage=target,
            final_weight_percentage=final_weight, message="The dataset final weight conflicts with the grading-policy evidence.", citations=used_sources
        )
    non_final = working.drop(final_rows.index)
    if non_final[["score", "weight"]].isna().any().any():
        raise GradeCalculationError("Completed grade categories require numeric scores and weights.")
    if (non_final["weight"] < 0).any() or ((non_final["score"] < 0) | (non_final["score"] > 100)).any():
        raise GradeCalculationError("Scores must be 0-100 and weights cannot be negative.")
    total_weight = float(non_final["weight"].sum()) + dataset_final_weight
    if abs(total_weight - 100) > 1e-6:
        raise GradeCalculationError("Grade category weights must total 100 percent.")
    contribution = float((non_final["score"] * non_final["weight"] / 100).sum())
    if final_weight == 0:
        status = "already_guaranteed" if contribution >= target else "impossible"
        message = "The target is already guaranteed." if status == "already_guaranteed" else "The target cannot be reached because the final has zero weight."
        return RequiredFinalResult(
            status=status, target_letter=target_letter, target_percentage=target,
            final_weight_percentage=final_weight, completed_contribution=round(contribution, 6),
            required_final_percentage=0 if status == "already_guaranteed" else None, message=message, citations=used_sources,
        )
    required = (target - contribution) / (final_weight / 100)
    common = dict(
        target_letter=target_letter, target_percentage=target, final_weight_percentage=final_weight,
        completed_contribution=round(contribution, 6), required_final_percentage=round(required, 6), citations=used_sources,
    )
    if required > 100:
        return RequiredFinalResult(status="impossible", message=f"The target would require {required:.2f}% on the final, which exceeds 100%.", **common)
    if required <= 0:
        return RequiredFinalResult(status="already_guaranteed", message="The target is already guaranteed even with a zero on the final.", **common)
    return RequiredFinalResult(status="required", message=f"A final-exam score of at least {required:.2f}% is required.", **common)
