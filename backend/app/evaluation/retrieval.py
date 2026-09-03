"""Executable deterministic retrieval evaluation."""

import argparse
from hashlib import sha256
import json
from math import sqrt
from pathlib import Path
import re
from uuid import UUID

from app.repositories.documents import InMemoryDocumentRepository, StoredChunk, StoredDocument
from app.services.retrieval import RetrievalService


class EvaluationEmbeddingProvider:
    """Offline token-hash embeddings for repeatable retrieval plumbing evaluation."""

    dimension = 2048
    stop_words = {"a", "an", "are", "be", "do", "for", "how", "is", "should", "the", "to", "when", "where"}

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            if token in self.stop_words:
                continue
            bucket = int.from_bytes(sha256(token.encode("utf-8")).digest()[:4], "big") % self.dimension
            vector[bucket] += 1.0
        norm = sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector


def evaluate_cases(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    provider = EvaluationEmbeddingProvider()
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
    print(json.dumps(evaluate_cases(args.path), indent=2))


if __name__ == "__main__":
    main()
