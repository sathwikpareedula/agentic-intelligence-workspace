"""Evidence-based verification tests."""

from app.agent.models import AnswerClaim, ToolObservation
from app.agent.verification import EvidenceVerifier


def _calculation(status="required"):
    return ToolObservation(
        success=True,
        summary="Calculated.",
        result={"status": status, "required_final_percentage": 94.666667},
        source_ids=["chunk-1"],
    )


def test_correct_numeric_and_cited_document_claims_are_verified() -> None:
    report = EvidenceVerifier().verify(
        [
            AnswerClaim(text="The required final is 94.666667%.", kind="numeric", value=94.666667),
            AnswerClaim(text="An A requires 90%.", kind="document", source_ids=["chunk-1"]),
        ],
        [_calculation()],
    )
    assert report.status == "verified"
    assert all(finding.status == "verified" for finding in report.findings)


def test_incorrect_numeric_and_unsupported_document_claims_are_rejected() -> None:
    report = EvidenceVerifier().verify(
        [
            AnswerClaim(text="The required final is 80%.", kind="numeric", value=80),
            AnswerClaim(text="Late work is accepted.", kind="document", source_ids=["invented"]),
        ],
        [_calculation()],
    )
    assert report.status == "unsupported"
    assert [finding.status for finding in report.findings] == ["unsupported", "unsupported"]


def test_missing_and_conflicting_evidence_are_structured() -> None:
    missing = EvidenceVerifier().verify([AnswerClaim(text="Policy statement", kind="document")], [])
    conflicting = EvidenceVerifier().verify([], [_calculation("conflicting_evidence")])
    insufficient = EvidenceVerifier().verify([], [_calculation("insufficient_evidence")])
    failed = EvidenceVerifier().verify([], [ToolObservation(success=False, summary="failed", error_code="tool_error")])
    assert missing.status == "insufficient_evidence"
    assert conflicting.status == "conflicting"
    assert insufficient.status == "insufficient_evidence"
    assert failed.status == "failed"


def test_named_numeric_evidence_prevents_accidental_value_collision() -> None:
    report = EvidenceVerifier().verify(
        [
            AnswerClaim(
                text="North sales are 100.",
                kind="numeric",
                value=100,
                evidence_keys=["regional.North.net_sales"],
            )
        ],
        [
            ToolObservation(
                success=True,
                summary="Calculated.",
                result={
                    "verification_facts": {
                        "regional.North.net_sales": 90,
                        "unrelated.value": 100,
                    }
                },
            )
        ],
    )

    assert report.status == "unsupported"


def test_commission_claim_requires_both_deterministic_fact_and_policy_source() -> None:
    observation = ToolObservation(
        success=True,
        summary="Calculated.",
        result={"verification_facts": {"commission.Alice": 67.5}},
        source_ids=["policy-chunk"],
    )
    missing_citation = EvidenceVerifier().verify(
        [AnswerClaim(text="Alice commission", kind="numeric", value=67.5, evidence_keys=["commission.Alice"])],
        [observation],
    )
    grounded = EvidenceVerifier().verify(
        [
            AnswerClaim(
                text="Alice commission",
                kind="numeric",
                value=67.5,
                evidence_keys=["commission.Alice"],
                source_ids=["policy-chunk"],
            )
        ],
        [observation],
    )

    assert missing_citation.status == "insufficient_evidence"
    assert grounded.status == "verified"


def test_data_diagnostic_warning_is_visible_without_erasing_verified_claims() -> None:
    report = EvidenceVerifier().verify(
        [AnswerClaim(text="Total", kind="numeric", value=10, evidence_keys=["total.net_sales"])],
        [
            ToolObservation(
                success=True,
                summary="Calculated.",
                result={"verification_facts": {"total.net_sales": 10}},
                warnings=["One customer key was unmatched."],
            )
        ],
    )

    assert report.status == "verified_with_warnings"
    assert [finding.status for finding in report.findings] == ["warning", "verified"]
