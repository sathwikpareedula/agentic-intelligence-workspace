"""Typed contracts for deterministic dataset transformations."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Scalar = str | int | float | bool | None


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SelectColumns(StrictModel):
    type: Literal["select"]
    columns: list[str]


class FilterRows(StrictModel):
    type: Literal["filter"]
    column: str
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "contains", "in", "is_null", "not_null"]
    value: Scalar | list[Scalar] = None


class SortKey(StrictModel):
    column: str
    ascending: bool = True


class SortRows(StrictModel):
    type: Literal["sort"]
    keys: list[SortKey]


class RenameColumns(StrictModel):
    type: Literal["rename"]
    mapping: dict[str, str]


class DropDuplicates(StrictModel):
    type: Literal["drop_duplicates"]
    columns: list[str] | None = None
    keep: Literal["first", "last"] = "first"


class HandleMissing(StrictModel):
    type: Literal["missing"]
    action: Literal["fill", "drop"]
    columns: list[str] | None = None
    value: Scalar = None

    @model_validator(mode="after")
    def validate_fill_value(self) -> "HandleMissing":
        if self.action == "fill" and self.value is None:
            raise ValueError("A non-null value is required when filling missing values.")
        return self


class DeriveColumn(StrictModel):
    type: Literal["derive"]
    new_column: str
    left_column: str
    operator: Literal["add", "subtract", "multiply", "divide", "ratio", "percentage"]
    right_column: str | None = None
    constant: float | None = None

    @model_validator(mode="after")
    def validate_operand(self) -> "DeriveColumn":
        if (self.right_column is None) == (self.constant is None):
            raise ValueError("Provide exactly one of right_column or constant.")
        return self


class Aggregation(StrictModel):
    column: str
    function: Literal["count", "sum", "mean", "median", "min", "max"]
    alias: str | None = None


class GroupAggregate(StrictModel):
    type: Literal["group"]
    group_by: list[str]
    aggregations: list[Aggregation]


Transformation = Annotated[
    SelectColumns | FilterRows | SortRows | RenameColumns | DropDuplicates | HandleMissing | DeriveColumn | GroupAggregate,
    Field(discriminator="type"),
]


class TransformRequest(StrictModel):
    operations: list[Transformation] = Field(default_factory=list)


class JoinSpec(StrictModel):
    left_on: list[str]
    right_on: list[str]
    how: Literal["inner", "left", "right", "outer"] = "inner"


class JoinWorkflowRequest(StrictModel):
    left_operations: list[Transformation] = Field(default_factory=list)
    right_operations: list[Transformation] = Field(default_factory=list)
    join: JoinSpec
    operations: list[Transformation] = Field(default_factory=list)


class DatasetResult(StrictModel):
    row_count: int
    column_count: int
    columns: list[str]
    rows: list[dict[str, Scalar]]


class JoinDiagnostics(StrictModel):
    left_input_rows: int
    right_input_rows: int
    output_rows: int
    matched_output_rows: int
    left_unmatched_rows: int
    right_unmatched_rows: int
    left_keys: list[str]
    right_keys: list[str]
    join_type: Literal["inner", "left", "right", "outer"]
    row_multiplication_occurred: bool
    many_to_many_detected: bool
    warning: str | None


class JoinResult(StrictModel):
    result: DatasetResult
    diagnostics: JoinDiagnostics


class ExportRequest(TransformRequest):
    format: Literal["csv", "xlsx"]


class JoinExportRequest(JoinWorkflowRequest):
    format: Literal["csv", "xlsx"]
