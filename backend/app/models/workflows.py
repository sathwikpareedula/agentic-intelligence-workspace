"""Versioned deterministic workflow recipe contracts."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.agent.models import ToolObservation


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class WorkflowStep(StrictModel):
    tool: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any]
    expected_columns: list[str] | None = None


class WorkflowCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    steps: list[WorkflowStep] = Field(min_length=1, max_length=50)
    source_task_id: UUID | None = None


class Workflow(WorkflowCreate):
    workflow_id: UUID = Field(default_factory=uuid4)
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkflowRerunRequest(StrictModel):
    step_overrides: dict[int, dict[str, Any]] = Field(default_factory=dict)


class WorkflowRun(StrictModel):
    workflow_id: UUID
    version: int
    status: str
    observations: list[ToolObservation]
    failed_step: int | None = None
    error: str | None = None
