"""Runtime dependency construction for retrieval services."""

from functools import lru_cache

from fastapi import Depends, HTTPException, status

from app.config import ConfigurationError, Settings, get_settings
from app.embeddings.openai_provider import OpenAIEmbeddingProvider
from app.repositories.documents import PostgresDocumentRepository, RepositoryError
from app.services.retrieval import RetrievalService


@lru_cache
def _postgres_repository(database_url: str, dimension: int) -> PostgresDocumentRepository:
    repository = PostgresDocumentRepository(database_url, dimension)
    repository.initialize()
    return repository


@lru_cache
def _openai_provider(api_key: str, model: str, dimension: int, batch_size: int) -> OpenAIEmbeddingProvider:
    return OpenAIEmbeddingProvider(api_key, model, dimension, batch_size)


def get_document_repository(settings: Settings = Depends(get_settings)):
    if not settings.database_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DATABASE_URL is required for document storage.",
        )
    try:
        return _postgres_repository(settings.database_url, settings.embedding_dimensions)
    except RepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


def get_embedding_provider(settings: Settings = Depends(get_settings)):
    if settings.embedding_provider != "openai":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Unsupported embedding provider '{settings.embedding_provider}'.",
        )
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is required for the OpenAI embedding provider.",
        )
    return _openai_provider(
        settings.openai_api_key,
        settings.embedding_model,
        settings.embedding_dimensions,
        settings.embedding_batch_size,
    )


def get_retrieval_service(
    repository=Depends(get_document_repository),
    embedding_provider=Depends(get_embedding_provider),
    settings: Settings = Depends(get_settings),
) -> RetrievalService:
    try:
        return RetrievalService(repository, embedding_provider, settings.pdf_max_upload_bytes)
    except ConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
