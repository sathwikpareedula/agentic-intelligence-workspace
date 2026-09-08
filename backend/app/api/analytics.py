"""Typed analytics plan validation and deterministic execution APIs."""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError

from app.api.datasets import _read_upload
from app.models.analytics import AnalyticsExecuteRequest, AnalyticsPlan, AnalyticsResult, AnalyticsSqlRequest
from app.services.analytics import AnalyticsError, execute_dataset_analytics, execute_sql_analytics, validate_plan
from app.services.datasets import DatasetReadError, DatasetTooLargeError, UnsupportedFileTypeError
from app.services.postgres_source import PostgresSourceError
from app.services.secrets import SecretError

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.post("/validate", response_model=AnalyticsPlan)
def analytics_validate(plan: AnalyticsPlan) -> AnalyticsPlan:
    try:
        return validate_plan(plan)
    except AnalyticsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.post("/execute", response_model=AnalyticsResult)
async def analytics_execute(
    file: UploadFile = File(...),
    request: str = Form(...),
    sheet: str | None = Form(default=None),
) -> AnalyticsResult:
    try:
        plan = AnalyticsPlan.model_validate_json(request)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.errors(include_context=False)) from exc
    dataset = await _read_upload(file, sheet)
    try:
        return execute_dataset_analytics(dataset, plan)
    except AnalyticsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.post("/execute-payload", response_model=AnalyticsResult)
def analytics_execute_payload(request: AnalyticsExecuteRequest) -> AnalyticsResult:
    import base64

    from app.services.datasets import load_dataset

    try:
        content = base64.b64decode(request.content_base64, validate=True)
        dataset = load_dataset(request.filename, content, request.sheet)
        return execute_dataset_analytics(dataset, request.plan)
    except DatasetTooLargeError as exc:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(exc)) from exc
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    except (AnalyticsError, DatasetReadError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.post("/sql", response_model=AnalyticsResult)
def analytics_sql(request: AnalyticsSqlRequest) -> AnalyticsResult:
    try:
        return execute_sql_analytics(request)
    except (AnalyticsError, PostgresSourceError, SecretError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
