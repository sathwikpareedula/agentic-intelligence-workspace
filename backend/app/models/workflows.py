"""Versioned deterministic workflow recipe contracts."""

from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from pydantic import model_validator

from app.agent.models import ToolObservation

MAX_WORKFLOW_RECIPE_BYTES = 64 * 1024 * 1024


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class WorkflowStep(StrictModel):
    tool: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any]
    expected_columns: list[str] | None = None
    expected_schemas: dict[str, list[str]] | None = None
    expected_column_types: dict[str, str] | None = None
    expected_schema_types: dict[str, dict[str, str]] | None = None


class WorkflowCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    steps: list[WorkflowStep] = Field(min_length=1, max_length=50)
    source_task_id: UUID | None = None

    @model_validator(mode="after")
    def bound_recipe_size(self) -> "WorkflowCreate":
        if len(self.model_dump_json().encode("utf-8")) > MAX_WORKFLOW_RECIPE_BYTES:
            raise ValueError(
                f"Workflow recipe exceeds the {MAX_WORKFLOW_RECIPE_BYTES // (1024 * 1024)} MiB persistence limit."
            )
        return self


class Workflow(WorkflowCreate):
    workflow_id: UUID = Field(default_factory=uuid4)
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkflowRerunRequest(StrictModel):
    step_overrides: dict[Annotated[int, Field(ge=1)], dict[str, Any]] = Field(default_factory=dict)


class RunLifecycleEvent(StrictModel):
    state: Literal["created", "validating_inputs", "running", "verifying", "succeeded", "blocked", "failed"]
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RunInputSnapshot(StrictModel):
    step: int = Field(ge=1)
    input_key: str = Field(min_length=1, max_length=500)
    source_type: Literal["upload", "postgres", "rest", "document", "configuration"]
    identity: str = Field(min_length=1, max_length=500)
    fingerprint: str = Field(min_length=64, max_length=64)
    schema_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    row_count: int | None = Field(default=None, ge=0)
    columns: list[str] = Field(default_factory=list, max_length=2_000)
    column_types: dict[str, str] = Field(default_factory=dict)
    missing_value_count: int | None = Field(default=None, ge=0)
    duplicate_row_count: int | None = Field(default=None, ge=0)


class RunFact(StrictModel):
    fact_id: str = Field(min_length=1, max_length=500)
    step: int = Field(ge=1)
    key: str = Field(min_length=1, max_length=300)
    metric: str = Field(min_length=1, max_length=200)
    value: float
    label: str = Field(min_length=1, max_length=500)
    calculation: str = Field(min_length=1, max_length=500)
    grouping: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    unit: str | None = Field(default=None, min_length=1, max_length=50)


class RunArtifact(StrictModel):
    artifact_id: UUID
    filename: str | None = Field(default=None, max_length=255)
    media_type: str | None = Field(default=None, max_length=200)
    row_count: int | None = Field(default=None, ge=0)
    column_count: int | None = Field(default=None, ge=0)
    download_url: str | None = Field(default=None, max_length=500)


class RunVerificationSummary(StrictModel):
    status: Literal["verified", "verified_with_warnings", "not_run", "failed"]
    fact_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)


class RunDriftFinding(StrictModel):
    kind: Literal["schema", "source", "missing_field", "type"]
    input_key: str = Field(min_length=1, max_length=500)
    status: Literal["changed", "incompatible"]
    explanation: str = Field(min_length=1, max_length=2_000)


class WorkflowRun(StrictModel):
    run_id: UUID = Field(default_factory=uuid4)
    workflow_id: UUID
    version: int
    status: Literal["completed", "failed"]
    observations: list[ToolObservation]
    failed_step: int | None = None
    error: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    definition_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    lifecycle: list[RunLifecycleEvent] = Field(default_factory=list)
    input_snapshots: list[RunInputSnapshot] = Field(default_factory=list)
    facts: list[RunFact] = Field(default_factory=list)
    artifacts: list[RunArtifact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, max_length=1_000)
    drift_findings: list[RunDriftFinding] = Field(default_factory=list)
    verification: RunVerificationSummary | None = None


class WorkflowRunRecord(StrictModel):
    run_id: UUID
    workflow_id: UUID
    version: int = Field(ge=1)
    status: Literal["completed", "failed"]
    failed_step: int | None = None
    error: str | None = None
    started_at: datetime
    completed_at: datetime
    definition_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    lifecycle: list[RunLifecycleEvent] = Field(default_factory=list)
    input_snapshots: list[RunInputSnapshot] = Field(default_factory=list)
    facts: list[RunFact] = Field(default_factory=list)
    artifacts: list[RunArtifact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, max_length=1_000)
    drift_findings: list[RunDriftFinding] = Field(default_factory=list)
    verification: RunVerificationSummary | None = None

    @classmethod
    def from_run(cls, run: WorkflowRun) -> "WorkflowRunRecord":
        return cls.model_validate(run.model_dump(mode="python", exclude={"observations"}))


class WorkflowRunList(StrictModel):
    workflow_id: UUID
    runs: list[WorkflowRunRecord]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class WorkflowSummary(StrictModel):
    workflow_id: UUID
    name: str
    version: int = Field(ge=1)
    source_task_id: UUID | None = None
    created_at: datetime


class WorkflowList(StrictModel):
    workflows: list[WorkflowSummary]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class RunComparisonRequest(StrictModel):
    previous_run_id: UUID
    current_run_id: UUID

    @model_validator(mode="after")
    def distinct_runs(self) -> "RunComparisonRequest":
        if self.previous_run_id == self.current_run_id:
            raise ValueError("Select two distinct workflow runs to compare.")
        return self


class RunFactReference(StrictModel):
    run_id: UUID
    workflow_id: UUID
    workflow_version: int = Field(ge=1)
    fact_id: str
    value: float


class RunMetricChange(StrictModel):
    fact_id: str
    label: str
    metric: str
    unit: str | None = None
    grouping: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    status: Literal["changed", "unchanged", "added", "removed"]
    previous: RunFactReference | None = None
    current: RunFactReference | None = None
    absolute_change: float | None = None
    percent_change: float | None = None
    percent_change_reason: str | None = None


class RunCountChange(StrictModel):
    input_key: str
    identity_previous: str | None = None
    identity_current: str | None = None
    previous: int | None = Field(default=None, ge=0)
    current: int | None = Field(default=None, ge=0)
    absolute_change: int | None = None
    percent_change: float | None = None
    percent_change_reason: str | None = None


class RunSnapshotChange(StrictModel):
    input_key: str
    status: Literal["unchanged", "content_changed", "added", "removed", "incompatible"]
    explanation: str
    previous_fingerprint: str | None = None
    current_fingerprint: str | None = None
    previous_schema_fingerprint: str | None = None
    current_schema_fingerprint: str | None = None


class RunWarningChange(StrictModel):
    warning: str
    previous_count: int = Field(ge=0)
    current_count: int = Field(ge=0)
    change: int


class RunComparison(StrictModel):
    workflow_id: UUID
    previous_run_id: UUID
    current_run_id: UUID
    previous_version: int = Field(ge=1)
    current_version: int = Field(ge=1)
    metrics: list[RunMetricChange]
    row_counts: list[RunCountChange]
    snapshots: list[RunSnapshotChange]
    warnings: list[RunWarningChange]
    verification_previous: RunVerificationSummary | None = None
    verification_current: RunVerificationSummary | None = None
    artifact_count_previous: int = Field(ge=0)
    artifact_count_current: int = Field(ge=0)
    observed_only: Literal[True] = True
