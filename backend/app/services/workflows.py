"""In-memory recipe persistence and validated deterministic reruns."""

from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from app.agent.models import ToolObservation
from app.agent.tools import DatasetInput, ToolRegistry
from app.models.workflows import Workflow, WorkflowCreate, WorkflowRun
from app.services.datasets import inspect_dataset, load_dataset


class WorkflowError(Exception):
    """Raised for missing or incompatible workflow recipes."""


class WorkflowRepository(Protocol):
    def save(self, workflow: Workflow) -> None: ...
    def get(self, workflow_id: UUID) -> Workflow | None: ...


class InMemoryWorkflowRepository:
    def __init__(self) -> None:
        self.workflows: dict[UUID, Workflow] = {}

    def save(self, workflow: Workflow) -> None:
        self.workflows[workflow.workflow_id] = workflow.model_copy(deep=True)

    def get(self, workflow_id: UUID) -> Workflow | None:
        workflow = self.workflows.get(workflow_id)
        return workflow.model_copy(deep=True) if workflow else None


class WorkflowService:
    def __init__(self, repository: WorkflowRepository, registry: ToolRegistry) -> None:
        self._repository = repository
        self._registry = registry

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
            raise WorkflowError("Workflow was not found.")
        return workflow

    def rerun(self, workflow_id: UUID, overrides: dict[int, dict]) -> WorkflowRun:
        workflow = self.get(workflow_id)
        observations = []
        for index, step in enumerate(workflow.steps, 1):
            tool = self._registry.get(step.tool)
            if tool is None:
                return _failed(workflow, observations, index, f"Tool '{step.tool}' is unavailable.")
            arguments = {**step.arguments, **overrides.get(index, {})}
            try:
                validated = tool.input_model.model_validate(arguments)
                if step.expected_columns is not None:
                    _check_schema(validated, step.expected_columns)
                observation = tool.handler(validated)
            except (ValidationError, ValueError, WorkflowError, Exception) as exc:
                return _failed(workflow, observations, index, str(exc))
            observations.append(observation)
            if not observation.success:
                return _failed(workflow, observations, index, observation.summary)
        return WorkflowRun(workflow_id=workflow.workflow_id, version=workflow.version, status="completed", observations=observations)


def _check_schema(arguments, expected_columns: list[str]) -> None:
    if not all(hasattr(arguments, name) for name in ("filename", "content", "sheet")):
        raise WorkflowError("Schema expectations can only be applied to dataset-backed steps.")
    dataset = load_dataset(arguments.filename, arguments.content(), arguments.sheet)
    actual = inspect_dataset(dataset).columns
    if actual != expected_columns:
        raise WorkflowError(f"Schema drift detected: expected columns {expected_columns}, received {actual}.")


def _failed(workflow, observations, index, error) -> WorkflowRun:
    return WorkflowRun(
        workflow_id=workflow.workflow_id, version=workflow.version, status="failed",
        observations=observations, failed_step=index, error=error,
    )
