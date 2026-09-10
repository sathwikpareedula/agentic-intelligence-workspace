"""End-to-end HTTP boundary for the bounded August sales demonstration."""

import base64

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from app.agent.models import AgentDatasetResource, AgentExecution, AgentTaskResources
from app.agent.orchestrator import AgentOrchestrator
from app.agent.providers import DeterministicSalesDemoProvider
from app.agent.tools import ToolRegistry, general_task_tools
from app.agent.verification import EvidenceVerifier
from app.config import Settings, get_settings
from app.dependencies import build_orchestrator_provider, build_retrieval_service, get_artifact_repository, get_execution_repository, get_workflow_service
from app.embeddings.base import EmbeddingError
from app.repositories.documents import RepositoryError
from app.services.artifacts import ArtifactRepository
from app.services.executions import persist_execution
from app.services.datasets import MAX_UPLOAD_BYTES
from app.services.pdf_documents import (
    NoExtractableTextError,
    PdfDocumentError,
    PdfTooLargeError,
    UnsupportedPdfTypeError,
)

router = APIRouter(prefix="/sales", tags=["sales-demo"])


async def _read(file: UploadFile, limit: int) -> tuple[str, bytes]:
    content = await file.read(limit + 1)
    filename = file.filename or ""
    await file.close()
    return filename, content


@router.post("/reports/august", response_model=AgentExecution)
async def prepare_august_report(
    request: Request,
    transactions: UploadFile = File(...),
    customers: UploadFile = File(...),
    targets: UploadFile = File(...),
    policy: UploadFile = File(...),
    goal: str = Form(default="Prepare the August sales report.", min_length=1, max_length=10000),
    settings: Settings = Depends(get_settings),
) -> AgentExecution:
    if settings.app_mode == "production" and settings.orchestrator_provider == "none":
        raise HTTPException(status_code=503, detail="ORCHESTRATOR_PROVIDER is not configured for production task execution.")
    transaction_upload, customer_upload, target_upload, policy_upload = await _read(transactions, MAX_UPLOAD_BYTES), await _read(customers, MAX_UPLOAD_BYTES), await _read(targets, MAX_UPLOAD_BYTES), await _read(policy, settings.pdf_max_upload_bytes)
    retrieval_service = build_retrieval_service(settings)
    try:
        ingested = await run_in_threadpool(
            retrieval_service.ingest_pdf,
            policy_upload[0],
            policy_upload[1],
            settings.chunk_size,
            settings.chunk_overlap,
        )
    except PdfTooLargeError as exc:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)) from exc
    except UnsupportedPdfTypeError as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)) from exc
    except (PdfDocumentError, NoExtractableTextError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except EmbeddingError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except RepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    def resource(upload: tuple[str, bytes]) -> AgentDatasetResource:
        return AgentDatasetResource(
            filename=upload[0],
            content_base64=base64.b64encode(upload[1]).decode("ascii"),
        )

    repository: ArtifactRepository | None = getattr(request.app.state, "artifact_repository", None)
    repository = repository or get_artifact_repository(settings)
    resources = AgentTaskResources(
        datasets=[resource(transaction_upload), resource(customer_upload), resource(target_upload)],
        document_ids=[ingested.document_id],
    )
    registry = ToolRegistry(
        general_task_tools(
            retrieval_service,
            resources,
            repository,
            get_workflow_service(settings),
        )
    )
    if settings.app_mode == "demo":
        provider = DeterministicSalesDemoProvider()
    else:
        provider = build_orchestrator_provider(settings, registry.specifications)
    orchestrator = AgentOrchestrator(
        provider,
        registry,
        EvidenceVerifier(),
        input_cost_per_million=settings.orchestrator_input_cost_per_million,
        output_cost_per_million=settings.orchestrator_output_cost_per_million,
    )
    execution = await run_in_threadpool(orchestrator.execute, goal, 12)
    try:
        persist_execution(execution, get_execution_repository(settings), repository)
    except RepositoryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return execution
