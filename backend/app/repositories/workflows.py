"""PostgreSQL persistence for versioned workflows and rerun provenance."""

from __future__ import annotations

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
                    ON CONFLICT (id) DO NOTHING
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
                    ON CONFLICT (workflow_id, version) DO UPDATE
                    SET recipe = workflow_versions.recipe
                    RETURNING recipe
                    """,
                    (workflow.workflow_id, workflow.version, Jsonb(payload), workflow.created_at),
                ).fetchone()
                stored = connection.execute(
                    "SELECT recipe FROM workflow_versions WHERE workflow_id = %s AND version = %s",
                    (workflow.workflow_id, workflow.version),
                ).fetchone()
                if stored is None or Workflow.model_validate(stored[0]) != workflow:
                    raise RepositoryError("An existing workflow version cannot be mutated.")
                connection.execute(
                    """
                    UPDATE workflows
                    SET current_version = GREATEST(current_version, %s), updated_at = %s
                    WHERE id = %s
                    """,
                    (workflow.version, workflow.created_at, workflow.workflow_id),
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

    def list(self, limit: int, offset: int) -> list[Workflow]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT v.recipe
                    FROM workflows w
                    JOIN workflow_versions v
                      ON v.workflow_id = w.id AND v.version = w.current_version
                    ORDER BY w.updated_at DESC, w.id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (limit, offset),
                ).fetchall()
        except psycopg.Error as exc:
            raise RepositoryError("Could not list workflows.") from exc
        return [Workflow.model_validate(row[0]) for row in rows]

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
                         step_overrides, observations, failed_step, error, artifact_ids,
                         definition_fingerprint, lifecycle, input_snapshots, facts, artifacts,
                         warnings, drift_findings, verification)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s)
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
                        run.definition_fingerprint,
                        Jsonb([item.model_dump(mode="json") for item in run.lifecycle]),
                        Jsonb([item.model_dump(mode="json") for item in run.input_snapshots]),
                        Jsonb([item.model_dump(mode="json") for item in run.facts]),
                        Jsonb([item.model_dump(mode="json") for item in run.artifacts]),
                        Jsonb(run.warnings),
                        Jsonb([item.model_dump(mode="json") for item in run.drift_findings]),
                        Jsonb(run.verification.model_dump(mode="json")) if run.verification else None,
                    ),
                )
        except (psycopg.Error, ValueError) as exc:
            raise RepositoryError("Could not persist the workflow run.") from exc

    def get_run(self, run_id: UUID) -> WorkflowRun | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    _RUN_SELECT + " WHERE id = %s",
                    (run_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise RepositoryError("Could not load the workflow run.") from exc
        return _run_from_row(row) if row else None

    def list_runs(self, workflow_id: UUID, limit: int, offset: int) -> list[WorkflowRun]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    _RUN_SELECT
                    + " WHERE workflow_id = %s ORDER BY started_at DESC, id DESC LIMIT %s OFFSET %s",
                    (workflow_id, limit, offset),
                ).fetchall()
        except psycopg.Error as exc:
            raise RepositoryError("Could not list workflow runs.") from exc
        return [_run_from_row(row) for row in rows]

    def _connect(self):
        return psycopg.connect(self._database_url, connect_timeout=self._connect_timeout_seconds)


_RUN_SELECT = """
SELECT id, workflow_id, workflow_version, status, observations, failed_step, error,
       started_at, completed_at, definition_fingerprint, lifecycle, input_snapshots,
       facts, artifacts, warnings, drift_findings, verification
FROM workflow_runs
"""


def _run_from_row(row) -> WorkflowRun:
    return WorkflowRun.model_validate(
        {
            "run_id": row[0],
            "workflow_id": row[1],
            "version": row[2],
            "status": row[3],
            "observations": row[4],
            "failed_step": row[5],
            "error": row[6],
            "started_at": row[7],
            "completed_at": row[8],
            "definition_fingerprint": row[9],
            "lifecycle": row[10] or [],
            "input_snapshots": row[11] or [],
            "facts": row[12] or [],
            "artifacts": row[13] or [],
            "warnings": row[14] or [],
            "drift_findings": row[15] or [],
            "verification": row[16],
        }
    )
