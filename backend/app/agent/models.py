"""Typed contracts for model decisions, tool observations, and execution traces."""

from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4
import base64

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.retrieval import SourceReference
from app.models.grades import PolicyEvidence


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ToolCall(StrictModel):
    type: Literal["tool_call"] = "tool_call"
    tool: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)


class Complete(StrictModel):
    type: Literal["complete"] = "complete"
    answer: str = Field(min_length=1, max_length=20000)
    claims: list["AnswerClaim"] = Field(default_factory=list)


class AnswerClaim(StrictModel):
    text: str = Field(min_length=1, max_length=2000)
    kind: Literal["numeric", "document"]
    value: float | None = None
    source_ids: list[str] = Field(default_factory=list)
    evidence_keys: list[str] = Field(default_factory=list)


ModelDecision = Annotated[ToolCall | Complete, Field(discriminator="type")]


class ModelDecisionEnvelope(StrictModel):
    decision: ModelDecision


class ToolObservation(StrictModel):
    success: bool
    summary: str
    result: dict[str, Any] | None = None
    error_code: str | None = None
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None
    recoverable: bool = True
    artifact_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    stages: list["ExecutionStage"] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TraceStep(StrictModel):
    step: int = Field(ge=1)
    requested_tool: str
    validated_arguments: dict[str, Any] | None = None
    success: bool
    observation: str
    error_code: str | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    duration_ms: float = Field(ge=0)
    stage: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ExecutionStage(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    status: Literal["completed", "warning", "failed"]
    explanation: str = Field(min_length=1, max_length=2000)
    tool_name: str | None = Field(default=None, max_length=100)
    row_counts: dict[str, int] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    verification_result: str | None = Field(default=None, max_length=100)


class ArtifactReference(StrictModel):
    artifact_id: UUID
    filename: str
    media_type: str
    download_url: str
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)


class WorkflowReference(StrictModel):
    workflow_id: UUID
    name: str
    version: int = Field(ge=1)
    rerun_url: str


class AgentExecution(StrictModel):
    task_id: UUID = Field(default_factory=uuid4)
    goal: str
    status: Literal["completed", "failed", "iteration_limit"]
    answer: str | None = None
    trace: list[TraceStep]
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime
    failure_reason: str | None = None
    failure_code: str | None = None
    verification: "VerificationReport | None" = None
    citations: list[SourceReference] = Field(default_factory=list)
    evidence: list[PolicyEvidence] = Field(default_factory=list)
    artifacts: list[ArtifactReference] = Field(default_factory=list)
    stages: list[ExecutionStage] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    saved_workflow: WorkflowReference | None = None


class VerificationFinding(StrictModel):
    status: Literal["verified", "warning", "unsupported", "conflicting", "insufficient_evidence", "failed"]
    claim: str
    explanation: str


class VerificationReport(StrictModel):
    status: Literal["verified", "verified_with_warnings", "unsupported", "conflicting", "insufficient_evidence", "failed"]
    findings: list[VerificationFinding] = Field(default_factory=list)


class AgentTaskRequest(StrictModel):
    goal: str = Field(min_length=1, max_length=10000)
    max_iterations: int = Field(default=8, ge=1, le=25)
    resources: "AgentTaskResources | None" = None


class AgentDatasetResource(StrictModel):
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1, max_length=14_000_000)
    sheet: str | None = Field(default=None, max_length=255)

    def content(self) -> bytes:
        try:
            return base64.b64decode(self.content_base64, validate=True)
        except ValueError as exc:
            raise ValueError("content_base64 is not valid base64.") from exc


class AgentTaskResources(StrictModel):
    # Singular fields preserve the original grades-demo API. The plural fields
    # are the production path for general tasks over multiple bound resources.
    dataset: AgentDatasetResource | None = None
    document_id: UUID | None = None
    datasets: list[AgentDatasetResource] = Field(default_factory=list, max_length=8)
    document_ids: list[UUID] = Field(default_factory=list, max_length=8)
    workflow_ids: list[UUID] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_resources(self) -> "AgentTaskResources":
        datasets = self.all_datasets()
        document_ids = self.all_document_ids()
        if not datasets and not document_ids and not self.workflow_ids:
            raise ValueError("Provide at least one dataset, document ID, or workflow ID.")
        if len(datasets) > 8:
            raise ValueError("An agent task may bind at most 8 datasets.")
        if sum(len(item.content_base64) for item in datasets) > 56_000_000:
            raise ValueError("Combined encoded dataset content exceeds the 56,000,000-character task limit.")
        if len(document_ids) > 8:
            raise ValueError("An agent task may bind at most 8 document IDs.")
        filenames = [item.filename for item in datasets]
        if len(filenames) != len(set(filenames)):
            raise ValueError("Dataset filenames must be unique within an agent task.")
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("Document IDs must be unique within an agent task.")
        if len(self.workflow_ids) != len(set(self.workflow_ids)):
            raise ValueError("Workflow IDs must be unique within an agent task.")
        return self

    def all_datasets(self) -> list[AgentDatasetResource]:
        return ([self.dataset] if self.dataset is not None else []) + self.datasets

    def all_document_ids(self) -> list[UUID]:
        return ([self.document_id] if self.document_id is not None else []) + self.document_ids

    @property
    def is_legacy_grades_demo(self) -> bool:
        return (
            self.dataset is not None
            and self.document_id is not None
            and not self.datasets
            and not self.document_ids
            and not self.workflow_ids
        )

    @property
    def is_north_star_sales_demo(self) -> bool:
        return (
            self.dataset is None
            and self.document_id is None
            and len(self.datasets) == 3
            and len(self.document_ids) == 1
            and not self.workflow_ids
        )
