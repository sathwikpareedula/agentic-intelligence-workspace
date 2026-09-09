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

    @model_validator(mode="after")
    def validate_value(self) -> "AnalyticsFilter":
        if self.operator in {"is_null", "not_null"}:
            if self.value is not None:
                raise ValueError(f"Operator '{self.operator}' does not accept a value.")
            return self
        if self.operator in {"in", "not_in"}:
            if not isinstance(self.value, list) or not self.value:
                raise ValueError(f"Operator '{self.operator}' requires a non-empty list value.")
            if len(self.value) > 1_000:
                raise ValueError("Filter lists may contain at most 1000 values.")
            return self
        if isinstance(self.value, list) or self.value is None:
            raise ValueError(f"Operator '{self.operator}' requires one non-null scalar value.")
        return self


class MetricSpec(StrictModel):
    name: MetricName
    column: str | None = Field(default=None, max_length=200)
    percentile: float | None = Field(default=None, ge=0, le=100)
    alias: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_metric(self) -> "MetricSpec":
        if self.name == "count":
            if self.column is not None or self.percentile is not None:
                raise ValueError("count does not accept a column or percentile.")
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
        if len(self.group_by) != len(set(self.group_by)):
            raise ValueError("group_by columns must be unique.")
        if len(self.expected_columns) != len(set(self.expected_columns)):
            raise ValueError("expected_columns must not contain duplicate names.")
        if self.analysis == "metrics" and not self.metrics:
            self.metrics = [MetricSpec(name="count")]
        if self.analysis == "metrics" and self.value_column is not None:
            raise ValueError("value_column is not used for metrics; specify columns on each metric.")
        if self.analysis != "metrics" and self.metrics:
            raise ValueError("metrics are only accepted when analysis='metrics'.")
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
        if self.analysis == "target_variance" and not self.group_by:
            raise ValueError("target_variance requires group_by.")
        if self.group_by and self.analysis not in {"metrics", "group_compare", "rolling_mean", "target_variance"}:
            raise ValueError(f"Analysis '{self.analysis}' does not support group_by.")
        if self.window is not None and self.analysis != "rolling_mean":
            raise ValueError("window is only valid for rolling_mean.")
        if self.second_column is not None and self.analysis not in {"target_variance", "correlation"}:
            raise ValueError("second_column is only valid for target_variance or correlation.")
        if self.order_column is not None and self.analysis not in {"percent_change", "growth_rate", "rolling_mean"}:
            raise ValueError("order_column is only valid for ordered analyses.")
        if self.contributor_column is not None and self.analysis != "target_variance":
            raise ValueError("contributor_column is only valid for target_variance.")
        return self


class NumericFact(StrictModel):
    key: str
    metric: str
    value: float | None = None
    label: str
    dataset: str
    calculation: str
    row_count: int
    grouping: dict[str, Scalar] = Field(default_factory=dict)
    unit: str | None = None


class VisualizationSpec(StrictModel):
    kind: Literal["metric", "bar", "line", "table"]
    title: str = Field(min_length=1, max_length=200)
    x_field: str | None = Field(default=None, max_length=200)
    y_fields: list[str] = Field(default_factory=list, max_length=6)
    rationale: str = Field(min_length=1, max_length=500)
    max_points: int = Field(ge=1, le=100)


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
    visualization: VisualizationSpec


class AnalyticsExecuteRequest(StrictModel):
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1)
    sheet: str | None = None
    plan: AnalyticsPlan


class AnalyticsSqlRequest(StrictModel):
    source: PostgresSourceConfig
    select_sql: str = Field(min_length=12, max_length=4000)
    max_rows: int | None = Field(default=None, ge=1, le=100_000)
