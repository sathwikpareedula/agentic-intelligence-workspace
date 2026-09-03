"""End-to-end tests for the grades CSV plus syllabus PDF workflow."""

import base64
from io import BytesIO
from uuid import UUID

import pandas as pd
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.agent.models import Complete, ToolCall
from app.agent.orchestrator import AgentOrchestrator
from app.agent.providers import FakeModelProvider
from app.agent.tools import ToolRegistry, grade_tool, retrieval_tool
from app.evaluation.retrieval import EvaluationEmbeddingProvider
from app.models.grades import PolicyEvidence
from app.models.retrieval import SourceReference
from app.repositories.documents import InMemoryDocumentRepository
from app.services.grades import GradeCalculationError, calculate_required_final
from app.services.retrieval import RetrievalService


def _pdf_bytes(text: str) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(output)
    return output.getvalue()


def _source(seed: int = 1) -> SourceReference:
    return SourceReference(document_id=UUID(int=seed), filename="syllabus.pdf", page_number=1, chunk_id=UUID(int=seed + 10))


def _evidence(text="Grading policy: An A requires at least 90%. The final exam is 30% of the course grade."):
    return [PolicyEvidence(text=text, source=_source())]


def test_grade_calculator_expected_and_edge_cases() -> None:
    standard = pd.DataFrame({"category": ["Homework", "Midterm", "Final Exam"], "score": [90, 80, None], "weight": [30, 40, 30]})
    result = calculate_required_final(standard, _evidence())
    assert result.status == "impossible"
    assert result.completed_contribution == 59
    assert result.required_final_percentage == 103.333333

    impossible = calculate_required_final(pd.DataFrame({"category": ["Work", "Final"], "score": [40, None], "weight": [70, 30]}), _evidence())
    guaranteed = calculate_required_final(pd.DataFrame({"category": ["Work", "Final"], "score": [100, None], "weight": [100, 0]}), [PolicyEvidence(text="An A requires at least 90%. The final exam is 0%.", source=_source())])
    assert impossible.status == "impossible"
    assert guaranteed.status == "already_guaranteed"


def test_grade_calculator_reports_evidence_and_data_failures() -> None:
    frame = pd.DataFrame({"category": ["Work", "Final"], "score": [95, None], "weight": [70, 30]})
    insufficient = calculate_required_final(frame, [PolicyEvidence(text="Grades are described elsewhere.", source=_source())])
    conflicting = calculate_required_final(frame, [*_evidence(), PolicyEvidence(text="An A requires at least 93%. The final exam is 40%.", source=_source(2))])
    assert insufficient.status == "insufficient_evidence"
    assert conflicting.status == "conflicting_evidence"

    try:
        calculate_required_final(pd.DataFrame({"category": ["Final"], "score": [None]}), _evidence())
    except GradeCalculationError as exc:
        assert "missing required" in str(exc)
    else:
        raise AssertionError("Missing grade columns must fail.")


def test_grades_and_syllabus_execute_as_grounded_multistep_agent_workflow() -> None:
    service = RetrievalService(InMemoryDocumentRepository(), EvaluationEmbeddingProvider(), 1024 * 1024)
    ingested = service.ingest_pdf("syllabus.pdf", _pdf_bytes("Grading policy: An A requires at least 90%. The final exam is 30% of the course grade."), 500, 50)
    evidence_response = service.search("A threshold and final exam weight", 1, ingested.document_id)
    evidence = [{"text": hit.text, "source": hit.source.model_dump(mode="json")} for hit in evidence_response.hits]
    grades = base64.b64encode(b"category,score,weight\nHomework,92,25\nQuizzes,88,20\nMidterm,84,25\nFinal Exam,,30\n").decode()
    decisions = [
        ToolCall(tool="document.search", arguments={"query": "A threshold and final exam weight", "top_k": 1, "document_id": str(ingested.document_id)}),
        ToolCall(tool="grades.required_final", arguments={"filename": "grades.csv", "content_base64": grades, "evidence": evidence}),
        Complete(answer="You need at least 94.67% on the final, based on the cited policy and deterministic calculation."),
    ]
    result = AgentOrchestrator(FakeModelProvider(decisions), ToolRegistry([retrieval_tool(service), grade_tool()])).execute("What do I need on my final for an A?")

    assert result.status == "completed"
    assert [step.requested_tool for step in result.trace] == ["document.search", "grades.required_final"]
    assert result.trace[0].source_ids
    assert result.trace[1].source_ids == result.trace[0].source_ids
    assert "94.67%" in result.answer
