"""FastAPI application entry point."""

import logging
import re
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.agent import router as agent_router
from app.api.artifacts import router as artifacts_router
from app.api.datasets import router as datasets_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.retrieval import router as retrieval_router
from app.api.sales import router as sales_router
from app.api.transformations import router as transformations_router
from app.api.workflows import router as workflows_router
from app.api.template_transforms import router as template_transforms_router
from app.api.sources import router as sources_router
from app.api.analytics import router as analytics_router
app = FastAPI(title="Agentic Intelligence Workspace")
app.state.artifact_repository = None
app.state.workflow_service = None
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = _request_id(request.headers.get("x-request-id"))
    request.state.request_id = request_id
    began = perf_counter()
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    logging.getLogger("app.requests").info(
        "request_complete request_id=%s method=%s path=%s status=%s duration_ms=%.2f",
        request_id, request.method, request.url.path, response.status_code, (perf_counter() - began) * 1000,
    )
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    return _error_response(request, exc.status_code, _error_code(exc.status_code), exc.detail, exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _error_response(request, 422, "validation_error", jsonable_encoder(exc.errors()))


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logging.getLogger("app.errors").exception(
        "unhandled_request_error request_id=%s method=%s path=%s",
        getattr(request.state, "request_id", "unknown"),
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return _error_response(request, 500, "internal_error", "Internal server error.")


def _request_id(candidate: str | None) -> str:
    cleaned = (candidate or "").strip()
    if cleaned and len(cleaned) <= 128 and re.fullmatch(r"[A-Za-z0-9._:-]+", cleaned):
        return cleaned
    return str(uuid4())


def _error_code(status_code: int) -> str:
    return {
        400: "bad_request",
        404: "not_found",
        413: "upload_too_large",
        415: "unsupported_media_type",
        422: "unprocessable_content",
        502: "provider_error",
        503: "service_unavailable",
    }.get(status_code, "http_error")


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    detail,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid4()))
    response_headers = dict(headers or {})
    response_headers["x-request-id"] = request_id
    return JSONResponse(
        status_code=status_code,
        headers=response_headers,
        content={"code": code, "detail": jsonable_encoder(detail), "request_id": request_id},
    )


app.include_router(health_router)
app.include_router(agent_router)
app.include_router(artifacts_router)
app.include_router(datasets_router)
app.include_router(transformations_router)
app.include_router(documents_router)
app.include_router(retrieval_router)
app.include_router(sales_router)
app.include_router(workflows_router)
app.include_router(template_transforms_router)
app.include_router(sources_router)
app.include_router(analytics_router)
