"""Offline repository, migration, readiness, and runtime separation tests."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException

from app.agent.models import AgentExecution, ToolObservation
from app.api import health
from app.config import Settings
from app.dependencies import (
    get_artifact_repository,
    get_document_repository,
    get_execution_repository,
    get_workflow_service,
)
from app.models.workflows import Workflow, WorkflowRun, WorkflowStep
from app.repositories.artifacts import LocalArtifactStore, PostgresArtifactRepository
from app.repositories.database import DatabaseProbe, MIGRATION_HEAD
from app.repositories.documents import InMemoryDocumentRepository, RepositoryError
from app.repositories.executions import InMemoryExecutionRepository, PostgresExecutionRepository
from app.repositories.workflows import PostgresWorkflowRepository
from app.services.artifacts import GeneratedArtifact, InMemoryArtifactRepository


class FakeCursor:
    def __init__(self, *, row=None, rows=None) -> None:
        self._row = row
        self._rows = rows or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class FakeConnection:
    def __init__(self) -> None:
        self.executed = []
        self.row = None
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return FakeCursor(row=self.row, rows=self.rows)


def _settings(monkeypatch, mode: str, tmp_path: Path | None = None) -> Settings:
    monkeypatch.setenv("APP_MODE", mode)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    if tmp_path is not None:
        monkeypatch.setenv("ARTIFACT_STORAGE_PATH", str(tmp_path))
    return Settings.from_env()


def test_demo_runtime_uses_only_in_memory_persistence(monkeypatch, tmp_path) -> None:
    settings = _settings(monkeypatch, "demo", tmp_path)

    assert isinstance(get_document_repository(settings), InMemoryDocumentRepository)
    assert isinstance(get_artifact_repository(settings), InMemoryArtifactRepository)
    assert isinstance(get_execution_repository(settings), InMemoryExecutionRepository)
    assert get_workflow_service(settings)._repository.__class__.__name__ == "InMemoryWorkflowRepository"


def test_production_runtime_requires_database_configuration(monkeypatch, tmp_path) -> None:
    settings = _settings(monkeypatch, "production", tmp_path)

    for factory in (get_document_repository, get_artifact_repository, get_execution_repository, get_workflow_service):
        try:
            factory(settings)
        except HTTPException as exc:
            assert exc.status_code == 503
            assert "DATABASE_URL" in str(exc.detail)
        else:
            raise AssertionError("Production persistence must never fall back to process-local storage.")


def test_postgres_workflow_repository_round_trips_recipe_and_persists_run(monkeypatch) -> None:
    connection = FakeConnection()
    monkeypatch.setattr("app.repositories.workflows.psycopg.connect", lambda *args, **kwargs: connection)
    repository = PostgresWorkflowRepository("postgresql://unused")
    workflow = Workflow(name="Inspect", steps=[WorkflowStep(tool="dataset.inspect", arguments={})])

    connection.row = (workflow.model_dump(mode="json"),)
    repository.save(workflow)
    restored = repository.get(workflow.workflow_id)
    run = WorkflowRun(
        workflow_id=workflow.workflow_id,
        version=1,
        status="completed",
        observations=[ToolObservation(success=True, summary="done")],
    )
    repository.save_run(run, {1: {"sheet": "Data"}})
    run_row = (
        run.run_id,
        run.workflow_id,
        run.version,
        run.status,
        [item.model_dump(mode="json") for item in run.observations],
        run.failed_step,
        run.error,
        run.started_at,
        run.completed_at,
        run.definition_fingerprint,
        [],
        [],
        [],
        [],
        [],
        [],
        None,
        [],
        [],
    )
    connection.row = run_row
    restored_run = repository.get_run(run.run_id)
    connection.rows = [run_row]
    restored_history = repository.list_runs(workflow.workflow_id, 10, 0)

    sql = "\n".join(item[0] for item in connection.executed)
    assert "INSERT INTO workflows" in sql
    assert "INSERT INTO workflow_versions" in sql
    assert "INSERT INTO workflow_runs" in sql
    assert restored == workflow
    assert restored_run == run
    assert restored_history == [run]


def test_artifact_metadata_uses_filesystem_body_and_integrity_check(monkeypatch, tmp_path) -> None:
    connection = FakeConnection()
    monkeypatch.setattr("app.repositories.artifacts.psycopg.connect", lambda *args, **kwargs: connection)
    store = LocalArtifactStore(tmp_path)
    repository = PostgresArtifactRepository("postgresql://unused", store)
    created_at = datetime.now(timezone.utc)
    artifact = GeneratedArtifact(
        "report.csv", "csv", "text/csv", 1, 1, b"value\n1\n", uuid4(), created_at
    )

    repository.save(artifact)
    insert_params = connection.executed[-1][1]
    connection.row = (
        artifact.filename,
        artifact.format,
        artifact.media_type,
        artifact.row_count,
        artifact.column_count,
        insert_params[6],
        insert_params[7],
        insert_params[8],
        None,
        None,
        None,
        "not_verified",
        None,
        created_at,
    )

    restored = repository.get(artifact.artifact_id)

    assert restored == artifact
    assert list(tmp_path.glob("*.bin"))
    assert all(not isinstance(value, bytes) for value in insert_params)


def test_local_artifact_store_rejects_traversal_metadata(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path)
    try:
        store.load("../secret.bin")
    except RepositoryError as exc:
        assert "invalid key" in str(exc)
    else:
        raise AssertionError("Storage keys must not be able to escape the artifact root.")


def test_execution_repository_persists_only_structured_trace(monkeypatch) -> None:
    connection = FakeConnection()
    monkeypatch.setattr("app.repositories.executions.psycopg.connect", lambda *args, **kwargs: connection)
    repository = PostgresExecutionRepository("postgresql://unused")
    execution = AgentExecution(
        goal="Inspect data",
        status="completed",
        trace=[],
        completed_at=datetime.now(timezone.utc),
    )

    repository.save(execution)

    sql, params = connection.executed[0]
    assert "tool_trace" in sql
    assert "reasoning" not in sql.lower()
    assert "Inspect data" in params


def test_readiness_reports_database_and_pgvector_failures(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_MODE", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured-but-unavailable/test")
    monkeypatch.setenv("OPENAI_API_KEY", "configured")
    monkeypatch.setenv("ORCHESTRATOR_PROVIDER", "openai")
    monkeypatch.setenv("ARTIFACT_STORAGE_PATH", str(tmp_path))
    settings = Settings.from_env()
    monkeypatch.setattr(
        health,
        "probe_database",
        lambda *args: DatabaseProbe(False, False, False, "PostgreSQL test failure."),
    )

    diagnostics = health._diagnostics(settings, probe=True)

    assert diagnostics.status == "not_ready"
    assert diagnostics.database == "unavailable"
    assert diagnostics.pgvector == "unavailable"
    assert diagnostics.migrations == "not_current"
    assert "PostgreSQL test failure." in diagnostics.limitations


def test_initial_migration_owns_all_production_tables() -> None:
    migration = Path(__file__).parents[1] / "migrations" / "versions" / "20260903_0001_persistence_foundation.py"
    text = migration.read_text(encoding="utf-8")

    assert 'revision = "20260903_0001"' in text
    for table in (
        "documents", "document_chunks", "workflows", "workflow_versions",
        "workflow_runs", "artifacts", "execution_runs",
    ):
        assert f"CREATE TABLE {table}" in text
    assert "CREATE EXTENSION IF NOT EXISTS vector" in text

    run_history = Path(__file__).parents[1] / "migrations" / "versions" / "20260907_0002_workflow_run_history.py"
    run_history_text = run_history.read_text(encoding="utf-8")
    assert 'revision = "20260907_0002"' in run_history_text
    assert 'down_revision = "20260903_0001"' in run_history_text
    for column in (
        "definition_fingerprint", "lifecycle", "input_snapshots", "facts",
        "artifacts", "warnings", "drift_findings",
    ):
        assert f"ADD COLUMN {column}" in run_history_text

    observability = Path(__file__).parents[1] / "migrations" / "versions" / "20260908_0003_workflow_run_observability.py"
    observability_text = observability.read_text(encoding="utf-8")
    assert f'revision = "{MIGRATION_HEAD}"' in observability_text
    assert 'down_revision = "20260907_0002"' in observability_text
    assert "ADD COLUMN step_summaries" in observability_text
    assert "ADD COLUMN diagnostics" in observability_text
