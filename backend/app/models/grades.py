"""Contracts for the deterministic weighted-grade calculation."""

import base64
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.retrieval import SourceReference


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PolicyEvidence(StrictModel):
    text: str = Field(min_length=1, max_length=20000)
    source: SourceReference


class RequiredFinalInput(StrictModel):
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1)
    sheet: str | None = None
    evidence: list[PolicyEvidence] = Field(min_length=1, max_length=20)
    target_letter: str = Field(default="A", pattern=r"^[A-Za-z][+-]?$")

    def content(self) -> bytes:
        try:
            return base64.b64decode(self.content_base64, validate=True)
        except ValueError as exc:
            raise ValueError("content_base64 is not valid base64.") from exc


class RequiredFinalResult(StrictModel):
    status: Literal["required", "impossible", "already_guaranteed", "insufficient_evidence", "conflicting_evidence"]
    target_letter: str
    target_percentage: float | None = None
    final_weight_percentage: float | None = None
    completed_contribution: float | None = None
    required_final_percentage: float | None = None
    message: str
    citations: list[SourceReference] = Field(default_factory=list)
