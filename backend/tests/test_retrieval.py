"""Tests for PDF ingestion, chunking, embeddings, retrieval, and citations."""

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.dependencies import get_retrieval_service
from app.embeddings.base import EmbeddingError
from app.embeddings.openai_provider import OpenAIEmbeddingProvider
from app.evaluation.retrieval import EvaluationEmbeddingProvider, evaluate_cases
from app.main import app
from app.repositories.documents import InMemoryDocumentRepository
from app.services.pdf_documents import (
    ExtractedDocument,
    NoExtractableTextError,
    PageText,
    PdfDocumentError,
    chunk_document,
    extract_pdf,
)
from app.services.retrieval import RetrievalService


def _pdf_bytes(text: str | None = None) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    if text is not None:
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        resources = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1"))
        page[NameObject("/Resources")] = resources
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(output)
    return output.getvalue()


@pytest.fixture
def retrieval_components():
    repository = InMemoryDocumentRepository()
    provider = EvaluationEmbeddingProvider()
    service = RetrievalService(repository, provider, max_pdf_bytes=1024 * 1024)
    return repository, provider, service


@pytest.fixture
def retrieval_client(retrieval_components):
    _, _, service = retrieval_components
    app.dependency_overrides[get_retrieval_service] = lambda: service
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_extract_pdf_text_and_stable_document_identity() -> None:
    content = _pdf_bytes("Vacation requests use the employee portal.")

    first = extract_pdf("handbook.pdf", content, len(content) + 1)
    second = extract_pdf("handbook.pdf", content, len(content) + 1)

    assert first.document_id == second.document_id
    assert first.filename == "handbook.pdf"
    assert first.page_count == 1
    assert first.pages == [PageText(page_number=1, text="Vacation requests use the employee portal.")]


@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        ("document.txt", b"text", "Unsupported file type"),
        ("document.pdf", b"", "uploaded PDF is empty"),
        ("document.pdf", b"%PDF-not-valid", "malformed or unreadable"),
    ],
)
def test_rejects_unsupported_empty_and_malformed_pdf(filename: str, content: bytes, message: str) -> None:
    with pytest.raises(PdfDocumentError, match=message):
        extract_pdf(filename, content, 1024)


def test_blank_pdf_reports_ocr_limitation() -> None:
    content = _pdf_bytes()

    with pytest.raises(NoExtractableTextError, match="OCR is not implemented"):
        extract_pdf("scan.pdf", content, len(content) + 1)


def test_chunking_preserves_pages_overlap_and_stable_ids() -> None:
    document = ExtractedDocument(
        document_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        filename="policy.pdf",
        page_count=2,
        pages=[
            PageText(1, "alpha beta gamma delta epsilon zeta eta theta"),
            PageText(2, "second page evidence"),
        ],
    )

    first = chunk_document(document, chunk_size=24, overlap=8)
    second = chunk_document(document, chunk_size=24, overlap=8)

    assert first == second
    assert all(chunk.text for chunk in first)
    assert [chunk.page_number for chunk in first][-1] == 2
    assert first[0].document_id == document.document_id
    assert set(first[0].text.split()) & set(first[1].text.split())


def test_deterministic_fake_embeddings() -> None:
    provider = EvaluationEmbeddingProvider()

    assert provider.embed_query("repeatable text") == provider.embed_query("repeatable text")
    assert len(provider.embed_query("repeatable text")) == provider.dimension
    assert provider.embed_documents(["one", "two"]) == [provider.embed_query("one"), provider.embed_query("two")]


def test_openai_embedding_provider_batches_without_network() -> None:
    calls = []

    class FakeEmbeddings:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                data=[SimpleNamespace(index=index, embedding=[float(index + 1), 0.0, 0.0]) for index, _ in enumerate(kwargs["input"])]
            )

    provider = OpenAIEmbeddingProvider("test-key", "test-model", dimension=3, batch_size=2)
    provider._client = SimpleNamespace(embeddings=FakeEmbeddings())

    vectors = provider.embed_documents(["one", "two", "three"])

    assert len(calls) == 2
    assert [call["input"] for call in calls] == [["one", "two"], ["three"]]
    assert vectors == [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0], [1.0, 0.0, 0.0]]


def test_ingestion_validates_embedding_dimension(retrieval_components) -> None:
    repository, _, _ = retrieval_components

    class BrokenProvider:
        dimension = 3

        def embed_documents(self, texts):
            return [[1.0, 0.0] for _ in texts]

        def embed_query(self, text):
            return [1.0, 0.0]

    service = RetrievalService(repository, BrokenProvider(), max_pdf_bytes=1024 * 1024)

    with pytest.raises(EmbeddingError, match="dimension 2; expected 3"):
        service.ingest_pdf("policy.pdf", _pdf_bytes("Policy text for embedding."), 500, 50)


def test_retrieval_ranking_top_k_filter_and_citations(retrieval_components) -> None:
    _, _, service = retrieval_components
    vacation = service.ingest_pdf("vacation.pdf", _pdf_bytes("Vacation requests use the employee portal."), 500, 50)
    security = service.ingest_pdf("security.pdf", _pdf_bytes("Report phishing email to the security team."), 500, 50)

    ranked = service.search("Where do I report phishing email?", top_k=1)
    filtered = service.search("employee", top_k=5, document_id=vacation.document_id)

    assert len(ranked.hits) == 1
    assert ranked.hits[0].source.document_id == security.document_id
    assert ranked.hits[0].source.filename == "security.pdf"
    assert ranked.hits[0].source.page_number == 1
    assert ranked.hits[0].source.chunk_id == security.chunks[0].chunk_id
    assert [hit.source.document_id for hit in filtered.hits] == [vacation.document_id]


def test_reingesting_same_pdf_replaces_chunks(retrieval_components) -> None:
    repository, _, service = retrieval_components
    content = _pdf_bytes("A stable document with enough text for multiple deterministic chunks and overlap behavior.")
    first = service.ingest_pdf("stable.pdf", content, 30, 5)
    second = service.ingest_pdf("stable.pdf", content, 500, 10)

    assert first.document_id == second.document_id
    assert first.chunk_count > second.chunk_count
    assert len([chunk for chunk in repository.chunks.values() if chunk.document_id == first.document_id]) == 1


def test_document_api_ingests_and_searches_with_provenance(retrieval_client) -> None:
    ingestion = retrieval_client.post(
        "/documents",
        data={"chunk_size": "500", "chunk_overlap": "50"},
        files={"file": ("security.pdf", _pdf_bytes("Report phishing email to the security team."), "application/pdf")},
    )
    assert ingestion.status_code == 201

    search = retrieval_client.post("/retrieval/search", json={"query": "phishing email", "top_k": 1})

    assert search.status_code == 200
    source = search.json()["hits"][0]["source"]
    assert source["document_id"] == ingestion.json()["document_id"]
    assert source["chunk_id"] == ingestion.json()["chunks"][0]["chunk_id"]
    assert source["filename"] == "security.pdf"
    assert source["page_number"] == 1


def test_document_api_errors_are_clear(retrieval_client) -> None:
    unsupported = retrieval_client.post(
        "/documents", files={"file": ("notes.txt", b"hello", "text/plain")}
    )
    malformed = retrieval_client.post(
        "/documents", files={"file": ("bad.pdf", b"%PDF-bad", "application/pdf")}
    )
    no_text = retrieval_client.post(
        "/documents", files={"file": ("scan.pdf", _pdf_bytes(), "application/pdf")}
    )

    assert unsupported.status_code == 415
    assert malformed.status_code == 422
    assert no_text.status_code == 422
    assert "OCR is not implemented" in no_text.json()["detail"]


def test_document_api_enforces_size_and_chunk_configuration(retrieval_client) -> None:
    too_large = retrieval_client.post(
        "/documents",
        files={"file": ("large.pdf", b"%PDF-" + b"x" * (1024 * 1024), "application/pdf")},
    )
    bad_chunks = retrieval_client.post(
        "/documents",
        data={"chunk_size": "100", "chunk_overlap": "100"},
        files={"file": ("policy.pdf", _pdf_bytes("Text that can be extracted."), "application/pdf")},
    )

    assert too_large.status_code == 413
    assert bad_chunks.status_code == 422
    assert "smaller than chunk size" in bad_chunks.json()["detail"]


def test_retrieval_api_validates_request(retrieval_client) -> None:
    response = retrieval_client.post("/retrieval/search", json={"query": "test", "top_k": 0})
    extra = retrieval_client.post("/retrieval/search", json={"query": "test", "unknown": True})
    whitespace = retrieval_client.post("/retrieval/search", json={"query": "   "})

    assert response.status_code == 422
    assert extra.status_code == 422
    assert whitespace.status_code == 422


def test_controlled_retrieval_evaluation() -> None:
    path = Path(__file__).parents[2] / "evals" / "retrieval_cases.json"

    result = evaluate_cases(path)

    assert result["query_count"] == 3
    assert result["hit_at_k"] == 1.0
    assert result["mean_reciprocal_rank"] == 1.0
    assert all(case["passed"] for case in result["cases"])
