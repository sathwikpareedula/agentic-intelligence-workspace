"""Typed contracts for deterministic analytical plans and facts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.datasets import DatasetProvenance
from app.models.sources import PostgresSourceConfig

Scalar = str | int | float | bool | None
AnalysisType = Literal[
    "metrics",
    "percent_change",
    "growth_rate",
    "rolling_mean",
    "rank",
    "target_variance",
    "correlation",
    "distribution",
    "group_compare",
]
MetricName = Literal[
    "count",
    "distinct_count",
    "sum",
    "mean",
    "median",
    "min",
    "max",
    "variance",
    "std",
    "percentile",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AnalyticsFilter(StrictModel):
    column: str = Field(min_length=1, max_length=200)
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "is_null", "not_null"]
    value: Scalar | list[Scalar] = None


class MetricSpec(StrictModel):
    name: MetricName
    column: str | None = Field(default=None, max_length=200)
    percentile: float | None = Field(default=None, ge=0, le=100)
    alias: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_metric(self) -> "MetricSpec":
        if self.name == "count":
            return self
        if not self.column:
            raise ValueError(f"Metric '{self.name}' requires a column.")
        if self.name == "percentile" and self.percentile is None:
            raise ValueError("percentile metrics require a percentile between 0 and 100.")
        if self.name != "percentile" and self.percentile is not None:
            raise ValueError("percentile is only valid for percentile metrics.")
        return self


class AnalyticsPlan(StrictModel):
    analysis: AnalysisType = "metrics"
    filters: list[AnalyticsFilter] = Field(default_factory=list, max_length=20)
    group_by: list[str] = Field(default_factory=list, max_length=8)
    metrics: list[MetricSpec] = Field(default_factory=list, max_length=12)
    value_column: str | None = Field(default=None, max_length=200)
    second_column: str | None = Field(default=None, max_length=200)
    order_column: str | None = Field(default=None, max_length=200)
    contributor_column: str | None = Field(default=None, max_length=200)
    window: int | None = Field(default=None, ge=2, le=365)
    rank_method: Literal["dense", "min", "max"] = "dense"
    ascending: bool = False
    limit: int = Field(default=100, ge=1, le=10_000)
    nulls: Literal["exclude", "fail"] = "exclude"
    expected_columns: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_plan(self) -> "AnalyticsPlan":
        if self.analysis == "metrics" and not self.metrics:
            self.metrics = [MetricSpec(name="count")]
        if self.analysis in {"percent_change", "growth_rate", "rolling_mean", "rank", "target_variance", "correlation", "distribution", "group_compare"}:
            if not self.value_column:
                raise ValueError(f"Analysis '{self.analysis}' requires value_column.")
        if self.analysis in {"target_variance", "correlation"} and not self.second_column:
            raise ValueError(f"Analysis '{self.analysis}' requires second_column.")
        if self.analysis in {"percent_change", "growth_rate", "rolling_mean"} and not self.order_column:
            raise ValueError(f"Analysis '{self.analysis}' requires order_column.")
        if self.analysis == "rolling_mean" and self.window is None:
            raise ValueError("rolling_mean requires window.")
        if self.analysis == "group_compare" and not self.group_by:
            raise ValueError("group_compare requires group_by.")
        return self


class NumericFact(StrictModel):
    key: str
    metric: str
    value: float | None = None
    label: str
    dataset: str
    calculation: str
    row_count: int
    grouping: dict[str, str] = Field(default_factory=dict)
    unit: str | None = None


class AnalyticsResult(StrictModel):
    status: Literal["completed"]
    plan: AnalyticsPlan
    facts: list[NumericFact]
    verification_facts: dict[str, float]
    columns: list[str]
    rows: list[dict[str, Scalar]]
    row_count: int
    input_row_count: int
    warnings: list[str] = Field(default_factory=list)
    provenance: DatasetProvenance | None = None
    explanation: str


class AnalyticsExecuteRequest(StrictModel):
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1)
    sheet: str | None = None
    plan: AnalyticsPlan


class AnalyticsSqlRequest(StrictModel):
    source: PostgresSourceConfig
    select_sql: str = Field(min_length=12, max_length=4000)
    max_rows: int | None = Field(default=None, ge=1, le=100_000)
