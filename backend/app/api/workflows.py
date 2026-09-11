"""Workflow save, retrieve, and rerun API."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.config import Settings, get_settings
from app.dependencies import get_workflow_service
from app.models.workflows import (
    RunComparison,
    RunComparisonRequest,
    Workflow,
    WorkflowCreate,
    WorkflowList,
    WorkflowRerunRequest,
    WorkflowRun,
    WorkflowRunRecord,
    WorkflowRunList,
    WorkflowSummary,
)
from app.repositories.documents import RepositoryError
from app.services.workflows import (
    WorkflowError,
    WorkflowNotFoundError,
    WorkflowRunNotFoundError,
    WorkflowService,
)

router = APIRouter(prefix="/workflows", tags=["workflows"])
run_router = APIRouter(prefix="/workflow-runs", tags=["workflow-runs"])


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


@router.get("", response_model=WorkflowList)
def list_workflows(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    settings: Settings = Depends(get_settings),
) -> WorkflowList:
    try:
        return WorkflowList(
            workflows=[
                WorkflowSummary.model_validate(
                    item.model_dump(
                        include={"workflow_id", "name", "version", "source_task_id", "created_at"}
                    )
                )
                for item in _service(request, settings).list(limit, offset)
            ],
            limit=limit,
            offset=offset,
        )
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


@router.get("/{workflow_id}/runs", response_model=WorkflowRunList)
def list_workflow_runs(
    workflow_id: UUID,
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    settings: Settings = Depends(get_settings),
) -> WorkflowRunList:
    try:
        runs = _service(request, settings).list_runs(workflow_id, limit, offset)
        return WorkflowRunList(
            workflow_id=workflow_id,
            runs=[WorkflowRunRecord.from_run(item) for item in runs],
            limit=limit,
            offset=offset,
        )
    except WorkflowNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RepositoryError as exc:
        raise HTTPException(503, str(exc)) from exc


@run_router.post("/compare", response_model=RunComparison)
def compare_workflow_runs(
    payload: RunComparisonRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> RunComparison:
    try:
        return _service(request, settings).compare_runs(
            payload.previous_run_id, payload.current_run_id
        )
    except WorkflowRunNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except WorkflowError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RepositoryError as exc:
        raise HTTPException(503, str(exc)) from exc


@run_router.get("/{run_id}", response_model=WorkflowRunRecord)
def get_workflow_run(
    run_id: UUID, request: Request, settings: Settings = Depends(get_settings)
) -> WorkflowRunRecord:
    try:
        return WorkflowRunRecord.from_run(_service(request, settings).get_run(run_id))
    except WorkflowRunNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RepositoryError as exc:
        raise HTTPException(503, str(exc)) from exc
