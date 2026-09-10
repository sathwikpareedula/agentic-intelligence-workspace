"""Health endpoint."""

from pathlib import Path
import os
from typing import Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict

from app.config import Settings, get_settings
from app.repositories.database import probe_database

router = APIRouter()


class HealthResponse(BaseModel):
    """Response returned when the API process is healthy."""

    status: Literal["ok"]


class RuntimeDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "not_ready"]
    mode: Literal["production", "demo"]
    storage: Literal["postgresql", "in_memory"]
    embedding_provider: str
    orchestrator_provider: str
    orchestrator_status: Literal["demo", "configured", "unavailable"]
    orchestrator_model: str
    database: Literal["not_required", "not_configured", "configured", "available", "unavailable"]
    pgvector: Literal["not_required", "unknown", "available", "unavailable"]
    migrations: Literal["not_required", "unknown", "current", "not_current"]
    artifact_storage: Literal["in_memory", "available", "unavailable"]
    limitations: list[str]


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Report that the API process is available."""

    return HealthResponse(status="ok")


def _diagnostics(settings: Settings, *, probe: bool = False) -> RuntimeDiagnostics:
    if settings.app_mode == "demo":
        return RuntimeDiagnostics(
            status="ready",
            mode="demo",
            storage="in_memory",
            embedding_provider="deterministic-token-hash",
            orchestrator_provider="deterministic-grades-demo",
            orchestrator_status="demo",
            orchestrator_model="deterministic-script",
            database="not_required",
            pgvector="not_required",
            migrations="not_required",
            artifact_storage="in_memory",
            limitations=[
                "State is process-local and is lost on restart.",
                "Offline token-hash retrieval is for product demonstration, not production semantic quality.",
                "No hosted model is used; task decisions are a bounded deterministic demo sequence.",
            ],
        )

    limitations: list[str] = []
    database_status = "configured" if settings.database_url else "not_configured"
    vector_status = "unknown"
    migration_status = "unknown"
    if not settings.database_url:
        limitations.append("DATABASE_URL is not configured.")
    elif probe:
        database_probe = probe_database(
            settings.database_url, settings.database_connect_timeout_seconds
        )
        database_status = "available" if database_probe.database_available else "unavailable"
        vector_status = "available" if database_probe.pgvector_available else "unavailable"
        migration_status = "current" if database_probe.migration_current else "not_current"
        if not database_probe.database_available:
            limitations.append(database_probe.error or "PostgreSQL is unavailable.")
        elif not database_probe.pgvector_available:
            limitations.append("The pgvector extension is unavailable.")
        if database_probe.database_available and not database_probe.migration_current:
            limitations.append("The database schema is not at the required migration revision.")
    if settings.embedding_provider != "openai":
        limitations.append(f"Embedding provider '{settings.embedding_provider}' is unsupported in production mode.")
    elif not settings.openai_api_key:
        limitations.append("OPENAI_API_KEY is not configured for embeddings.")
    if settings.orchestrator_provider == "none":
        limitations.append("ORCHESTRATOR_PROVIDER must select 'openai' or 'ollama' for production task execution.")
    elif settings.orchestrator_provider == "openai" and not settings.orchestrator_api_key:
        limitations.append("ORCHESTRATOR_API_KEY or OPENAI_API_KEY is not configured for orchestration.")
    orchestrator_status = (
        "configured"
        if settings.orchestrator_provider == "ollama"
        or (settings.orchestrator_provider == "openai" and settings.orchestrator_api_key)
        else "unavailable"
    )
    storage_status = _artifact_storage_status(settings.artifact_storage_path) if probe else "available"
    if storage_status == "unavailable":
        limitations.append("Local artifact storage is unavailable or not writable.")
    return RuntimeDiagnostics(
        status="not_ready" if limitations else "ready",
        mode="production",
        storage="postgresql",
        embedding_provider=settings.embedding_provider,
        orchestrator_provider=settings.orchestrator_provider,
        orchestrator_status=orchestrator_status,
        orchestrator_model=settings.orchestrator_model,
        database=database_status,
        pgvector=vector_status,
        migrations=migration_status,
        artifact_storage=storage_status,
        limitations=limitations,
    )


def _artifact_storage_status(path: str) -> Literal["available", "unavailable"]:
    try:
        root = Path(path).expanduser().resolve()
        if root.exists():
            return "available" if root.is_dir() and os.access(root, os.W_OK) else "unavailable"
        parent = root.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        return "available" if parent.is_dir() and os.access(parent, os.W_OK) else "unavailable"
    except OSError:
        return "unavailable"


@router.get("/runtime", response_model=RuntimeDiagnostics)
def get_runtime(settings: Settings = Depends(get_settings)) -> RuntimeDiagnostics:
    """Describe configured execution paths without probing paid or stateful providers."""
    return _diagnostics(settings)


@router.get("/ready", response_model=RuntimeDiagnostics)
def get_readiness(response: Response, settings: Settings = Depends(get_settings)) -> RuntimeDiagnostics:
    """Report configuration readiness without silently falling back to demo providers."""
    diagnostics = _diagnostics(settings, probe=True)
    if diagnostics.status != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return diagnostics
