"""Versioned recipe persistence, immutable run history, and deterministic comparison."""

from __future__ import annotations

import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from app.agent.models import ToolObservation
from app.agent.tools import DatasetInput, ToolRegistry
from app.models.workflows import (
    RunArtifact,
    RunCategoryChange,
    RunCategorySnapshot,
    RunComparison,
    RunCountChange,
    RunDriftFinding,
    RunDiagnostic,
    RunFact,
    RunFactReference,
    RunInputSnapshot,
    RunLifecycleEvent,
    RunMetricChange,
    RunQualityChange,
    RunSnapshotChange,
    RunStepChange,
    RunStepSummary,
    RunVerificationSummary,
    RunWarningChange,
    Workflow,
    WorkflowCreate,
    WorkflowRun,
)
from app.services.datasets import inspect_dataset, load_dataset
from app.services.artifacts import ArtifactRepository


class WorkflowError(Exception):
    """Raised for missing or incompatible workflow recipes."""


class WorkflowNotFoundError(WorkflowError):
    """Raised when a workflow is absent from process-local storage."""


class WorkflowRunNotFoundError(WorkflowError):
    """Raised when a workflow run is absent from durable history."""


class WorkflowInputDriftError(WorkflowError):
    def __init__(self, message: str, finding: RunDriftFinding) -> None:
        super().__init__(message)
        self.finding = finding


class WorkflowRepository(Protocol):
    def save(self, workflow: Workflow) -> None: ...
    def get(self, workflow_id: UUID) -> Workflow | None: ...
    def list(self, limit: int, offset: int) -> list[Workflow]: ...
    def save_run(self, run: WorkflowRun, overrides: dict[int, dict]) -> None: ...
    def get_run(self, run_id: UUID) -> WorkflowRun | None: ...
    def list_runs(self, workflow_id: UUID, limit: int, offset: int) -> list[WorkflowRun]: ...


class InMemoryWorkflowRepository:
    def __init__(self) -> None:
        self.workflows: dict[UUID, Workflow] = {}
        self.runs: dict[UUID, WorkflowRun] = {}

    def save(self, workflow: Workflow) -> None:
        existing = self.workflows.get(workflow.workflow_id)
        if existing is not None and existing != workflow:
            raise WorkflowError("An existing workflow version cannot be mutated.")
        self.workflows[workflow.workflow_id] = workflow.model_copy(deep=True)

    def get(self, workflow_id: UUID) -> Workflow | None:
        workflow = self.workflows.get(workflow_id)
        return workflow.model_copy(deep=True) if workflow else None

    def list(self, limit: int, offset: int) -> list[Workflow]:
        ordered = sorted(
            self.workflows.values(), key=lambda item: (item.created_at, str(item.workflow_id)), reverse=True
        )
        return [item.model_copy(deep=True) for item in ordered[offset : offset + limit]]

    def save_run(self, run: WorkflowRun, overrides: dict[int, dict]) -> None:
        self.runs[run.run_id] = run.model_copy(deep=True)

    def get_run(self, run_id: UUID) -> WorkflowRun | None:
        run = self.runs.get(run_id)
        return run.model_copy(deep=True) if run else None

    def list_runs(self, workflow_id: UUID, limit: int, offset: int) -> list[WorkflowRun]:
        ordered = sorted(
            (item for item in self.runs.values() if item.workflow_id == workflow_id),
            key=lambda item: (item.started_at, str(item.run_id)),
            reverse=True,
        )
        return [item.model_copy(deep=True) for item in ordered[offset : offset + limit]]


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
        normalized_steps = []
        for index, step in enumerate(request.steps, 1):
            if _contains_raw_secret(step.arguments):
                raise WorkflowError(
                    f"Step {index} contains a raw secret field; persist only approved secret reference names."
                )
            tool = self._registry.get(step.tool)
            if tool is None:
                raise WorkflowError(f"Step {index} references unknown tool '{step.tool}'.")
            try:
                validated = tool.input_model.model_validate(step.arguments)
            except ValidationError as exc:
                raise WorkflowError(f"Step {index} arguments are invalid: {_validation_summary(exc)}") from exc
            normalized_steps.append(_enrich_schema_contract(step, validated))
        payload = request.model_dump()
        payload["steps"] = normalized_steps
        workflow = Workflow(**payload)
        self._repository.save(workflow)
        return workflow

    def get(self, workflow_id: UUID) -> Workflow:
        workflow = self._repository.get(workflow_id)
        if workflow is None:
            raise WorkflowNotFoundError("Workflow was not found or has expired.")
        return workflow

    def list(self, limit: int = 50, offset: int = 0) -> list[Workflow]:
        return self._repository.list(limit, offset)

    def get_run(self, run_id: UUID) -> WorkflowRun:
        run = self._repository.get_run(run_id)
        if run is None:
            raise WorkflowRunNotFoundError("Workflow run was not found.")
        return run

    def list_runs(self, workflow_id: UUID, limit: int = 50, offset: int = 0) -> list[WorkflowRun]:
        self.get(workflow_id)
        return self._repository.list_runs(workflow_id, limit, offset)

    def rerun(self, workflow_id: UUID, overrides: dict[int, dict]) -> WorkflowRun:
        workflow = self.get(workflow_id)
        started_at = datetime.now(timezone.utc)
        lifecycle = [_event("created", started_at), _event("validating_inputs")]
        snapshots: list[RunInputSnapshot] = []
        drift_findings: list[RunDriftFinding] = []
        invalid_steps = sorted(index for index in overrides if index > len(workflow.steps))
        if invalid_steps:
            raise WorkflowError(f"Overrides reference nonexistent step(s): {invalid_steps}.")
        if _contains_raw_secret(overrides):
            first_step = min(overrides, default=1)
            return self._save_run(
                _failed(
                    workflow, [], first_step, "Workflow overrides cannot include secrets.", started_at,
                    lifecycle=lifecycle, snapshots=snapshots, drift_findings=drift_findings, blocked=True,
                ),
                {},
            )
        observations = []
        lifecycle.append(_event("running"))
        for index, step in enumerate(workflow.steps, 1):
            tool = self._registry.get(step.tool)
            if tool is None:
                return self._save_run(_failed(workflow, observations, index, f"Tool '{step.tool}' is unavailable.", started_at, lifecycle=lifecycle, snapshots=snapshots), overrides)
            step_override = overrides.get(index, {})
            arguments = {**step.arguments, **step_override}
            if step.tool == "sales.august_report" and "policy_evidence" in overrides.get(index, {}):
                return self._save_run(_failed(workflow, observations, index,
                    "Saved commission evidence is pinned. Start a new sales task to retrieve a replacement policy.", started_at, lifecycle=lifecycle, snapshots=snapshots, blocked=True), overrides)
            if step.tool == "template.transform":
                unsupported = sorted(set(overrides.get(index, {})) - {"sources", "target"})
                if unsupported:
                    return self._save_run(_failed(workflow, observations, index,
                        f"Saved mappings, rules, and policy evidence are pinned; unsupported overrides: {unsupported}.", started_at, lifecycle=lifecycle, snapshots=snapshots, blocked=True), overrides)
            if step_override and (step.tool.startswith("source.") or step.tool == "analytics.sql"):
                return self._save_run(_failed(workflow, observations, index,
                    "External-source workflow configuration is pinned and cannot be overridden.", started_at, lifecycle=lifecycle, snapshots=snapshots, blocked=True), {})
            try:
                validated = tool.input_model.model_validate(arguments)
                snapshots.extend(_snapshot_inputs(index, validated.model_dump(mode="json")))
                if step.expected_columns is not None:
                    _check_schema(validated, step.expected_columns, step.expected_column_types, f"step.{index}.input")
                if step.expected_schemas is not None:
                    _check_nested_schemas(validated, step.expected_schemas, step.expected_schema_types or {}, index)
                observation = tool.handler(validated)
                if observation.tool_name is None:
                    observation = observation.model_copy(update={"tool_name": step.tool})
                snapshots = _merge_observation_provenance(snapshots, index, observation)
            except Exception as exc:
                message = _validation_summary(exc) if isinstance(exc, ValidationError) else str(exc)
                if isinstance(exc, WorkflowInputDriftError):
                    drift_findings.append(exc.finding)
                return self._save_run(_failed(workflow, observations, index, message, started_at, lifecycle=lifecycle, snapshots=snapshots, drift_findings=drift_findings, blocked=isinstance(exc, WorkflowInputDriftError)), overrides)
            observations.append(observation)
            if not observation.success:
                return self._save_run(_failed(workflow, observations, index, observation.summary, started_at, lifecycle=lifecycle, snapshots=snapshots), overrides)
        lifecycle.append(_event("verifying"))
        try:
            facts, artifacts, warnings, step_summaries, diagnostics = _collect_run_outputs(observations)
        except WorkflowError as exc:
            return self._save_run(_failed(workflow, observations, len(workflow.steps), str(exc), started_at, lifecycle=lifecycle, snapshots=snapshots), overrides)
        lifecycle.append(_event("succeeded"))
        verification = RunVerificationSummary(
            status=("verified_with_warnings" if warnings else "verified") if facts else "not_run",
            fact_count=len(facts),
            warning_count=len(warnings),
        )
        run = WorkflowRun(
            workflow_id=workflow.workflow_id, version=workflow.version, status="completed",
            observations=observations, started_at=started_at, completed_at=datetime.now(timezone.utc),
            definition_fingerprint=_workflow_fingerprint(workflow), lifecycle=lifecycle,
            input_snapshots=_unique_snapshots(snapshots), facts=facts, artifacts=artifacts,
            warnings=warnings, drift_findings=drift_findings, verification=verification,
            step_summaries=step_summaries, diagnostics=diagnostics,
        )
        return self._save_run(run, overrides)

    def compare_runs(self, previous_run_id: UUID, current_run_id: UUID) -> RunComparison:
        previous = self.get_run(previous_run_id)
        current = self.get_run(current_run_id)
        if previous.workflow_id != current.workflow_id:
            raise WorkflowError("Only runs of the same workflow can be compared.")
        if previous.status != "completed" or current.status != "completed":
            raise WorkflowError("Only completed workflow runs can be compared.")
        return _compare_completed_runs(previous, current)

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


def _check_schema(
    arguments,
    expected_columns: list[str],
    expected_types: dict[str, str] | None,
    input_key: str,
) -> None:
    if not all(hasattr(arguments, name) for name in ("filename", "content", "sheet")):
        raise WorkflowError("Schema expectations can only be applied to dataset-backed steps.")
    dataset = load_dataset(arguments.filename, arguments.content(), arguments.sheet)
    inspection = inspect_dataset(dataset)
    actual = inspection.columns
    if actual != expected_columns:
        message = f"Schema drift detected: expected columns {expected_columns}, received {actual}."
        raise WorkflowInputDriftError(
            message,
            RunDriftFinding(kind="schema", input_key=input_key, status="incompatible", explanation=message),
        )
    actual_types = {item.name: item.data_type for item in inspection.column_details}
    if expected_types is not None and actual_types != expected_types:
        message = f"Type drift detected: expected {expected_types}, received {actual_types}."
        raise WorkflowInputDriftError(
            message,
            RunDriftFinding(kind="type", input_key=input_key, status="incompatible", explanation=message),
        )


def _contains_raw_secret(value, *, reference_container: bool = False) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().casefold().replace("-", "_")
            is_reference = normalized.endswith("_secret_ref") or normalized.endswith("_secret_refs")
            if not reference_container and not is_reference and any(
                marker in normalized
                for marker in ("api_key", "apikey", "authorization", "credential", "password", "secret", "token")
            ):
                return True
            if not is_reference and _contains_raw_secret(child):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_raw_secret(item, reference_container=reference_container) for item in value)
    return False


def _validation_summary(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'arguments'}: {error['msg']}"
        for error in exc.errors(include_context=False, include_input=False)
    )


def _check_nested_schemas(
    arguments,
    expected_schemas: dict[str, list[str]],
    expected_schema_types: dict[str, dict[str, str]],
    step: int,
) -> None:
    for resource_name, expected_columns in expected_schemas.items():
        resource = getattr(arguments, resource_name, None)
        if resource is None or not all(hasattr(resource, name) for name in ("filename", "content", "sheet")):
            raise WorkflowError(
                f"Schema expectation for '{resource_name}' does not reference a dataset-backed argument."
            )
        dataset = load_dataset(resource.filename, resource.content(), resource.sheet)
        inspection = inspect_dataset(dataset)
        actual = inspection.columns
        if actual != expected_columns:
            message = f"Schema drift detected for {resource_name}: expected columns {expected_columns}, received {actual}."
            raise WorkflowInputDriftError(
                message,
                RunDriftFinding(
                    kind="schema", input_key=f"step.{step}.{resource_name}", status="incompatible", explanation=message
                ),
            )
        actual_types = {item.name: item.data_type for item in inspection.column_details}
        expected_types = expected_schema_types.get(resource_name)
        if expected_types is not None and actual_types != expected_types:
            message = f"Type drift detected for {resource_name}: expected {expected_types}, received {actual_types}."
            raise WorkflowInputDriftError(
                message,
                RunDriftFinding(
                    kind="type", input_key=f"step.{step}.{resource_name}", status="incompatible", explanation=message
                ),
            )


def _failed(
    workflow,
    observations,
    index,
    error,
    started_at,
    *,
    lifecycle=None,
    snapshots=None,
    drift_findings=None,
    blocked: bool = False,
) -> WorkflowRun:
    events = list(lifecycle or [])
    events.append(_event("blocked" if blocked else "failed"))
    warnings = [warning for observation in observations for warning in observation.warnings]
    step_summaries, diagnostics = _collect_observability(observations)
    if not step_summaries or step_summaries[-1].step != index:
        tool_name = workflow.steps[index - 1].tool if 0 < index <= len(workflow.steps) else "workflow.validation"
        step_summaries.append(
            RunStepSummary(
                step=index,
                tool_name=tool_name,
                status="blocked" if blocked else "failed",
                summary=str(error)[:2_000] or "Workflow execution failed.",
                warning_count=0,
                artifact_count=0,
                source_count=0,
            )
        )
    elif blocked:
        step_summaries[-1] = step_summaries[-1].model_copy(update={"status": "blocked"})
    return WorkflowRun(
        workflow_id=workflow.workflow_id, version=workflow.version, status="failed",
        observations=observations, failed_step=index, error=error,
        started_at=started_at, completed_at=datetime.now(timezone.utc),
        definition_fingerprint=_workflow_fingerprint(workflow), lifecycle=events,
        input_snapshots=_unique_snapshots(snapshots or []), warnings=warnings,
        drift_findings=drift_findings or [],
        verification=RunVerificationSummary(status="failed", fact_count=0, warning_count=len(warnings)),
        step_summaries=step_summaries, diagnostics=diagnostics,
    )


def _event(state: str, occurred_at: datetime | None = None) -> RunLifecycleEvent:
    return RunLifecycleEvent(state=state, occurred_at=occurred_at or datetime.now(timezone.utc))


def _canonical_hash(value) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _workflow_fingerprint(workflow: Workflow) -> str:
    return _canonical_hash(
        {
            "workflow_id": str(workflow.workflow_id),
            "version": workflow.version,
            "steps": [step.model_dump(mode="json") for step in workflow.steps],
        }
    )


def _enrich_schema_contract(step, validated):
    updates: dict[str, object] = {}
    if step.expected_columns is not None and step.expected_column_types is None:
        inspection = _inspect_dataset_argument(validated)
        if inspection is not None:
            updates["expected_column_types"] = {
                item.name: item.data_type for item in inspection.column_details
            }
    if step.expected_schemas is not None and step.expected_schema_types is None:
        nested: dict[str, dict[str, str]] = {}
        for name in step.expected_schemas:
            resource = getattr(validated, name, None)
            inspection = _inspect_dataset_argument(resource)
            if inspection is not None:
                nested[name] = {item.name: item.data_type for item in inspection.column_details}
        if nested:
            updates["expected_schema_types"] = nested
    return step.model_copy(update=updates)


def _inspect_dataset_argument(value):
    if value is None or not all(hasattr(value, name) for name in ("filename", "content", "sheet")):
        return None
    return inspect_dataset(load_dataset(value.filename, value.content(), value.sheet))


def _snapshot_inputs(step: int, value, path: str = "input") -> list[RunInputSnapshot]:
    snapshots: list[RunInputSnapshot] = []
    if isinstance(value, dict):
        if isinstance(value.get("filename"), str) and isinstance(value.get("content_base64"), str):
            try:
                content = base64.b64decode(value["content_base64"], validate=True)
            except ValueError as exc:
                raise WorkflowError(f"Invalid encoded dataset at {path}.") from exc
            dataset = load_dataset(value["filename"], content, value.get("sheet"))
            inspection = inspect_dataset(dataset)
            column_types = {item.name: item.data_type for item in inspection.column_details}
            missing_by_column, categories = _dataset_quality(dataset)
            schema = {"columns": inspection.columns, "types": column_types}
            snapshots.append(
                RunInputSnapshot(
                    step=step, input_key=f"step.{step}.{path}", source_type="upload",
                    identity=value["filename"], fingerprint=hashlib.sha256(content).hexdigest(),
                    schema_fingerprint=_canonical_hash(schema), row_count=inspection.row_count,
                    columns=inspection.columns, column_types=column_types,
                    missing_value_count=sum(item.missing_count for item in inspection.column_details),
                    duplicate_row_count=inspection.duplicate_row_count,
                    missing_by_column=missing_by_column, categories=categories,
                )
            )
            return snapshots
        if all(key in value for key in ("host", "database", "user", "password_secret_ref")):
            safe = {key: child for key, child in value.items() if key != "password"}
            identity = f"postgres://{value['user']}@{value['host']}:{value.get('port', 5432)}/{value['database']}"
            snapshots.append(
                RunInputSnapshot(
                    step=step, input_key=f"step.{step}.{path}", source_type="postgres",
                    identity=identity, fingerprint=_canonical_hash(safe),
                )
            )
            return snapshots
        if isinstance(value.get("url"), str) and "header_secret_refs" in value:
            snapshots.append(
                RunInputSnapshot(
                    step=step, input_key=f"step.{step}.{path}", source_type="rest",
                    identity=value["url"], fingerprint=_canonical_hash(value),
                )
            )
            return snapshots
        for key, child in value.items():
            snapshots.extend(_snapshot_inputs(step, child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            snapshots.extend(_snapshot_inputs(step, child, f"{path}.{index}"))
    return snapshots


def _unique_snapshots(snapshots: list[RunInputSnapshot]) -> list[RunInputSnapshot]:
    unique: dict[str, RunInputSnapshot] = {}
    for snapshot in snapshots:
        existing = unique.get(snapshot.input_key)
        if existing is not None and existing != snapshot:
            raise WorkflowError(f"Run input snapshot identity collision at '{snapshot.input_key}'.")
        unique[snapshot.input_key] = snapshot
    return [unique[key] for key in sorted(unique)]


def _merge_observation_provenance(
    snapshots: list[RunInputSnapshot], step: int, observation: ToolObservation
) -> list[RunInputSnapshot]:
    result = observation.result or {}
    provenance = result.get("provenance")
    inspection = result.get("inspection")
    if not isinstance(provenance, dict):
        return snapshots
    source_type = provenance.get("source_type")
    if source_type not in {"postgres", "rest"}:
        return snapshots
    column_types: dict[str, str] = {}
    columns: list[str] = []
    schema_fingerprint = None
    missing_count = None
    duplicate_count = None
    missing_by_column: dict[str, int] = {}
    categories: dict[str, RunCategorySnapshot] = {}
    if isinstance(inspection, dict):
        columns = [str(item) for item in inspection.get("columns", [])]
        details = inspection.get("column_details", [])
        column_types = {
            str(item["name"]): str(item["data_type"])
            for item in details
            if isinstance(item, dict) and "name" in item and "data_type" in item
        }
        schema_fingerprint = _canonical_hash({"columns": columns, "types": column_types})
        missing_count = sum(
            int(item.get("missing_count", 0)) for item in details if isinstance(item, dict)
        )
        duplicate_count = inspection.get("duplicate_row_count")
    dataset_payload = result.get("dataset")
    if isinstance(dataset_payload, dict) and isinstance(dataset_payload.get("content_base64"), str):
        try:
            content = base64.b64decode(dataset_payload["content_base64"], validate=True)
            loaded = load_dataset(dataset_payload["filename"], content, dataset_payload.get("sheet"))
            missing_by_column, categories = _dataset_quality(loaded)
        except (KeyError, ValueError):
            missing_by_column, categories = {}, {}
    updated = list(snapshots)
    candidates = [
        index for index, snapshot in enumerate(updated)
        if snapshot.step == step and snapshot.source_type == source_type
    ]
    if not candidates:
        return snapshots
    index = candidates[-1]
    updated[index] = updated[index].model_copy(
        update={
            "identity": str(provenance.get("identity") or updated[index].identity),
            "fingerprint": str(provenance.get("config_fingerprint") or updated[index].fingerprint),
            "schema_fingerprint": schema_fingerprint,
            "row_count": provenance.get("row_count"),
            "columns": columns,
            "column_types": column_types,
            "missing_value_count": missing_count,
            "duplicate_row_count": duplicate_count,
            "missing_by_column": missing_by_column,
            "categories": categories,
        }
    )
    return updated


def _dataset_quality(dataset) -> tuple[dict[str, int], dict[str, RunCategorySnapshot]]:
    frame = dataset.frame
    missing = {str(column): int(frame[column].isna().sum()) for column in frame.columns}
    categories: dict[str, RunCategorySnapshot] = {}
    for column in frame.columns:
        series = frame[column]
        if getattr(series.dtype, "kind", "") in {"i", "u", "f", "c"}:
            continue
        values = sorted({str(value) for value in series.dropna().tolist()})
        complete = len(values) <= 100 and all(len(value) <= 200 for value in values)
        categories[str(column)] = RunCategorySnapshot(
            unique_count=len(values), values=values if complete else [], values_complete=complete
        )
    return missing, categories


def _collect_run_outputs(observations: list[ToolObservation]):
    facts: dict[str, RunFact] = {}
    artifacts: dict[UUID, RunArtifact] = {}
    warnings: list[str] = []
    for step, observation in enumerate(observations, 1):
        warnings.extend(observation.warnings)
        result = observation.result or {}
        metadata_by_key = {
            item.get("key"): item for item in result.get("facts", [])
            if isinstance(item, dict) and isinstance(item.get("key"), str)
        }
        raw_facts = result.get("verification_facts", {})
        if isinstance(raw_facts, dict):
            for key, value in raw_facts.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    raise WorkflowError(f"Workflow produced a non-finite or non-numeric fact for '{key}'.")
                metadata = metadata_by_key.get(key, {})
                fact_id = f"step.{step}.{key}"
                fact = RunFact(
                    fact_id=fact_id, step=step, key=key,
                    metric=str(metadata.get("metric") or key), value=float(value),
                    label=str(metadata.get("label") or key),
                    calculation=str(metadata.get("calculation") or f"deterministic result from step {step}"),
                    grouping=metadata.get("grouping") if isinstance(metadata.get("grouping"), dict) else {},
                    unit=metadata.get("unit"),
                )
                if fact_id in facts:
                    raise WorkflowError(f"Workflow produced an ambiguous repeated fact identity '{fact_id}'.")
                facts[fact_id] = fact
        raw_artifact = result.get("artifact")
        if isinstance(raw_artifact, dict) and raw_artifact.get("artifact_id"):
            artifact = RunArtifact.model_validate(raw_artifact)
            artifacts[artifact.artifact_id] = artifact
        for artifact_id in observation.artifact_ids:
            parsed = UUID(artifact_id)
            artifacts.setdefault(parsed, RunArtifact(artifact_id=parsed))
    step_summaries, diagnostics = _collect_observability(observations)
    return list(facts.values()), list(artifacts.values()), warnings, step_summaries, diagnostics


def _collect_observability(
    observations: list[ToolObservation],
) -> tuple[list[RunStepSummary], list[RunDiagnostic]]:
    steps: list[RunStepSummary] = []
    diagnostics: dict[str, RunDiagnostic] = {}
    for step, observation in enumerate(observations, 1):
        steps.append(
            RunStepSummary(
                step=step,
                tool_name=observation.tool_name or "unknown",
                status="succeeded" if observation.success else "failed",
                summary=observation.summary[:2_000] or "No summary was recorded.",
                warning_count=len(observation.warnings),
                artifact_count=len(observation.artifact_ids),
                source_count=len(observation.source_ids),
            )
        )
        result = observation.result or {}
        for root in ("join_diagnostics", "target_join_diagnostics", "data_quality", "trace_metadata", "diagnostics"):
            value = result.get(root)
            if isinstance(value, dict):
                for path, raw_value in _numeric_leaves(value, root):
                    if isinstance(raw_value, bool):
                        numeric = float(int(raw_value))
                    elif isinstance(raw_value, (int, float)) and math.isfinite(float(raw_value)):
                        numeric = float(raw_value)
                    else:
                        continue
                    diagnostic_id = f"step.{step}.{path}"
                    if diagnostic_id in diagnostics:
                        raise WorkflowError(f"Workflow produced an ambiguous diagnostic identity '{diagnostic_id}'.")
                    lowered = path.casefold()
                    kind = "join" if any(marker in lowered for marker in ("join", "unmatched", "multiplication")) else "quality"
                    unit = "percent" if any(marker in lowered for marker in ("percent", "_pct", "percentage")) else "count" if any(marker in lowered for marker in ("row", "count", "duplicate", "missing", "unmatched")) else "value"
                    diagnostics[diagnostic_id] = RunDiagnostic(
                        diagnostic_id=diagnostic_id,
                        step=step,
                        kind=kind,
                        label=path.replace("_", " ").replace(".", " · "),
                        value=numeric,
                        unit=unit,
                    )
    return steps, list(diagnostics.values())


def _numeric_leaves(value: dict, prefix: str):
    for key in sorted(value):
        child = value[key]
        path = f"{prefix}.{key}"
        if isinstance(child, dict):
            yield from _numeric_leaves(child, path)
        else:
            yield path, child


def _compare_completed_runs(previous: WorkflowRun, current: WorkflowRun) -> RunComparison:
    previous_facts = _fact_map(previous)
    current_facts = _fact_map(current)
    metrics: list[RunMetricChange] = []
    for fact_id in sorted(set(previous_facts) | set(current_facts)):
        before = previous_facts.get(fact_id)
        after = current_facts.get(fact_id)
        if before is not None and after is not None:
            if (before.metric, before.unit, before.grouping, before.calculation) != (
                after.metric, after.unit, after.grouping, after.calculation
            ):
                raise WorkflowError(f"Fact '{fact_id}' changed meaning between workflow runs.")
            absolute = after.value - before.value
            percent, reason = _percentage_change(before.value, after.value)
            status = "unchanged" if absolute == 0 else "changed"
        else:
            absolute = None
            percent = None
            reason = "Metric is unavailable in one run; missing values are not treated as zero."
            status = "added" if after is not None else "removed"
        exemplar = after or before
        assert exemplar is not None
        metrics.append(
            RunMetricChange(
                fact_id=fact_id, label=exemplar.label, metric=exemplar.metric, unit=exemplar.unit,
                grouping=exemplar.grouping, status=status,
                previous=_fact_reference(previous, before) if before else None,
                current=_fact_reference(current, after) if after else None,
                absolute_change=absolute, percent_change=percent, percent_change_reason=reason,
            )
        )

    previous_snapshots = _snapshot_map(previous)
    current_snapshots = _snapshot_map(current)
    snapshot_changes: list[RunSnapshotChange] = []
    row_counts: list[RunCountChange] = []
    quality_changes: list[RunQualityChange] = []
    category_changes: list[RunCategoryChange] = []
    for key in sorted(set(previous_snapshots) | set(current_snapshots)):
        before = previous_snapshots.get(key)
        after = current_snapshots.get(key)
        if before is None:
            snapshot_status, explanation = "added", "Input is present only in the current run."
        elif after is None:
            snapshot_status, explanation = "removed", "Input is present only in the previous run."
        elif before.schema_fingerprint != after.schema_fingerprint:
            snapshot_status, explanation = "incompatible", "Input schema or column types changed."
        elif before.fingerprint == after.fingerprint:
            snapshot_status, explanation = "unchanged", "Input content and schema are unchanged."
        else:
            snapshot_status, explanation = "content_changed", "Input content changed while its schema remained compatible."
        added_columns = sorted(set(after.columns) - set(before.columns)) if before and after else []
        removed_columns = sorted(set(before.columns) - set(after.columns)) if before and after else []
        type_changes = {
            column: {"previous": before.column_types[column], "current": after.column_types[column]}
            for column in sorted(set(before.column_types) & set(after.column_types))
            if before.column_types[column] != after.column_types[column]
        } if before is not None and after is not None else {}
        snapshot_changes.append(
            RunSnapshotChange(
                input_key=key, status=snapshot_status, explanation=explanation,
                previous_fingerprint=before.fingerprint if before else None,
                current_fingerprint=after.fingerprint if after else None,
                previous_schema_fingerprint=before.schema_fingerprint if before else None,
                current_schema_fingerprint=after.schema_fingerprint if after else None,
                added_columns=added_columns, removed_columns=removed_columns, type_changes=type_changes,
            )
        )
        before_count = before.row_count if before else None
        after_count = after.row_count if after else None
        if before_count is not None or after_count is not None:
            absolute = after_count - before_count if before_count is not None and after_count is not None else None
            percent, reason = _percentage_change(before_count, after_count) if before_count is not None and after_count is not None else (None, "Row count is unavailable in one run.")
            row_counts.append(
                RunCountChange(
                    input_key=key, identity_previous=before.identity if before else None,
                    identity_current=after.identity if after else None,
                    previous=before_count, current=after_count, absolute_change=absolute,
                    percent_change=percent, percent_change_reason=reason,
                )
            )
        if before is not None and after is not None:
            for column in sorted(set(before.missing_by_column) | set(after.missing_by_column)):
                quality_changes.append(
                    _quality_change(
                        f"{key}.missing.{column}", "quality", f"Missing values · {column}",
                        before.missing_by_column.get(column), after.missing_by_column.get(column),
                        previous.run_id, current.run_id,
                    )
                )
            if before.duplicate_row_count is not None or after.duplicate_row_count is not None:
                quality_changes.append(
                    _quality_change(
                        f"{key}.duplicates", "quality", "Duplicate rows",
                        before.duplicate_row_count, after.duplicate_row_count,
                        previous.run_id, current.run_id,
                    )
                )
            for column in sorted(set(before.categories) | set(after.categories)):
                old_category = before.categories.get(column)
                new_category = after.categories.get(column)
                quality_changes.append(
                    _quality_change(
                        f"{key}.unique.{column}", "category", f"Unique values · {column}",
                        old_category.unique_count if old_category else None,
                        new_category.unique_count if new_category else None,
                        previous.run_id, current.run_id,
                    )
                )
                if old_category is not None and new_category is not None:
                    complete = old_category.values_complete and new_category.values_complete
                    category_changes.append(
                        RunCategoryChange(
                            input_key=key, column=column,
                            previous_unique_count=old_category.unique_count,
                            current_unique_count=new_category.unique_count,
                            added=sorted(set(new_category.values) - set(old_category.values)) if complete else [],
                            removed=sorted(set(old_category.values) - set(new_category.values)) if complete else [],
                            values_complete=complete,
                            previous_run_id=previous.run_id, current_run_id=current.run_id,
                        )
                    )

    previous_warnings = Counter(previous.warnings)
    current_warnings = Counter(current.warnings)
    warning_changes = [
        RunWarningChange(
            warning=warning, previous_count=previous_warnings[warning], current_count=current_warnings[warning],
            change=current_warnings[warning] - previous_warnings[warning],
        )
        for warning in sorted(set(previous_warnings) | set(current_warnings))
        if previous_warnings[warning] != current_warnings[warning]
    ]
    previous_diagnostics = {item.diagnostic_id: item for item in previous.diagnostics}
    current_diagnostics = {item.diagnostic_id: item for item in current.diagnostics}
    for diagnostic_id in sorted(set(previous_diagnostics) | set(current_diagnostics)):
        before = previous_diagnostics.get(diagnostic_id)
        after = current_diagnostics.get(diagnostic_id)
        exemplar = after or before
        assert exemplar is not None
        if before is not None and after is not None and (before.kind, before.unit) != (after.kind, after.unit):
            raise WorkflowError(f"Diagnostic '{diagnostic_id}' changed meaning between workflow runs.")
        quality_changes.append(
            _quality_change(
                diagnostic_id, "join" if exemplar.kind == "join" else "quality",
                exemplar.label, before.value if before else None, after.value if after else None,
                previous.run_id, current.run_id, unit=exemplar.unit,
            )
        )
    previous_steps = {item.step: item for item in previous.step_summaries}
    current_steps = {item.step: item for item in current.step_summaries}
    step_changes: list[RunStepChange] = []
    for step in sorted(set(previous_steps) | set(current_steps)):
        before = previous_steps.get(step)
        after = current_steps.get(step)
        if before is not None and after is not None and before.tool_name != after.tool_name:
            raise WorkflowError(f"Workflow step {step} changed tool identity between runs.")
        exemplar = after or before
        assert exemplar is not None
        step_changes.append(
            RunStepChange(
                step=step, tool_name=exemplar.tool_name,
                previous_status=before.status if before else None,
                current_status=after.status if after else None,
                warning_change=(after.warning_count if after else 0) - (before.warning_count if before else 0),
                artifact_change=(after.artifact_count if after else 0) - (before.artifact_count if before else 0),
                previous_run_id=previous.run_id, current_run_id=current.run_id,
            )
        )
    return RunComparison(
        workflow_id=previous.workflow_id, previous_run_id=previous.run_id, current_run_id=current.run_id,
        previous_version=previous.version, current_version=current.version, metrics=metrics,
        row_counts=row_counts, snapshots=snapshot_changes, warnings=warning_changes,
        verification_previous=previous.verification, verification_current=current.verification,
        artifact_count_previous=len(previous.artifacts), artifact_count_current=len(current.artifacts),
        quality=quality_changes, categories=category_changes, steps=step_changes,
    )


def _fact_map(run: WorkflowRun) -> dict[str, RunFact]:
    result: dict[str, RunFact] = {}
    for fact in run.facts:
        if fact.fact_id in result:
            raise WorkflowError(f"Run {run.run_id} contains ambiguous fact identity '{fact.fact_id}'.")
        result[fact.fact_id] = fact
    return result


def _snapshot_map(run: WorkflowRun) -> dict[str, RunInputSnapshot]:
    result: dict[str, RunInputSnapshot] = {}
    for snapshot in run.input_snapshots:
        if snapshot.input_key in result:
            raise WorkflowError(f"Run {run.run_id} contains ambiguous input identity '{snapshot.input_key}'.")
        result[snapshot.input_key] = snapshot
    return result


def _fact_reference(run: WorkflowRun, fact: RunFact) -> RunFactReference:
    return RunFactReference(
        run_id=run.run_id, workflow_id=run.workflow_id, workflow_version=run.version,
        fact_id=fact.fact_id, value=fact.value,
    )


def _percentage_change(previous: int | float, current: int | float) -> tuple[float | None, str | None]:
    if previous == 0:
        return None, "Percentage change is undefined because the previous value is zero."
    value = (float(current) - float(previous)) / float(previous) * 100.0
    if not math.isfinite(value):
        return None, "Percentage change is non-finite and was omitted."
    return value, None


def _quality_change(
    quality_id: str,
    section: str,
    label: str,
    previous: int | float | None,
    current: int | float | None,
    previous_run_id: UUID,
    current_run_id: UUID,
    *,
    unit: str = "count",
) -> RunQualityChange:
    absolute = float(current) - float(previous) if previous is not None and current is not None else None
    percent, reason = _percentage_change(previous, current) if previous is not None and current is not None else (None, "Value is unavailable in one run.")
    return RunQualityChange(
        quality_id=quality_id, section=section, label=label, unit=unit,
        previous=float(previous) if previous is not None else None,
        current=float(current) if current is not None else None,
        absolute_change=absolute, percent_change=percent, percent_change_reason=reason,
        previous_run_id=previous_run_id, current_run_id=current_run_id,
    )
