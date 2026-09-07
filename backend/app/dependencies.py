"""Runtime dependency construction with explicit demo/production separation."""

from functools import lru_cache

from fastapi import Depends, HTTPException, status

from app.agent.tools import ToolRegistry, dataset_tools, sales_report_tool, source_tools, template_transform_tool
from app.config import ConfigurationError, Settings, get_settings
from app.embeddings.deterministic import DeterministicEmbeddingProvider
from app.embeddings.openai_provider import OpenAIEmbeddingProvider
from app.repositories.artifacts import LocalArtifactStore, PostgresArtifactRepository
from app.repositories.documents import InMemoryDocumentRepository, PostgresDocumentRepository, RepositoryError
from app.repositories.executions import InMemoryExecutionRepository, PostgresExecutionRepository
from app.repositories.workflows import PostgresWorkflowRepository
from app.services.artifacts import InMemoryArtifactRepository
from app.services.retrieval import RetrievalService
from app.services.workflows import InMemoryWorkflowRepository, WorkflowService


def _unavailable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)


def _require_database(settings: Settings) -> str:
    if not settings.database_url:
        raise _unavailable("DATABASE_URL is required for production persistence.")
    return settings.database_url


@lru_cache
def _postgres_repository(
    database_url: str,
    dimension: int,
    provider: str,
    model: str,
    timeout: int,
) -> PostgresDocumentRepository:
    return PostgresDocumentRepository(database_url, dimension, provider, model, timeout)


@lru_cache
def _openai_provider(api_key: str, model: str, dimension: int, batch_size: int) -> OpenAIEmbeddingProvider:
    return OpenAIEmbeddingProvider(api_key, model, dimension, batch_size)


@lru_cache
def _demo_repository() -> InMemoryDocumentRepository:
    return InMemoryDocumentRepository()


@lru_cache
def _deterministic_provider() -> DeterministicEmbeddingProvider:
    return DeterministicEmbeddingProvider()


@lru_cache
def _demo_artifact_repository() -> InMemoryArtifactRepository:
    return InMemoryArtifactRepository()


@lru_cache
def _postgres_artifact_repository(
    database_url: str,
    storage_path: str,
    timeout: int,
) -> PostgresArtifactRepository:
    try:
        store = LocalArtifactStore(storage_path)
    except (OSError, RepositoryError) as exc:
        raise RepositoryError("Could not initialize local artifact storage.") from exc
    return PostgresArtifactRepository(database_url, store, timeout)


@lru_cache
def _demo_workflow_repository() -> InMemoryWorkflowRepository:
    return InMemoryWorkflowRepository()


@lru_cache
def _postgres_workflow_repository(database_url: str, timeout: int) -> PostgresWorkflowRepository:
    return PostgresWorkflowRepository(database_url, timeout)


@lru_cache
def _demo_execution_repository() -> InMemoryExecutionRepository:
    return InMemoryExecutionRepository()


@lru_cache
def _postgres_execution_repository(database_url: str, timeout: int) -> PostgresExecutionRepository:
    return PostgresExecutionRepository(database_url, timeout)


def get_document_repository(settings: Settings = Depends(get_settings)):
    if settings.app_mode == "demo":
        return _demo_repository()
    if settings.embedding_provider != "openai":
        raise _unavailable(f"Unsupported embedding provider '{settings.embedding_provider}'.")
    return _postgres_repository(
        _require_database(settings),
        settings.embedding_dimensions,
        settings.embedding_provider,
        settings.embedding_model,
        settings.database_connect_timeout_seconds,
    )


def get_embedding_provider(settings: Settings = Depends(get_settings)):
    if settings.app_mode == "demo":
        return _deterministic_provider()
    if settings.embedding_provider != "openai":
        raise _unavailable(f"Unsupported embedding provider '{settings.embedding_provider}'.")
    if not settings.openai_api_key:
        raise _unavailable("OPENAI_API_KEY is required for the OpenAI embedding provider.")
    return _openai_provider(
        settings.openai_api_key,
        settings.embedding_model,
        settings.embedding_dimensions,
        settings.embedding_batch_size,
    )


def get_artifact_repository(settings: Settings = Depends(get_settings)):
    if settings.app_mode == "demo":
        return _demo_artifact_repository()
    try:
        return _postgres_artifact_repository(
            _require_database(settings),
            settings.artifact_storage_path,
            settings.database_connect_timeout_seconds,
        )
    except RepositoryError as exc:
        raise _unavailable(str(exc)) from exc


def get_workflow_service(settings: Settings = Depends(get_settings)) -> WorkflowService:
    if settings.app_mode == "demo":
        repository = _demo_workflow_repository()
    else:
        repository = _postgres_workflow_repository(
            _require_database(settings), settings.database_connect_timeout_seconds
        )
    artifacts = get_artifact_repository(settings)
    return WorkflowService(
        repository,
        ToolRegistry(
            [
                *dataset_tools(),
                *source_tools(settings.allow_private_rest_targets),
                sales_report_tool(artifacts),
                template_transform_tool(artifacts),
            ]
        ),
        artifacts,
    )


def get_execution_repository(settings: Settings = Depends(get_settings)):
    if settings.app_mode == "demo":
        return _demo_execution_repository()
    return _postgres_execution_repository(
        _require_database(settings), settings.database_connect_timeout_seconds
    )


def get_retrieval_service(
    repository=Depends(get_document_repository),
    embedding_provider=Depends(get_embedding_provider),
    settings: Settings = Depends(get_settings),
) -> RetrievalService:
    try:
        return RetrievalService(repository, embedding_provider, settings.pdf_max_upload_bytes)
    except ConfigurationError as exc:
        raise _unavailable(str(exc)) from exc


def build_retrieval_service(settings: Settings) -> RetrievalService:
    """Construct the configured retrieval service outside FastAPI dependency injection."""
    return RetrievalService(
        get_document_repository(settings),
        get_embedding_provider(settings),
        settings.pdf_max_upload_bytes,
    )
