"""API boundary for bounded agent task execution."""

from fastapi import APIRouter, HTTPException, Request, status

from app.agent.models import AgentExecution, AgentTaskRequest
from app.agent.orchestrator import AgentOrchestrator

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/tasks", response_model=AgentExecution)
def execute_agent_task(payload: AgentTaskRequest, request: Request) -> AgentExecution:
    orchestrator: AgentOrchestrator | None = getattr(request.app.state, "agent_orchestrator", None)
    if orchestrator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No orchestrator model provider is configured.",
        )
    return orchestrator.execute(payload.goal, payload.max_iterations)
