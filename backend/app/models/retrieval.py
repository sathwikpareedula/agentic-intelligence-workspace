"""Typed document ingestion, retrieval, and citation contracts."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceReference(StrictModel):
    document_id: UUID
    filename: str
    page_number: int = Field(ge=1)
    chunk_id: UUID


class DocumentChunkMetadata(StrictModel):
    chunk_id: UUID
    page_number: int = Field(ge=1)
    chunk_index: int = Field(ge=0)
    character_count: int = Field(ge=1)


class DocumentIngestionResult(StrictModel):
    document_id: UUID
    filename: str
    page_count: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    chunks: list[DocumentChunkMetadata]


class RetrievalRequest(StrictModel):
    query: str = Field(min_length=1, max_length=8000)
    document_id: UUID | None = None
    top_k: int = Field(default=5, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def query_must_contain_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Query must contain non-whitespace text.")
        return cleaned


class RetrievalHit(StrictModel):
    rank: int = Field(ge=1)
    text: str
    score: float = Field(ge=-1.0, le=1.0)
    source: SourceReference


class RetrievalResponse(StrictModel):
    query: str
    hits: list[RetrievalHit]
