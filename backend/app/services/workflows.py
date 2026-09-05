"""Versioned recipe persistence and validated deterministic reruns."""

from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from app.agent.models import ToolObservation
from app.agent.tools import DatasetInput, ToolRegistry
from app.models.workflows import Workflow, WorkflowCreate, WorkflowRun
from app.services.datasets import inspect_dataset, load_dataset
from app.services.artifacts import ArtifactRepository


class WorkflowError(Exception):
    """Raised for missing or incompatible workflow recipes."""


class WorkflowNotFoundError(WorkflowError):
    """Raised when a workflow is absent from process-local storage."""


class WorkflowRepository(Protocol):
    def save(self, workflow: Workflow) -> None: ...
    def get(self, workflow_id: UUID) -> Workflow | None: ...
    def save_run(self, run: WorkflowRun, overrides: dict[int, dict]) -> None: ...


class InMemoryWorkflowRepository:
    def __init__(self) -> None:
        self.workflows: dict[UUID, Workflow] = {}
        self.runs: dict[UUID, WorkflowRun] = {}

    def save(self, workflow: Workflow) -> None:
        self.workflows[workflow.workflow_id] = workflow.model_copy(deep=True)

    def get(self, workflow_id: UUID) -> Workflow | None:
        workflow = self.workflows.get(workflow_id)
        return workflow.model_copy(deep=True) if workflow else None

    def save_run(self, run: WorkflowRun, overrides: dict[int, dict]) -> None:
        self.runs[run.run_id] = run.model_copy(deep=True)


class WorkflowService:
    def __init__(
        self,
        repository: WorkflowRepository,
        registry: ToolRegistry,
        artifact_repository: ArtifactRepository | None = None,
    ) -> None:
        self._repository = repository
        self._registry = registry
        self._artifact_repository = artifact_repository

    def create(self, request: WorkflowCreate) -> Workflow:
        for index, step in enumerate(request.steps, 1):
            tool = self._registry.get(step.tool)
            if tool is None:
                raise WorkflowError(f"Step {index} references unknown tool '{step.tool}'.")
            try:
                tool.input_model.model_validate(step.arguments)
            except ValidationError as exc:
                raise WorkflowError(f"Step {index} arguments are invalid: {exc}") from exc
        workflow = Workflow(**request.model_dump())
        self._repository.save(workflow)
        return workflow

    def get(self, workflow_id: UUID) -> Workflow:
        workflow = self._repository.get(workflow_id)
        if workflow is None:
            raise WorkflowNotFoundError("Workflow was not found or has expired.")
        return workflow

    def rerun(self, workflow_id: UUID, overrides: dict[int, dict]) -> WorkflowRun:
        workflow = self.get(workflow_id)
        started_at = datetime.now(timezone.utc)
        invalid_steps = sorted(index for index in overrides if index > len(workflow.steps))
        if invalid_steps:
            raise WorkflowError(f"Overrides reference nonexistent step(s): {invalid_steps}.")
        observations = []
        for index, step in enumerate(workflow.steps, 1):
            tool = self._registry.get(step.tool)
            if tool is None:
                return self._save_run(_failed(workflow, observations, index, f"Tool '{step.tool}' is unavailable.", started_at), overrides)
            arguments = {**step.arguments, **overrides.get(index, {})}
            try:
                validated = tool.input_model.model_validate(arguments)
                if step.expected_columns is not None:
                    _check_schema(validated, step.expected_columns)
                observation = tool.handler(validated)
            except Exception as exc:
                return self._save_run(_failed(workflow, observations, index, str(exc), started_at), overrides)
            observations.append(observation)
            if not observation.success:
                return self._save_run(_failed(workflow, observations, index, observation.summary, started_at), overrides)
        run = WorkflowRun(
            workflow_id=workflow.workflow_id,
            version=workflow.version,
            status="completed",
            observations=observations,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
        )
        return self._save_run(run, overrides)

    def _save_run(self, run: WorkflowRun, overrides: dict[int, dict]) -> WorkflowRun:
        self._repository.save_run(run, overrides)
        artifact_ids = [
            UUID(artifact_id)
            for observation in run.observations
            for artifact_id in observation.artifact_ids
        ]
        if self._artifact_repository is not None:
            self._artifact_repository.link_to_workflow(
                artifact_ids, run.workflow_id, run.run_id
            )
        return run


def _check_schema(arguments, expected_columns: list[str]) -> None:
    if not all(hasattr(arguments, name) for name in ("filename", "content", "sheet")):
        raise WorkflowError("Schema expectations can only be applied to dataset-backed steps.")
    dataset = load_dataset(arguments.filename, arguments.content(), arguments.sheet)
    actual = inspect_dataset(dataset).columns
    if actual != expected_columns:
        raise WorkflowError(f"Schema drift detected: expected columns {expected_columns}, received {actual}.")


def _failed(workflow, observations, index, error, started_at) -> WorkflowRun:
    return WorkflowRun(
        workflow_id=workflow.workflow_id, version=workflow.version, status="failed",
        observations=observations, failed_step=index, error=error,
        started_at=started_at, completed_at=datetime.now(timezone.utc),
    )
