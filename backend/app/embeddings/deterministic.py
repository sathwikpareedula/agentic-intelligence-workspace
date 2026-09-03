"""Deterministic offline embeddings for explicit demo and controlled evaluation use."""

from hashlib import sha256
from math import sqrt
import re


class DeterministicEmbeddingProvider:
    """Token-hash vectors that verify plumbing without claiming semantic-model quality."""

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
