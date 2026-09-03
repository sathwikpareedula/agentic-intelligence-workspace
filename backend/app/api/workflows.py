"""Workflow save, retrieve, and rerun API."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from app.models.workflows import Workflow, WorkflowCreate, WorkflowRerunRequest, WorkflowRun
from app.services.workflows import WorkflowError, WorkflowService

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _service(request: Request) -> WorkflowService:
    service = getattr(request.app.state, "workflow_service", None)
    if service is None:
        raise HTTPException(503, "Workflow repository and tools are not configured.")
    return service


@router.post("", response_model=Workflow, status_code=201)
def save_workflow(payload: WorkflowCreate, request: Request) -> Workflow:
    try:
        return _service(request).create(payload)
    except WorkflowError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/{workflow_id}", response_model=Workflow)
def get_workflow(workflow_id: UUID, request: Request) -> Workflow:
    try:
        return _service(request).get(workflow_id)
    except WorkflowError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{workflow_id}/runs", response_model=WorkflowRun)
def rerun_workflow(workflow_id: UUID, payload: WorkflowRerunRequest, request: Request) -> WorkflowRun:
    try:
        return _service(request).rerun(workflow_id, payload.step_overrides)
    except WorkflowError as exc:
        raise HTTPException(404, str(exc)) from exc
