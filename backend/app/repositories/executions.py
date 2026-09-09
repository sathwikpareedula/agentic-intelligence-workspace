"""Structured execution provenance repositories; no hidden reasoning is stored."""

from typing import Protocol
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from app.agent.models import AgentExecution
from app.repositories.documents import RepositoryError


class ExecutionRepository(Protocol):
    def save(self, execution: AgentExecution) -> None: ...


class InMemoryExecutionRepository:
    def __init__(self) -> None:
        self.executions: dict[UUID, AgentExecution] = {}

    def save(self, execution: AgentExecution) -> None:
        self.executions[execution.task_id] = execution.model_copy(deep=True)


class PostgresExecutionRepository:
    def __init__(self, database_url: str, connect_timeout_seconds: int = 3) -> None:
        self._database_url = database_url
        self._connect_timeout_seconds = connect_timeout_seconds

    def save(self, execution: AgentExecution) -> None:
        try:
            with psycopg.connect(
                self._database_url,
                connect_timeout=self._connect_timeout_seconds,
            ) as connection:
                connection.execute(
                    """
                    INSERT INTO execution_runs
                        (id, user_goal, status, started_at, completed_at, tool_trace,
                         artifact_ids, verification, failure_reason, provider_usage)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        execution.task_id,
                        execution.goal,
                        execution.status,
                        execution.started_at,
                        execution.completed_at,
                        Jsonb([step.model_dump(mode="json") for step in execution.trace]),
                        [artifact.artifact_id for artifact in execution.artifacts],
                        Jsonb(execution.verification.model_dump(mode="json")) if execution.verification else None,
                        execution.failure_reason,
                        Jsonb(execution.provider_usage.model_dump(mode="json")) if execution.provider_usage else None,
                    ),
                )
        except psycopg.Error as exc:
            raise RepositoryError("Could not persist execution provenance.") from exc
