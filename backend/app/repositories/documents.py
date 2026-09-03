"""Document vector repository contracts and implementations."""

from dataclasses import dataclass
from math import sqrt
from typing import Protocol
from uuid import UUID

import psycopg
from pgvector.psycopg import register_vector


class RepositoryError(Exception):
    """Raised when document storage or search fails."""


@dataclass(frozen=True)
class StoredDocument:
    document_id: UUID
    filename: str
    page_count: int


@dataclass(frozen=True)
class StoredChunk:
    chunk_id: UUID
    document_id: UUID
    filename: str
    page_number: int
    chunk_index: int
    text: str
    embedding: list[float]


@dataclass(frozen=True)
class RepositorySearchHit:
    chunk_id: UUID
    document_id: UUID
    filename: str
    page_number: int
    text: str
    score: float


class DocumentRepository(Protocol):
    def save_document(self, document: StoredDocument, chunks: list[StoredChunk]) -> None: ...

    def search(self, embedding: list[float], top_k: int, document_id: UUID | None = None) -> list[RepositorySearchHit]: ...


class InMemoryDocumentRepository:
    """Exact cosine repository for tests and controlled evaluation."""

    def __init__(self) -> None:
        self.documents: dict[UUID, StoredDocument] = {}
        self.chunks: dict[UUID, StoredChunk] = {}

    def save_document(self, document: StoredDocument, chunks: list[StoredChunk]) -> None:
        self.documents[document.document_id] = document
        self.chunks = {key: value for key, value in self.chunks.items() if value.document_id != document.document_id}
        self.chunks.update({chunk.chunk_id: chunk for chunk in chunks})

    def search(self, embedding: list[float], top_k: int, document_id: UUID | None = None) -> list[RepositorySearchHit]:
        candidates = [chunk for chunk in self.chunks.values() if document_id is None or chunk.document_id == document_id]
        ranked = sorted(
            ((self._cosine_similarity(embedding, chunk.embedding), chunk) for chunk in candidates),
            key=lambda item: (-item[0], str(item[1].chunk_id)),
        )[:top_k]
        return [
            RepositorySearchHit(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                filename=chunk.filename,
                page_number=chunk.page_number,
                text=chunk.text,
                score=score,
            )
            for score, chunk in ranked
        ]

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        if len(left) != len(right):
            raise RepositoryError("Stored and query embedding dimensions do not match.")
        left_norm = sqrt(sum(value * value for value in left))
        right_norm = sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


class PostgresDocumentRepository:
    """PostgreSQL + pgvector repository using cosine similarity."""

    def __init__(self, database_url: str, embedding_dimension: int) -> None:
        if embedding_dimension <= 0 or embedding_dimension > 16000:
            raise RepositoryError("pgvector embeddings must have between 1 and 16000 dimensions.")
        self._database_url = database_url
        self._dimension = embedding_dimension

    def initialize(self) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
                register_vector(connection)
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS documents (
                        id uuid PRIMARY KEY,
                        filename text NOT NULL,
                        page_count integer NOT NULL CHECK (page_count > 0),
                        created_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )
                connection.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS document_chunks (
                        id uuid PRIMARY KEY,
                        document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                        page_number integer NOT NULL CHECK (page_number > 0),
                        chunk_index integer NOT NULL CHECK (chunk_index >= 0),
                        content text NOT NULL CHECK (content <> ''),
                        embedding vector({self._dimension}) NOT NULL,
                        UNIQUE (document_id, page_number, chunk_index)
                    )
                    """
                )
        except psycopg.Error as exc:
            raise RepositoryError("Could not initialize PostgreSQL document storage.") from exc

    def save_document(self, document: StoredDocument, chunks: list[StoredChunk]) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO documents (id, filename, page_count)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                    SET filename = EXCLUDED.filename, page_count = EXCLUDED.page_count
                    """,
                    (document.document_id, document.filename, document.page_count),
                )
                connection.execute("DELETE FROM document_chunks WHERE document_id = %s", (document.document_id,))
                connection.executemany(
                    """
                    INSERT INTO document_chunks
                        (id, document_id, page_number, chunk_index, content, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (chunk.chunk_id, chunk.document_id, chunk.page_number, chunk.chunk_index, chunk.text, chunk.embedding)
                        for chunk in chunks
                    ],
                )
        except psycopg.Error as exc:
            raise RepositoryError("Could not store document chunks.") from exc

    def search(self, embedding: list[float], top_k: int, document_id: UUID | None = None) -> list[RepositorySearchHit]:
        params: list[object] = [embedding]
        where = ""
        if document_id is not None:
            where = "WHERE c.document_id = %s"
            params.append(document_id)
        params.extend([embedding, top_k])
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT c.id, c.document_id, d.filename, c.page_number, c.content,
                           1 - (c.embedding <=> %s) AS score
                    FROM document_chunks c
                    JOIN documents d ON d.id = c.document_id
                    {where}
                    ORDER BY c.embedding <=> %s, c.id
                    LIMIT %s
                    """,
                    params,
                ).fetchall()
        except psycopg.Error as exc:
            raise RepositoryError("Could not search document chunks.") from exc
        return [
            RepositorySearchHit(
                chunk_id=row[0], document_id=row[1], filename=row[2], page_number=row[3], text=row[4], score=float(row[5])
            )
            for row in rows
        ]

    def _connect(self):
        connection = psycopg.connect(self._database_url)
        register_vector(connection)
        return connection
