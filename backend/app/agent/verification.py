"""Practical verification against the agent's own deterministic observations."""

from math import isclose

from app.agent.models import AnswerClaim, ToolObservation, VerificationFinding, VerificationReport


class EvidenceVerifier:
    def verify(self, claims: list[AnswerClaim], observations: list[ToolObservation]) -> VerificationReport:
        findings: list[VerificationFinding] = []
        source_ids = {source for item in observations if item.success for source in item.source_ids}
        values = []
        result_statuses = set()
        for item in observations:
            if item.result:
                values.extend(_numeric_values(item.result))
                if isinstance(item.result.get("status"), str):
                    result_statuses.add(item.result["status"])

        if any(not item.success and item.error_code == "tool_error" for item in observations):
            findings.append(VerificationFinding(status="failed", claim="tool execution", explanation="A deterministic tool failed."))
        if "conflicting_evidence" in result_statuses:
            findings.append(VerificationFinding(status="conflicting", claim="evidence consistency", explanation="A deterministic tool reported conflicting evidence."))
        if "insufficient_evidence" in result_statuses:
            findings.append(VerificationFinding(status="insufficient_evidence", claim="evidence sufficiency", explanation="A deterministic tool reported insufficient evidence."))

        for claim in claims:
            if claim.kind == "numeric":
                if claim.value is not None and any(isclose(claim.value, value, rel_tol=1e-9, abs_tol=1e-6) for value in values):
                    findings.append(VerificationFinding(status="verified", claim=claim.text, explanation="Numeric value matches a deterministic tool output."))
                else:
                    findings.append(VerificationFinding(status="unsupported", claim=claim.text, explanation="Numeric value does not match a deterministic tool output."))
            else:
                if claim.source_ids and set(claim.source_ids).issubset(source_ids):
                    findings.append(VerificationFinding(status="verified", claim=claim.text, explanation="Claim cites evidence returned by a successful retrieval or calculation."))
                elif not claim.source_ids:
                    findings.append(VerificationFinding(status="insufficient_evidence", claim=claim.text, explanation="Document claim has no citations."))
                else:
                    findings.append(VerificationFinding(status="unsupported", claim=claim.text, explanation="Claim citations were not present in observed evidence."))

        precedence = ["failed", "conflicting", "unsupported", "insufficient_evidence", "verified"]
        statuses = {finding.status for finding in findings}
        overall = next((status for status in precedence if status in statuses), "insufficient_evidence")
        return VerificationReport(status=overall, findings=findings)


def _numeric_values(value) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, dict):
        return [number for child in value.values() for number in _numeric_values(child)]
    if isinstance(value, list):
        return [number for child in value for number in _numeric_values(child)]
    return []
