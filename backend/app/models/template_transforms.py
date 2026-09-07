"""Typed contracts for deterministic transform-to-template workflows."""

from __future__ import annotations

import base64
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.datasets import DatasetInspection
from app.models.grades import PolicyEvidence
from app.models.transformations import JoinDiagnostics


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class FilePayload(StrictModel):
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1)
    sheet: str | None = Field(default=None, max_length=100)

    def content(self) -> bytes:
        try:
            return base64.b64decode(self.content_base64, validate=True)
        except ValueError as exc:
            raise ValueError("content_base64 is not valid base64.") from exc


class SourcePayload(FilePayload):
    role: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")


class TemplateColumn(StrictModel):
    name: str
    column_index: int = Field(ge=1)
    inferred_type: Literal["text", "number", "date", "boolean", "formula", "unknown"]
    number_format: str | None = None
    example_values: list[str | int | float | bool | None] = Field(default_factory=list, max_length=5)
    formula: str | None = None
    formula_row: int | None = Field(default=None, ge=1)


class TemplateSheet(StrictModel):
    name: str
    state: Literal["visible", "hidden", "veryHidden"]
    max_row: int = Field(ge=1)
    max_column: int = Field(ge=1)


class TemplateInspection(StrictModel):
    filename: str
    file_type: Literal["csv", "xlsx"]
    target_sheet: str | None
    header_row: int = Field(ge=1)
    headers: list[str]
    columns: list[TemplateColumn]
    sheets: list[TemplateSheet]
    formula_cell_count: int = Field(ge=0)
    has_macros: bool
    fingerprint: str


class SourceInspection(StrictModel):
    role: str
    inspection: DatasetInspection
    candidate_keys: list[list[str]]
    fingerprint: str


class FieldMapping(StrictModel):
    target_field: str
    source_role: str | None = None
    source_field: str | None = None
    mapping_type: Literal[
        "explicit", "exact", "normalized", "documented_alias", "semantic_candidate", "template_formula", "unmapped"
    ]
    confidence: float = Field(ge=0, le=1)
    evidence: str
    transformation: Literal[
        "none", "trim", "upper", "lower", "normalize_number", "normalize_currency", "normalize_date"
    ] = "none"
    status: Literal["confirmed", "proposed_high_confidence", "ambiguous", "missing", "incompatible"]

    @model_validator(mode="after")
    def validate_source_pair(self) -> "FieldMapping":
        if (self.source_role is None) != (self.source_field is None):
            raise ValueError("source_role and source_field must be provided together.")
        if self.mapping_type != "template_formula" and self.status not in {"missing", "ambiguous", "incompatible"} and self.source_field is None:
            raise ValueError("Resolved mappings require a source field.")
        return self


class ClarificationRequirement(StrictModel):
    code: Literal["ambiguous_mapping", "missing_required_field", "incompatible_type"]
    target_field: str
    candidate_options: list[str] = Field(default_factory=list)
    reason: str


class JoinRule(StrictModel):
    right_role: str
    left_on: list[str] = Field(min_length=1, max_length=8)
    right_on: list[str] = Field(min_length=1, max_length=8)
    how: Literal["inner", "left", "right", "outer"] = "left"
    block_many_to_many: bool = True
    block_row_multiplication: bool = True
    max_unmatched_left_percentage: float = Field(default=100, ge=0, le=100)


class FieldReference(StrictModel):
    source_role: str
    source_field: str
    transformation: Literal[
        "none", "trim", "upper", "lower", "normalize_number", "normalize_currency", "normalize_date"
    ] = "none"


class DerivationRule(StrictModel):
    target_field: str
    operation: Literal["add", "subtract", "multiply", "divide", "concat", "policy_multiply"]
    inputs: list[FieldReference] = Field(min_length=1, max_length=2)
    constant: float | None = None
    separator: str = " "
    policy_query: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_operands(self) -> "DerivationRule":
        if self.operation == "policy_multiply":
            if len(self.inputs) != 1 or self.constant is not None or not self.policy_query:
                raise ValueError("policy_multiply requires one input and a policy_query; its rate cannot be supplied as a constant.")
        elif self.operation == "concat":
            if self.constant is not None or self.policy_query is not None:
                raise ValueError("concat accepts only source inputs and a separator.")
        elif self.policy_query is not None:
            raise ValueError("policy_query is only valid for policy_multiply.")
        elif len(self.inputs) + (1 if self.constant is not None else 0) != 2:
            raise ValueError("Arithmetic derivations require exactly two operands.")
        return self


class TransformTemplatePlan(StrictModel):
    source_roles: list[str] = Field(min_length=1, max_length=8)
    expected_source_columns: dict[str, list[str]]
    target_filename: str
    target_sheet: str | None
    target_header_row: int = Field(ge=1)
    target_headers: list[str] = Field(min_length=1)
    template_fingerprint: str = Field(min_length=64, max_length=64)
    mappings: list[FieldMapping]
    joins: list[JoinRule] = Field(default_factory=list, max_length=7)
    derivations: list[DerivationRule] = Field(default_factory=list, max_length=50)
    required_fields: list[str]
    unique_fields: list[str] = Field(default_factory=list)


class TransformProposalRequest(StrictModel):
    target: FilePayload
    sources: list[SourcePayload] = Field(min_length=1, max_length=8)
    required_fields: list[str] | None = None
    explicit_mappings: dict[str, str] = Field(default_factory=dict)
    documented_aliases: dict[str, list[str]] = Field(default_factory=dict)
    header_row: int | None = Field(default=None, ge=1, le=100)


class TransformProposal(StrictModel):
    status: Literal["ready", "clarification_required"]
    template: TemplateInspection
    sources: list[SourceInspection]
    plan: TransformTemplatePlan
    clarifications: list[ClarificationRequirement]


class TransformExecutionRequest(StrictModel):
    target: FilePayload
    sources: list[SourcePayload] = Field(min_length=1, max_length=8)
    plan: TransformTemplatePlan
    policy_evidence: list[PolicyEvidence] = Field(default_factory=list, max_length=20)


class ValidationCheck(StrictModel):
    name: str
    passed: bool
    detail: str


class OutputValidation(StrictModel):
    status: Literal["completed", "completed_with_warnings", "failed_validation"]
    checks: list[ValidationCheck]
    errors: list[str]
    warnings: list[str]
    input_row_count: int = Field(ge=0)
    output_row_count: int = Field(ge=0)
    join_diagnostics: list[JoinDiagnostics]


class FieldProvenance(StrictModel):
    target_field: str
    source_fields: list[str]
    transformation: str
    policy_evidence_ids: list[str] = Field(default_factory=list)
    validation: Literal["passed", "warning", "failed"]


class TemplateArtifactReference(StrictModel):
    artifact_id: UUID
    filename: str
    media_type: str
    row_count: int
    column_count: int
    download_url: str


class SavedWorkflowReference(StrictModel):
    workflow_id: UUID
    name: str
    version: int
    rerun_url: str


class TransformExecutionResponse(StrictModel):
    status: Literal["completed", "completed_with_warnings", "clarification_required", "failed_validation"]
    plan: TransformTemplatePlan
    validation: OutputValidation | None = None
    provenance: list[FieldProvenance] = Field(default_factory=list)
    clarifications: list[ClarificationRequirement] = Field(default_factory=list)
    artifact: TemplateArtifactReference | None = None
    saved_workflow: SavedWorkflowReference | None = None
