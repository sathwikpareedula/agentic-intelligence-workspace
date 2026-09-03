"""End-to-end HTTP boundary for the bounded August sales demonstration."""

import base64

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from app.agent.models import AgentDatasetResource, AgentExecution
from app.agent.orchestrator import AgentOrchestrator
from app.agent.providers import DeterministicSalesDemoProvider, OpenAIModelProvider
from app.agent.tools import ToolRegistry, sales_task_tools
from app.agent.verification import EvidenceVerifier
from app.config import Settings, get_settings
from app.dependencies import build_retrieval_service
from app.embeddings.base import EmbeddingError
from app.repositories.documents import RepositoryError
from app.services.artifacts import InMemoryArtifactRepository
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
    goal: str = Form(default="Prepare the August sales report."),
    settings: Settings = Depends(get_settings),
) -> AgentExecution:
    if settings.app_mode == "production" and settings.orchestrator_provider != "openai":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ORCHESTRATOR_PROVIDER=openai is required for production task execution.",
        )
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

    repository: InMemoryArtifactRepository | None = getattr(request.app.state, "artifact_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="Artifact storage is not configured.")
    registry = ToolRegistry(
        sales_task_tools(
            retrieval_service,
            resource(transaction_upload),
            resource(customer_upload),
            resource(target_upload),
            ingested.document_id,
            repository,
        )
    )
    if settings.app_mode == "demo":
        provider = DeterministicSalesDemoProvider()
    else:
        if not settings.openai_api_key:
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY is required for production task execution.")
        provider = OpenAIModelProvider(
            settings.openai_api_key,
            settings.orchestrator_model,
            registry.specifications,
            settings.orchestrator_timeout_seconds,
            settings.orchestrator_max_retries,
        )
    orchestrator = AgentOrchestrator(provider, registry, EvidenceVerifier())
    return await run_in_threadpool(orchestrator.execute, goal, 8)
