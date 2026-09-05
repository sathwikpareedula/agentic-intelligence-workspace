"""Persist structured run provenance and connect resulting artifacts to the run."""

from app.agent.models import AgentExecution
from app.repositories.executions import ExecutionRepository
from app.services.artifacts import ArtifactRepository


def persist_execution(
    execution: AgentExecution,
    execution_repository: ExecutionRepository,
    artifact_repository: ArtifactRepository,
) -> None:
    verification_status = "not_verified"
    if execution.verification is not None:
        verification_status = "verified" if execution.verification.status == "verified" else "failed"
    artifact_repository.link_to_execution(
        [artifact.artifact_id for artifact in execution.artifacts],
        execution.task_id,
        verification_status,
    )
    execution_repository.save(execution)
