"""Hosted OpenAI embedding provider."""

from openai import OpenAI, OpenAIError

from app.embeddings.base import EmbeddingError, validate_embeddings


class OpenAIEmbeddingProvider:
    def __init__(self, api_key: str, model: str, dimension: int, batch_size: int) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._dimension = dimension
        self._batch_size = batch_size

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if any(not text.strip() for text in texts):
            raise EmbeddingError("Cannot embed empty document text.")
        vectors = []
        try:
            for start in range(0, len(texts), self._batch_size):
                batch = texts[start : start + self._batch_size]
                response = self._client.embeddings.create(
                    input=batch,
                    model=self._model,
                    dimensions=self._dimension,
                    encoding_format="float",
                )
                vectors.extend(item.embedding for item in sorted(response.data, key=lambda item: item.index))
        except OpenAIError as exc:
            raise EmbeddingError("OpenAI embedding request failed.") from exc
        validate_embeddings(vectors, len(texts), self.dimension)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        if not text.strip():
            raise EmbeddingError("Cannot embed an empty query.")
        return self.embed_documents([text])[0]
