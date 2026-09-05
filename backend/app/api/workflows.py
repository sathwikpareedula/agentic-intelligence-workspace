"""Workflow save, retrieve, and rerun API."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import Settings, get_settings
from app.dependencies import get_workflow_service
from app.models.workflows import Workflow, WorkflowCreate, WorkflowRerunRequest, WorkflowRun
from app.repositories.documents import RepositoryError
from app.services.workflows import WorkflowError, WorkflowNotFoundError, WorkflowService

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _service(request: Request, settings: Settings) -> WorkflowService:
    service = getattr(request.app.state, "workflow_service", None)
    return service or get_workflow_service(settings)


@router.post("", response_model=Workflow, status_code=201)
def save_workflow(payload: WorkflowCreate, request: Request, settings: Settings = Depends(get_settings)) -> Workflow:
    try:
        return _service(request, settings).create(payload)
    except WorkflowError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RepositoryError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/{workflow_id}", response_model=Workflow)
def get_workflow(workflow_id: UUID, request: Request, settings: Settings = Depends(get_settings)) -> Workflow:
    try:
        return _service(request, settings).get(workflow_id)
    except WorkflowNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RepositoryError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/{workflow_id}/runs", response_model=WorkflowRun)
def rerun_workflow(workflow_id: UUID, payload: WorkflowRerunRequest, request: Request, settings: Settings = Depends(get_settings)) -> WorkflowRun:
    try:
        return _service(request, settings).rerun(workflow_id, payload.step_overrides)
    except WorkflowNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except WorkflowError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RepositoryError as exc:
        raise HTTPException(503, str(exc)) from exc
