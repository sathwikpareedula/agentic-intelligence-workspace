"""Deterministic dataset transformation, join, and export endpoints."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import ValidationError

from app.api.datasets import _read_upload
from app.config import Settings, get_settings
from app.dependencies import get_artifact_repository
from app.models.transformations import (
    DatasetResult,
    ExportRequest,
    JoinExportRequest,
    JoinResult,
    JoinWorkflowRequest,
    TransformRequest,
)
from app.repositories.documents import RepositoryError
from app.services.artifacts import ArtifactRepository, GeneratedArtifact, generate_artifact
from app.services.transformations import (
    TransformationError,
    apply_transformations,
    dataframe_result,
    join_datasets,
)

router = APIRouter(prefix="/datasets", tags=["datasets"])


def _parse_request(raw: str, model_type):
    try:
        return model_type.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.errors(include_context=False),
        ) from exc


def _operation_error(exc: TransformationError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


def _artifact_response(artifact: GeneratedArtifact) -> Response:
    return Response(
        content=artifact.content,
        media_type=artifact.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "X-Artifact-Filename": artifact.filename,
            "X-Artifact-Format": artifact.format,
            "X-Artifact-Row-Count": str(artifact.row_count),
            "X-Artifact-Column-Count": str(artifact.column_count),
            "X-Artifact-Id": str(artifact.artifact_id),
        },
    )


@router.post("/transform", response_model=DatasetResult)
async def transform_dataset(
    file: UploadFile = File(...),
    request: str = Form(...),
    sheet: str | None = Form(default=None),
) -> DatasetResult:
    spec = _parse_request(request, TransformRequest)
    dataset = await _read_upload(file, sheet)
    try:
        return dataframe_result(apply_transformations(dataset.frame, spec.operations))
    except TransformationError as exc:
        raise _operation_error(exc) from exc


@router.post("/join", response_model=JoinResult)
async def join_uploaded_datasets(
    left_file: UploadFile = File(...),
    right_file: UploadFile = File(...),
    request: str = Form(...),
    left_sheet: str | None = Form(default=None),
    right_sheet: str | None = Form(default=None),
) -> JoinResult:
    spec = _parse_request(request, JoinWorkflowRequest)
    try:
        left = await _read_upload(left_file, left_sheet)
    except HTTPException:
        await right_file.close()
        raise
    right = await _read_upload(right_file, right_sheet)
    try:
        left_frame = apply_transformations(left.frame, spec.left_operations)
        right_frame = apply_transformations(right.frame, spec.right_operations)
        joined = join_datasets(left_frame, right_frame, spec.join)
        result = apply_transformations(joined.frame, spec.operations)
        return JoinResult(result=dataframe_result(result), diagnostics=joined.diagnostics)
    except TransformationError as exc:
        raise _operation_error(exc) from exc


@router.post("/export")
async def export_dataset(
    http_request: Request,
    file: UploadFile = File(...),
    request: str = Form(...),
    sheet: str | None = Form(default=None),
    settings: Settings = Depends(get_settings),
) -> Response:
    spec = _parse_request(request, ExportRequest)
    dataset = await _read_upload(file, sheet)
    try:
        result = apply_transformations(dataset.frame, spec.operations)
    except TransformationError as exc:
        raise _operation_error(exc) from exc
    artifact = generate_artifact(result, dataset.filename, spec.format)
    _persist_artifact(artifact, http_request, settings)
    return _artifact_response(artifact)


@router.post("/join/export")
async def export_joined_datasets(
    http_request: Request,
    left_file: UploadFile = File(...),
    right_file: UploadFile = File(...),
    request: str = Form(...),
    left_sheet: str | None = Form(default=None),
    right_sheet: str | None = Form(default=None),
    settings: Settings = Depends(get_settings),
) -> Response:
    spec = _parse_request(request, JoinExportRequest)
    try:
        left = await _read_upload(left_file, left_sheet)
    except HTTPException:
        await right_file.close()
        raise
    right = await _read_upload(right_file, right_sheet)
    try:
        left_frame = apply_transformations(left.frame, spec.left_operations)
        right_frame = apply_transformations(right.frame, spec.right_operations)
        joined = join_datasets(left_frame, right_frame, spec.join)
        result = apply_transformations(joined.frame, spec.operations)
    except TransformationError as exc:
        raise _operation_error(exc) from exc
    artifact = generate_artifact(result, "joined_dataset", spec.format)
    _persist_artifact(artifact, http_request, settings)
    return _artifact_response(artifact)


def _persist_artifact(artifact: GeneratedArtifact, request: Request, settings: Settings) -> None:
    repository: ArtifactRepository | None = getattr(request.app.state, "artifact_repository", None)
    repository = repository or get_artifact_repository(settings)
    try:
        repository.save(artifact)
    except RepositoryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
