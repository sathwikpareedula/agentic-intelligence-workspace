"""Configuration and PostgreSQL repository contract tests."""

from uuid import UUID

import pytest

from app.config import ConfigurationError, Settings
from app.repositories.documents import PostgresDocumentRepository, RepositoryError, StoredChunk, StoredDocument


def test_retrieval_settings_are_environment_configurable(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@localhost/test")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "512")
    monkeypatch.setenv("RETRIEVAL_CHUNK_SIZE", "800")
    monkeypatch.setenv("RETRIEVAL_CHUNK_OVERLAP", "100")

    settings = Settings.from_env()

    assert settings.database_url == "postgresql://user:secret@localhost/test"
    assert settings.embedding_dimensions == 512
    assert settings.chunk_size == 800
    assert settings.chunk_overlap == 100


def test_retrieval_settings_reject_invalid_overlap(monkeypatch) -> None:
    monkeypatch.setenv("RETRIEVAL_CHUNK_SIZE", "100")
    monkeypatch.setenv("RETRIEVAL_CHUNK_OVERLAP", "100")

    with pytest.raises(ConfigurationError, match="must be smaller"):
        Settings.from_env()


def test_postgres_repository_validates_vector_dimension() -> None:
    with pytest.raises(RepositoryError, match="between 1 and 16000"):
        PostgresDocumentRepository("postgresql://unused", 16001)


def test_postgres_repository_schema_storage_and_cosine_search(monkeypatch) -> None:
    document_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    chunk_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    executed = []
    batches = []

    class FakeCursor:
        def __init__(self, rows=None):
            self._rows = rows or []

        def fetchall(self):
            return self._rows

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params))
            if "SELECT c.id" in sql:
                return FakeCursor([(chunk_id, document_id, "policy.pdf", 2, "Evidence text", 0.875)])
            return FakeCursor()

        def executemany(self, sql, params):
            batches.append((sql, list(params)))

    connection = FakeConnection()
    monkeypatch.setattr("app.repositories.documents.psycopg.connect", lambda _: connection)
    monkeypatch.setattr("app.repositories.documents.register_vector", lambda _: None)
    repository = PostgresDocumentRepository("postgresql://unused", 3)

    repository.initialize()
    repository.save_document(
        StoredDocument(document_id, "policy.pdf", 2),
        [StoredChunk(chunk_id, document_id, "policy.pdf", 2, 0, "Evidence text", [1.0, 0.0, 0.0])],
    )
    hits = repository.search([1.0, 0.0, 0.0], 1, document_id)

    sql = "\n".join(statement for statement, _ in executed)
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "embedding vector(3)" in sql
    assert "1 - (c.embedding <=> %s) AS score" in sql
    assert "WHERE c.document_id = %s" in sql
    assert len(batches[0][1]) == 1
    assert hits[0].chunk_id == chunk_id
    assert hits[0].filename == "policy.pdf"
    assert hits[0].page_number == 2
    assert hits[0].score == 0.875
