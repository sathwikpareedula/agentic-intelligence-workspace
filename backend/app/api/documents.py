"""PDF ingestion API."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.dependencies import get_retrieval_service
from app.embeddings.base import EmbeddingError
from app.models.retrieval import DocumentIngestionResult
from app.repositories.documents import RepositoryError
from app.services.pdf_documents import (
    NoExtractableTextError,
    PdfDocumentError,
    PdfTooLargeError,
    UnsupportedPdfTypeError,
)
from app.services.retrieval import RetrievalService

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=DocumentIngestionResult, status_code=status.HTTP_201_CREATED)
async def ingest_document(
    file: UploadFile = File(...),
    chunk_size: int | None = Form(default=None, ge=100, le=8000),
    chunk_overlap: int | None = Form(default=None, ge=0, le=4000),
    service: RetrievalService = Depends(get_retrieval_service),
    settings: Settings = Depends(get_settings),
) -> DocumentIngestionResult:
    content = await file.read(settings.pdf_max_upload_bytes + 1)
    filename = file.filename or ""
    await file.close()
    try:
        return await run_in_threadpool(
            service.ingest_pdf,
            filename,
            content,
            chunk_size or settings.chunk_size,
            settings.chunk_overlap if chunk_overlap is None else chunk_overlap,
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
