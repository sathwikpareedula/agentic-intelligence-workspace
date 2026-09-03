"""Health endpoint."""

from typing import Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict

from app.config import Settings, get_settings

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
    limitations: list[str]


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Report that the API process is available."""

    return HealthResponse(status="ok")


def _diagnostics(settings: Settings) -> RuntimeDiagnostics:
    if settings.app_mode == "demo":
        return RuntimeDiagnostics(
            status="ready",
            mode="demo",
            storage="in_memory",
            embedding_provider="deterministic-token-hash",
            orchestrator_provider="deterministic-grades-demo",
            limitations=[
                "State is process-local and is lost on restart.",
                "Offline token-hash retrieval is for product demonstration, not production semantic quality.",
                "No hosted model is used; task decisions are a bounded deterministic demo sequence.",
            ],
        )

    limitations = []
    if not settings.database_url:
        limitations.append("DATABASE_URL is not configured.")
    if settings.embedding_provider != "openai":
        limitations.append(f"Embedding provider '{settings.embedding_provider}' is unsupported in production mode.")
    elif not settings.openai_api_key:
        limitations.append("OPENAI_API_KEY is not configured for embeddings.")
    if settings.orchestrator_provider != "openai":
        limitations.append("ORCHESTRATOR_PROVIDER must be 'openai' for production task execution.")
    elif not settings.openai_api_key:
        limitations.append("OPENAI_API_KEY is not configured for orchestration.")
    return RuntimeDiagnostics(
        status="not_ready" if limitations else "ready",
        mode="production",
        storage="postgresql",
        embedding_provider=settings.embedding_provider,
        orchestrator_provider=settings.orchestrator_provider,
        limitations=limitations,
    )


@router.get("/runtime", response_model=RuntimeDiagnostics)
def get_runtime(settings: Settings = Depends(get_settings)) -> RuntimeDiagnostics:
    """Describe configured execution paths without probing paid or stateful providers."""
    return _diagnostics(settings)


@router.get("/ready", response_model=RuntimeDiagnostics)
def get_readiness(response: Response, settings: Settings = Depends(get_settings)) -> RuntimeDiagnostics:
    """Report configuration readiness without silently falling back to demo providers."""
    diagnostics = _diagnostics(settings)
    if diagnostics.status != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return diagnostics
