"""API boundary for bounded agent task execution."""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.agent.models import AgentExecution, AgentTaskRequest
from app.agent.orchestrator import AgentOrchestrator
from app.agent.providers import DeterministicGradesDemoProvider, DeterministicSalesDemoProvider
from app.agent.tools import ToolRegistry, general_task_tools, grade_task_tools
from app.agent.verification import EvidenceVerifier
from app.config import Settings, get_settings
from app.dependencies import (
    build_retrieval_service,
    build_orchestrator_provider,
    get_artifact_repository,
    get_execution_repository,
    get_workflow_service,
)
from app.repositories.documents import RepositoryError
from app.services.executions import persist_execution

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

    if settings.app_mode == "production" and settings.orchestrator_provider == "none":
        raise HTTPException(status_code=503, detail="ORCHESTRATOR_PROVIDER is not configured for production task execution.")
    if payload.resources is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The grades task requires an uploaded dataset and an ingested document ID.",
        )

    if settings.app_mode == "demo":
        if payload.resources.is_legacy_grades_demo:
            assert payload.resources.dataset is not None
            assert payload.resources.document_id is not None
            retrieval_service = build_retrieval_service(settings)
            registry = ToolRegistry(
                grade_task_tools(
                    retrieval_service,
                    payload.resources.dataset,
                    payload.resources.document_id,
                )
            )
            provider = DeterministicGradesDemoProvider()
        elif payload.resources.is_north_star_sales_demo:
            retrieval_service = build_retrieval_service(settings)
            artifact_repository = get_artifact_repository(settings)
            registry = ToolRegistry(
                general_task_tools(
                    retrieval_service,
                    payload.resources,
                    artifact_repository,
                    get_workflow_service(settings),
                )
            )
            provider = DeterministicSalesDemoProvider()
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="APP_MODE=demo supports the explicit deterministic grades workflow or the three-dataset plus one-policy north-star sales workflow.",
            )
    else:
        retrieval_service = (
            build_retrieval_service(settings)
            if payload.resources.all_document_ids()
            else None
        )
        artifact_repository = get_artifact_repository(settings)
        tools = general_task_tools(
            retrieval_service,
            payload.resources,
            artifact_repository,
            get_workflow_service(settings),
            settings.allow_private_rest_targets,
        )
        if payload.resources.is_legacy_grades_demo:
            assert payload.resources.dataset is not None
            assert payload.resources.document_id is not None
            tools.extend(
                tool
                for tool in grade_task_tools(
                    retrieval_service,
                    payload.resources.dataset,
                    payload.resources.document_id,
                )
                if tool.name == "grades.required_final"
            )
        registry = ToolRegistry(tools)
        provider = build_orchestrator_provider(settings, registry.specifications)
    orchestrator = AgentOrchestrator(
        provider,
        registry,
        EvidenceVerifier(),
        input_cost_per_million=settings.orchestrator_input_cost_per_million,
        output_cost_per_million=settings.orchestrator_output_cost_per_million,
    )
    execution = orchestrator.execute(payload.goal, payload.max_iterations)
    try:
        persist_execution(
            execution,
            get_execution_repository(settings),
            get_artifact_repository(settings),
        )
    except RepositoryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return execution
