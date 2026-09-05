"""Embedding provider contract and validation."""

from math import isfinite
from typing import Protocol


class EmbeddingError(Exception):
    """Raised when embeddings cannot be produced or validated."""


class EmbeddingProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def validate_embeddings(vectors: list[list[float]], expected_count: int, dimension: int) -> None:
    if len(vectors) != expected_count:
        raise EmbeddingError(f"Embedding provider returned {len(vectors)} vectors; expected {expected_count}.")
    for index, vector in enumerate(vectors):
        if len(vector) != dimension:
            raise EmbeddingError(f"Embedding {index} has dimension {len(vector)}; expected {dimension}.")
        if not all(isfinite(value) for value in vector):
            raise EmbeddingError(f"Embedding {index} contains a non-finite value.")
