"""Opt-in live integration test for an explicitly isolated PostgreSQL/pgvector database."""

import os
import base64
from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest

from app.repositories.database import probe_database
from app.repositories.documents import PostgresDocumentRepository, RepositoryError, StoredChunk, StoredDocument
from app.agent.models import AgentExecution
from app.agent.tools import ToolRegistry, dataset_tools
from app.models.workflows import WorkflowCreate, WorkflowStep
from app.repositories.artifacts import LocalArtifactStore, PostgresArtifactRepository
from app.repositories.executions import PostgresExecutionRepository
from app.repositories.workflows import PostgresWorkflowRepository
from app.services.artifacts import GeneratedArtifact
from app.services.workflows import WorkflowService


@pytest.mark.skipif(
    os.getenv("ALLOW_DATABASE_INTEGRATION_TESTS") != "1" or not os.getenv("TEST_DATABASE_URL"),
    reason="Set ALLOW_DATABASE_INTEGRATION_TESTS=1 and TEST_DATABASE_URL for an isolated project test database.",
)
def test_live_pgvector_and_durable_repositories(tmp_path) -> None:
    database_url = os.environ["TEST_DATABASE_URL"]
    probe = probe_database(database_url)
    assert probe.database_available
    assert probe.pgvector_available
    assert probe.migration_current
    repository = PostgresDocumentRepository(database_url, 3, "integration", "fixed-v1")
    first_document = StoredDocument(uuid4(), "first.pdf", 1, "integration", "fixed-v1", 3)
    second_document = StoredDocument(uuid4(), "second.pdf", 1, "integration", "fixed-v1", 3)
    first_chunk = StoredChunk(uuid4(), first_document.document_id, "first.pdf", 1, 0, "alpha", [1.0, 0.0, 0.0])
    second_chunk = StoredChunk(uuid4(), second_document.document_id, "second.pdf", 1, 0, "beta", [0.0, 1.0, 0.0])
    workflow_repository = PostgresWorkflowRepository(database_url)
    workflow_service = WorkflowService(workflow_repository, ToolRegistry(dataset_tools()))
    workflow = workflow_service.create(
        WorkflowCreate(
            name="Persistent inspect",
            steps=[
                WorkflowStep(
                    tool="dataset.inspect",
                    arguments={
                        "filename": "data.csv",
                        "content_base64": base64.b64encode(b"id\n1\n").decode("ascii"),
                    },
                    expected_columns=["id"],
                )
            ],
        )
    )
    artifact_repository = PostgresArtifactRepository(database_url, LocalArtifactStore(tmp_path))
    artifact = GeneratedArtifact(
        "result.csv", "csv", "text/csv", 1, 1, b"id\n1\n", uuid4(), datetime.now(timezone.utc)
    )
    execution = AgentExecution(
        goal="Integration persistence check",
        status="completed",
        trace=[],
        completed_at=datetime.now(timezone.utc),
    )
    try:
        repository.save_document(first_document, [first_chunk])
        repository.save_document(second_document, [second_chunk])

        # A batch constraint error must roll back both metadata and chunk replacement.
        replacement = StoredDocument(first_document.document_id, "replacement.pdf", 1, "integration", "fixed-v1", 3)
        with pytest.raises(RepositoryError, match="Could not store document chunks"):
            repository.save_document(replacement, [first_chunk, first_chunk])
        retained = repository.search([1.0, 0.0, 0.0], 2, first_document.document_id)
        assert len(retained) == 1
        assert retained[0].filename == "first.pdf"
        assert retained[0].text == "alpha"

        all_hits = repository.search([1.0, 0.0, 0.0], 2)
        filtered_hits = repository.search([1.0, 0.0, 0.0], 2, second_document.document_id)

        assert [hit.chunk_id for hit in all_hits] == [first_chunk.chunk_id, second_chunk.chunk_id]
        assert [hit.chunk_id for hit in filtered_hits] == [second_chunk.chunk_id]
        assert filtered_hits[0].filename == "second.pdf"
        assert filtered_hits[0].page_number == 1
        restarted_service = WorkflowService(
            PostgresWorkflowRepository(database_url), ToolRegistry(dataset_tools())
        )
        assert restarted_service.get(workflow.workflow_id) == workflow
        workflow_run = restarted_service.rerun(workflow.workflow_id, {})
        assert workflow_run.status == "completed"
        artifact_repository.save(artifact)
        assert PostgresArtifactRepository(
            database_url, LocalArtifactStore(tmp_path)
        ).get(artifact.artifact_id) == artifact
        PostgresExecutionRepository(database_url).save(execution)
        with psycopg.connect(database_url) as connection:
            assert connection.execute(
                "SELECT count(*) FROM workflow_runs WHERE id = %s", (workflow_run.run_id,)
            ).fetchone()[0] == 1
            assert connection.execute(
                "SELECT count(*) FROM execution_runs WHERE id = %s", (execution.task_id,)
            ).fetchone()[0] == 1
    finally:
        with psycopg.connect(database_url) as connection:
            connection.execute("DELETE FROM execution_runs WHERE id = %s", (execution.task_id,))
            connection.execute("DELETE FROM artifacts WHERE id = %s", (artifact.artifact_id,))
            connection.execute("DELETE FROM workflow_runs WHERE workflow_id = %s", (workflow.workflow_id,))
            connection.execute("DELETE FROM workflows WHERE id = %s", (workflow.workflow_id,))
            connection.execute(
                "DELETE FROM documents WHERE id = ANY(%s)",
                ([first_document.document_id, second_document.document_id],),
            )


@pytest.mark.skipif(
    os.getenv("ALLOW_DATABASE_INTEGRATION_TESTS") != "1" or not os.getenv("TEST_DATABASE_URL"),
    reason="Set ALLOW_DATABASE_INTEGRATION_TESTS=1 and TEST_DATABASE_URL for an isolated project test database.",
)
def test_external_postgres_connector_is_read_only_and_importable() -> None:
    from urllib.parse import urlparse

    from app.models.sources import PostgresTableRef
    from app.models.analytics import AnalyticsSqlRequest
    from app.services.analytics import execute_sql_analytics
    from app.services.postgres_source import PostgresSourceError, import_source, list_catalog, test_connection, validate_select
    from app.models.sources import PostgresImportRequest, PostgresSourceConfig

    database_url = os.environ["TEST_DATABASE_URL"]
    parsed = urlparse(database_url)
    password = parsed.password or ""
    os.environ["EXTERNAL_PG_PASSWORD"] = password
    with psycopg.connect(database_url) as connection:
        connection.execute("CREATE SCHEMA IF NOT EXISTS external_demo")
        connection.execute("DROP TABLE IF EXISTS external_demo.orders")
        connection.execute("DROP SEQUENCE IF EXISTS external_demo.review_sequence")
        connection.execute(
            "CREATE TABLE external_demo.orders (order_id text PRIMARY KEY, customer_name text, amount numeric)"
        )
        connection.execute("INSERT INTO external_demo.orders VALUES ('O-1', 'Ada', 10)")
        connection.execute("CREATE SEQUENCE external_demo.review_sequence")
        connection.commit()
    config = PostgresSourceConfig(
        host=parsed.hostname or "127.0.0.1",
        port=parsed.port or 5432,
        database=parsed.path.lstrip("/"),
        user=parsed.username or "postgres",
        password_secret_ref="EXTERNAL_PG_PASSWORD",
        sslmode="disable",
    )
    try:
        assert test_connection(config)["read_only_session"] is True
        catalog = list_catalog(config)
        names = {(item.schema_name, item.name) for item in catalog.tables}
        assert ("external_demo", "orders") in names
        imported = import_source(
            PostgresImportRequest(source=config, table=PostgresTableRef(schema="external_demo", table="orders"))
        )
        assert imported.inspection.row_count == 1
        assert imported.provenance.source_type == "postgres"
        assert password not in imported.model_dump_json()
        sql_result = execute_sql_analytics(
            AnalyticsSqlRequest(source=config, select_sql="SELECT count(*) AS total FROM external_demo.orders")
        )
        assert sql_result.verification_facts["sql.total"] == 1
        with pytest.raises(PostgresSourceError, match="read-only"):
            import_source(
                PostgresImportRequest(
                    source=config,
                    select_sql="SELECT nextval('external_demo.review_sequence') AS value",
                )
            )
        with pytest.raises(Exception):
            validate_select("INSERT INTO external_demo.orders VALUES ('x')")
        with pytest.raises(Exception):
            import_source(PostgresImportRequest(source=config, select_sql="INSERT INTO external_demo.orders VALUES ('x')"))
    finally:
        os.environ.pop("EXTERNAL_PG_PASSWORD", None)
        with psycopg.connect(database_url) as connection:
            connection.execute("DROP TABLE IF EXISTS external_demo.orders")
            connection.execute("DROP SEQUENCE IF EXISTS external_demo.review_sequence")
            connection.commit()
