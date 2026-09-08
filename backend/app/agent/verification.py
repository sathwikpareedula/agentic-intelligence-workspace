"""Practical verification against the agent's own deterministic observations."""

from math import isclose, isfinite

from app.agent.models import AnswerClaim, ToolObservation, VerificationFinding, VerificationReport


class EvidenceVerifier:
    def verify(self, claims: list[AnswerClaim], observations: list[ToolObservation]) -> VerificationReport:
        findings: list[VerificationFinding] = []
        source_ids = {source for item in observations if item.success for source in item.source_ids}
        values = []
        facts: dict[str, float] = {}
        fact_units: dict[str, str] = {}
        ambiguous_fact_keys: set[str] = set()
        result_statuses = set()
        for item in observations:
            if item.result and item.success:
                values.extend(_numeric_values(item.result))
                raw_facts = item.result.get("verification_facts", {})
                if isinstance(raw_facts, dict):
                    for key, value in raw_facts.items():
                        if not isinstance(value, (int, float)) or isinstance(value, bool):
                            continue
                        numeric = float(value)
                        if not isfinite(numeric):
                            continue
                        normalized_key = str(key)
                        if normalized_key in facts:
                            ambiguous_fact_keys.add(normalized_key)
                        else:
                            facts[normalized_key] = numeric
                raw_fact_details = item.result.get("facts", [])
                if isinstance(raw_fact_details, list):
                    for detail in raw_fact_details:
                        if not isinstance(detail, dict) or not isinstance(detail.get("key"), str):
                            continue
                        unit = detail.get("unit")
                        if isinstance(unit, str) and unit:
                            key = detail["key"]
                            if key in fact_units and fact_units[key].casefold() != unit.casefold():
                                ambiguous_fact_keys.add(key)
                            else:
                                fact_units[key] = unit
            if item.result and isinstance(item.result.get("status"), str):
                result_statuses.add(item.result["status"])
            for warning in item.warnings:
                findings.append(
                    VerificationFinding(
                        status="warning",
                        claim="data and join diagnostics",
                        explanation=warning,
                    )
                )

        if "failed" in result_statuses or any(not item.success and item.error_code == "tool_error" for item in observations):
            findings.append(VerificationFinding(status="failed", claim="tool execution", explanation="A deterministic tool failed."))
        if "conflicting_evidence" in result_statuses:
            findings.append(VerificationFinding(status="conflicting", claim="evidence consistency", explanation="A deterministic tool reported conflicting evidence."))
        if "insufficient_evidence" in result_statuses:
            findings.append(VerificationFinding(status="insufficient_evidence", claim="evidence sufficiency", explanation="A deterministic tool reported insufficient evidence."))

        for claim in claims:
            if claim.kind == "numeric":
                ambiguous_keys = [key for key in claim.evidence_keys if key in ambiguous_fact_keys]
                if ambiguous_keys:
                    findings.append(
                        VerificationFinding(
                            status="unsupported",
                            claim=claim.text,
                            explanation="Named deterministic fact identity is ambiguous across multiple tool results.",
                        )
                    )
                    continue
                keyed_values = [facts[key] for key in claim.evidence_keys if key in facts]
                candidates = keyed_values if claim.evidence_keys else ([] if facts else values)
                matches = [
                    isclose(claim.value, value, rel_tol=1e-9, abs_tol=1e-6)
                    for value in candidates if claim.value is not None
                ]
                numeric_match = bool(matches) and (all(matches) if claim.evidence_keys else any(matches))
                missing_keys = [key for key in claim.evidence_keys if key not in facts]
                expected_units = {
                    fact_units[key].casefold()
                    for key in claim.evidence_keys
                    if key in fact_units
                }
                unit_matches = not expected_units or (
                    claim.unit is not None
                    and len(expected_units) == 1
                    and claim.unit.casefold() in expected_units
                )
                commission_claim = any(key.startswith("commission.") or key == "total.commission" for key in claim.evidence_keys)
                policy_grounded = not commission_claim or (
                    bool(claim.source_ids) and set(claim.source_ids).issubset(source_ids)
                )
                if numeric_match and not missing_keys and policy_grounded and unit_matches:
                    explanation = "Numeric value matches the named deterministic tool output."
                    if commission_claim:
                        explanation += " The commission claim also cites observed policy evidence."
                    findings.append(VerificationFinding(status="verified", claim=claim.text, explanation=explanation))
                elif numeric_match and not missing_keys and not unit_matches:
                    findings.append(
                        VerificationFinding(
                            status="unsupported",
                            claim=claim.text,
                            explanation="Numeric value matches, but the claim does not preserve the deterministic fact unit.",
                        )
                    )
                elif commission_claim and numeric_match and not policy_grounded:
                    findings.append(VerificationFinding(status="insufficient_evidence", claim=claim.text, explanation="Commission value matches deterministic output but is not linked to observed policy evidence."))
                else:
                    findings.append(VerificationFinding(status="unsupported", claim=claim.text, explanation="Numeric value does not match the named deterministic tool output."))
            else:
                if claim.source_ids and set(claim.source_ids).issubset(source_ids):
                    findings.append(VerificationFinding(status="verified", claim=claim.text, explanation="Claim cites evidence returned by a successful retrieval or calculation."))
                elif not claim.source_ids:
                    findings.append(VerificationFinding(status="insufficient_evidence", claim=claim.text, explanation="Document claim has no citations."))
                else:
                    findings.append(VerificationFinding(status="unsupported", claim=claim.text, explanation="Claim citations were not present in observed evidence."))

        precedence = ["failed", "conflicting", "unsupported", "insufficient_evidence"]
        statuses = {finding.status for finding in findings}
        overall = next((status for status in precedence if status in statuses), None)
        if overall is None:
            overall = "verified_with_warnings" if "warning" in statuses and "verified" in statuses else (
                "verified" if "verified" in statuses else "insufficient_evidence"
            )
        return VerificationReport(status=overall, findings=findings)


def _numeric_values(value) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except (OverflowError, ValueError):
            return []
        return [number] if isfinite(number) else []
    if isinstance(value, dict):
        return [number for child in value.values() for number in _numeric_values(child)]
    if isinstance(value, list):
        return [number for child in value for number in _numeric_values(child)]
    return []
