"""Executable deterministic retrieval evaluation."""

import argparse
import json
from pathlib import Path
from uuid import UUID

from app.embeddings.deterministic import DeterministicEmbeddingProvider
from app.repositories.documents import InMemoryDocumentRepository, StoredChunk, StoredDocument
from app.services.retrieval import RetrievalService

EvaluationEmbeddingProvider = DeterministicEmbeddingProvider


def evaluate_cases(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    provider = DeterministicEmbeddingProvider()
    repository = InMemoryDocumentRepository()
    for document_data in data["documents"]:
        document_id = UUID(document_data["document_id"])
        texts = [chunk["text"] for chunk in document_data["chunks"]]
        embeddings = provider.embed_documents(texts)
        repository.save_document(
            StoredDocument(
                document_id=document_id,
                filename=document_data["filename"],
                page_count=max(chunk["page_number"] for chunk in document_data["chunks"]),
            ),
            [
                StoredChunk(
                    chunk_id=UUID(chunk["chunk_id"]),
                    document_id=document_id,
                    filename=document_data["filename"],
                    page_number=chunk["page_number"],
                    chunk_index=index,
                    text=chunk["text"],
                    embedding=embedding,
                )
                for index, (chunk, embedding) in enumerate(zip(document_data["chunks"], embeddings, strict=True))
            ],
        )

    service = RetrievalService(repository, provider, max_pdf_bytes=1)
    top_k = data["top_k"]
    results = []
    reciprocal_rank_total = 0.0
    hits = 0
    for case in data["queries"]:
        response = service.search(case["query"], top_k)
        ranking = [str(hit.source.chunk_id) for hit in response.hits]
        expected = case["expected_chunk_id"]
        rank = ranking.index(expected) + 1 if expected in ranking else None
        if rank is not None:
            hits += 1
            reciprocal_rank_total += 1 / rank
        results.append(
            {
                "query": case["query"],
                "expected_chunk_id": expected,
                "retrieved_chunk_ids": ranking,
                "expected_rank": rank,
                "passed": rank is not None,
            }
        )
    count = len(results)
    return {
        "top_k": top_k,
        "query_count": count,
        "hit_at_k": hits / count if count else 0.0,
        "mean_reciprocal_rank": reciprocal_rank_total / count if count else 0.0,
        "cases": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run controlled retrieval evaluation.")
    parser.add_argument("path", type=Path, help="Path to retrieval evaluation JSON.")
    args = parser.parse_args()
    result = evaluate_cases(args.path)
    print(json.dumps(result, indent=2))
    if not all(case["passed"] for case in result["cases"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
