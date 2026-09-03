"""Typed responses for deterministic dataset inspection and profiling."""

from typing import Literal

from pydantic import BaseModel


class ColumnInspection(BaseModel):
    name: str
    data_type: str
    missing_count: int
    missing_percentage: float


class DatasetInspection(BaseModel):
    filename: str
    file_type: Literal["csv", "xlsx"]
    selected_sheet: str | None
    row_count: int
    column_count: int
    columns: list[str]
    column_details: list[ColumnInspection]
    duplicate_row_count: int


class NumericProfile(BaseModel):
    name: str
    kind: Literal["numeric"] = "numeric"
    count: int
    missing_count: int
    mean: float | None
    minimum: float | None
    maximum: float | None
    median: float | None


class TopValue(BaseModel):
    value: str
    count: int


class CategoricalProfile(BaseModel):
    name: str
    kind: Literal["categorical"] = "categorical"
    count: int
    missing_count: int
    unique_count: int
    top_values: list[TopValue]


class DatasetProfile(BaseModel):
    inspection: DatasetInspection
    columns: list[NumericProfile | CategoricalProfile]
