"""API boundary for bounded agent task execution."""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.agent.models import AgentExecution, AgentTaskRequest
from app.agent.orchestrator import AgentOrchestrator
from app.agent.providers import DeterministicGradesDemoProvider, OpenAIModelProvider
from app.agent.tools import ToolRegistry, grade_task_tools
from app.agent.verification import EvidenceVerifier
from app.config import Settings, get_settings
from app.dependencies import build_retrieval_service

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/tasks", response_model=AgentExecution)
def execute_agent_task(
    payload: AgentTaskRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> AgentExecution:
    orchestrator: AgentOrchestrator | None = getattr(request.app.state, "agent_orchestrator", None)
    if orchestrator is not None:
        return orchestrator.execute(payload.goal, payload.max_iterations)

    if settings.app_mode == "production" and settings.orchestrator_provider != "openai":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ORCHESTRATOR_PROVIDER=openai is required for production task execution.",
        )
    if payload.resources is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The grades task requires an uploaded dataset and an ingested document ID.",
        )

    retrieval_service = build_retrieval_service(settings)
    registry = ToolRegistry(
        grade_task_tools(
            retrieval_service,
            payload.resources.dataset,
            payload.resources.document_id,
        )
    )
    if settings.app_mode == "demo":
        provider = DeterministicGradesDemoProvider()
    else:
        if not settings.openai_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OPENAI_API_KEY is required for production task execution.",
            )
        provider = OpenAIModelProvider(
            settings.openai_api_key,
            settings.orchestrator_model,
            registry.specifications,
            settings.orchestrator_timeout_seconds,
            settings.orchestrator_max_retries,
        )
    orchestrator = AgentOrchestrator(provider, registry, EvidenceVerifier())
    return orchestrator.execute(payload.goal, payload.max_iterations)
