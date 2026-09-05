"""PostgreSQL persistence for versioned workflows and rerun provenance."""

from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from app.models.workflows import Workflow, WorkflowRun
from app.repositories.documents import RepositoryError


class PostgresWorkflowRepository:
    def __init__(self, database_url: str, connect_timeout_seconds: int = 3) -> None:
        self._database_url = database_url
        self._connect_timeout_seconds = connect_timeout_seconds

    def save(self, workflow: Workflow) -> None:
        payload = workflow.model_dump(mode="json")
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO workflows (id, name, source_task_id, current_version, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        source_task_id = EXCLUDED.source_task_id,
                        current_version = GREATEST(workflows.current_version, EXCLUDED.current_version),
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        workflow.workflow_id,
                        workflow.name,
                        workflow.source_task_id,
                        workflow.version,
                        workflow.created_at,
                        workflow.created_at,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO workflow_versions (workflow_id, version, recipe, created_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (workflow_id, version) DO NOTHING
                    """,
                    (workflow.workflow_id, workflow.version, Jsonb(payload), workflow.created_at),
                )
        except psycopg.Error as exc:
            raise RepositoryError("Could not persist the workflow.") from exc

    def get(self, workflow_id: UUID) -> Workflow | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT v.recipe
                    FROM workflows w
                    JOIN workflow_versions v
                      ON v.workflow_id = w.id AND v.version = w.current_version
                    WHERE w.id = %s
                    """,
                    (workflow_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise RepositoryError("Could not load the workflow.") from exc
        return Workflow.model_validate(row[0]) if row else None

    def save_run(self, run: WorkflowRun, overrides: dict[int, dict]) -> None:
        artifact_ids = {
            UUID(artifact_id)
            for observation in run.observations
            for artifact_id in observation.artifact_ids
        }
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO workflow_runs
                        (id, workflow_id, workflow_version, status, started_at, completed_at,
                         step_overrides, observations, failed_step, error, artifact_ids)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        run.run_id,
                        run.workflow_id,
                        run.version,
                        run.status,
                        run.started_at,
                        run.completed_at,
                        Jsonb({str(key): value for key, value in overrides.items()}),
                        Jsonb([item.model_dump(mode="json") for item in run.observations]),
                        run.failed_step,
                        run.error,
                        sorted(artifact_ids, key=str),
                    ),
                )
        except (psycopg.Error, ValueError) as exc:
            raise RepositoryError("Could not persist the workflow run.") from exc

    def _connect(self):
        return psycopg.connect(self._database_url, connect_timeout=self._connect_timeout_seconds)
