"""FastAPI application entry point."""

import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.agent import router as agent_router
from app.api.datasets import router as datasets_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.retrieval import router as retrieval_router
from app.api.transformations import router as transformations_router
from app.api.workflows import router as workflows_router

app = FastAPI(title="Agentic Intelligence Workspace")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id", "").strip()[:128] or str(uuid4())
    began = perf_counter()
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    logging.getLogger("app.requests").info(
        "request_complete request_id=%s method=%s path=%s status=%s duration_ms=%.2f",
        request_id, request.method, request.url.path, response.status_code, (perf_counter() - began) * 1000,
    )
    return response
app.include_router(health_router)
app.include_router(agent_router)
app.include_router(datasets_router)
app.include_router(transformations_router)
app.include_router(documents_router)
app.include_router(retrieval_router)
app.include_router(workflows_router)
