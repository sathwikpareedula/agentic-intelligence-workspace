"""Document ingestion and evidence retrieval orchestration."""

from app.embeddings.base import EmbeddingProvider, validate_embeddings
from app.models.retrieval import (
    DocumentChunkMetadata,
    DocumentIngestionResult,
    RetrievalHit,
    RetrievalResponse,
    SourceReference,
)
from app.repositories.documents import DocumentRepository, StoredChunk, StoredDocument
from app.services.pdf_documents import chunk_document, extract_pdf


class RetrievalService:
    def __init__(self, repository: DocumentRepository, embedding_provider: EmbeddingProvider, max_pdf_bytes: int) -> None:
        self._repository = repository
        self._embedding_provider = embedding_provider
        self._max_pdf_bytes = max_pdf_bytes

    def ingest_pdf(self, filename: str, content: bytes, chunk_size: int, overlap: int) -> DocumentIngestionResult:
        document = extract_pdf(filename, content, self._max_pdf_bytes)
        chunks = chunk_document(document, chunk_size, overlap)
        embeddings = self._embedding_provider.embed_documents([chunk.text for chunk in chunks])
        validate_embeddings(embeddings, len(chunks), self._embedding_provider.dimension)
        self._repository.save_document(
            StoredDocument(document_id=document.document_id, filename=document.filename, page_count=document.page_count),
            [
                StoredChunk(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    filename=chunk.filename,
                    page_number=chunk.page_number,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    embedding=embedding,
                )
                for chunk, embedding in zip(chunks, embeddings, strict=True)
            ],
        )
        return DocumentIngestionResult(
            document_id=document.document_id,
            filename=document.filename,
            page_count=document.page_count,
            chunk_count=len(chunks),
            chunks=[
                DocumentChunkMetadata(
                    chunk_id=chunk.chunk_id,
                    page_number=chunk.page_number,
                    chunk_index=chunk.chunk_index,
                    character_count=len(chunk.text),
                )
                for chunk in chunks
            ],
        )

    def search(self, query: str, top_k: int, document_id=None) -> RetrievalResponse:
        cleaned_query = query.strip()
        query_embedding = self._embedding_provider.embed_query(cleaned_query)
        validate_embeddings([query_embedding], 1, self._embedding_provider.dimension)
        hits = self._repository.search(query_embedding, top_k, document_id)
        return RetrievalResponse(
            query=cleaned_query,
            hits=[
                RetrievalHit(
                    rank=rank,
                    text=hit.text,
                    score=max(-1.0, min(1.0, hit.score)),
                    source=SourceReference(
                        document_id=hit.document_id,
                        filename=hit.filename,
                        page_number=hit.page_number,
                        chunk_id=hit.chunk_id,
                    ),
                )
                for rank, hit in enumerate(hits, start=1)
            ],
        )
