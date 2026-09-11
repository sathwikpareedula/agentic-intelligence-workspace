"""Typed responses for deterministic dataset inspection and profiling."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ColumnInspection(BaseModel):
    name: str
    data_type: str
    missing_count: int
    missing_percentage: float


class DatasetProvenance(BaseModel):
    source_type: Literal["upload", "postgres", "rest"]
    identity: str = Field(min_length=1, max_length=500)
    display_name: str = Field(min_length=1, max_length=255)
    retrieved_at: datetime
    config_fingerprint: str = Field(min_length=64, max_length=64)
    row_count: int = Field(ge=0)
    details: dict[str, str | int | None] = Field(default_factory=dict)


class DatasetInspection(BaseModel):
    filename: str
    file_type: Literal["csv", "xlsx", "json", "parquet"]
    selected_sheet: str | None
    row_count: int
    column_count: int
    columns: list[str]
    column_details: list[ColumnInspection]
    duplicate_row_count: int
    provenance: DatasetProvenance | None = None


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
