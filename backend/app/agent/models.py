"""Typed contracts for model decisions, tool observations, and execution traces."""

from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


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


ModelDecision = Annotated[ToolCall | Complete, Field(discriminator="type")]


class ToolObservation(StrictModel):
    success: bool
    summary: str
    result: dict[str, Any] | None = None
    error_code: str | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


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


class AgentExecution(StrictModel):
    task_id: UUID = Field(default_factory=uuid4)
    goal: str
    status: Literal["completed", "failed", "iteration_limit"]
    answer: str | None = None
    trace: list[TraceStep]
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime
    failure_reason: str | None = None
    verification: "VerificationReport | None" = None


class VerificationFinding(StrictModel):
    status: Literal["verified", "unsupported", "conflicting", "insufficient_evidence", "failed"]
    claim: str
    explanation: str


class VerificationReport(StrictModel):
    status: Literal["verified", "unsupported", "conflicting", "insufficient_evidence", "failed"]
    findings: list[VerificationFinding] = Field(default_factory=list)


class AgentTaskRequest(StrictModel):
    goal: str = Field(min_length=1, max_length=10000)
    max_iterations: int = Field(default=8, ge=1, le=25)
