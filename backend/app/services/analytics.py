"""Deterministic analytics over workspace datasets with fail-closed numeric semantics."""

from __future__ import annotations

from typing import Any

import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype

from app.models.analytics import (
    AnalyticsFilter,
    AnalyticsPlan,
    AnalyticsResult,
    AnalyticsSqlRequest,
    MetricSpec,
    NumericFact,
)
from app.models.sources import PostgresImportRequest
from app.services.datasets import LoadedDataset, inspect_dataset, load_dataset
from app.services.postgres_source import import_source, validate_select

MAX_RESULT_CELLS = 50_000


class AnalyticsError(Exception):
    """User-facing analytics validation or execution failure."""


def validate_plan(plan: AnalyticsPlan, columns: list[str] | None = None) -> AnalyticsPlan:
    AnalyticsPlan.model_validate(plan.model_dump())
    if columns is not None:
        _require_plan_columns(plan, columns)
    return plan


def execute_dataset_analytics(dataset: LoadedDataset, plan: AnalyticsPlan) -> AnalyticsResult:
    columns = [str(column) for column in dataset.frame.columns]
    if plan.expected_columns and columns != plan.expected_columns:
        raise AnalyticsError("Dataset schema does not match the analytical plan; rerun after inspecting the current columns.")
    _require_plan_columns(plan, columns)
    frame = _apply_filters(dataset.frame.copy(), plan.filters)
    if frame.empty:
        raise AnalyticsError("No rows remain after applying the requested filters.")
    if plan.nulls == "fail":
        needed = _value_columns(plan)
        if needed and frame[needed].isna().any().any():
            raise AnalyticsError("Missing values are present and the plan is configured to fail on nulls.")
    result_frame, facts, warnings, explanation = _analyze(frame, plan, dataset.filename)
    if result_frame.size > MAX_RESULT_CELLS:
        raise AnalyticsError("The analytical result exceeds the bounded result size.")
    if plan.limit:
        result_frame = result_frame.head(plan.limit)
    rows = _json_rows(result_frame)
    verification = {item.key: item.value for item in facts if item.value is not None}
    return AnalyticsResult(
        status="completed",
        plan=plan,
        facts=facts,
        verification_facts=verification,
        columns=[str(column) for column in result_frame.columns],
        rows=rows,
        row_count=len(result_frame),
        input_row_count=len(frame),
        warnings=warnings,
        provenance=dataset.provenance,
        explanation=explanation,
    )


def execute_uploaded_analytics(filename: str, content: bytes, plan: AnalyticsPlan, sheet: str | None = None) -> AnalyticsResult:
    dataset = load_dataset(filename, content, sheet)
    return execute_dataset_analytics(dataset, plan)


def execute_sql_analytics(request: AnalyticsSqlRequest) -> AnalyticsResult:
    validated = validate_select(request.select_sql)
    imported = import_source(
        PostgresImportRequest(source=request.source, select_sql=validated, max_rows=request.max_rows)
    )
    dataset = load_dataset(imported.dataset.filename, _decode(imported.dataset.content_base64))
    dataset = LoadedDataset(
        filename=dataset.filename,
        file_type=dataset.file_type,
        selected_sheet=dataset.selected_sheet,
        frame=dataset.frame,
        provenance=imported.provenance,
    )
    plan = AnalyticsPlan(analysis="metrics", metrics=[MetricSpec(name="count")], limit=min(request.max_rows or 5000, 10_000))
    result = execute_dataset_analytics(dataset, plan)
    facts = list(result.facts)
    if len(dataset.frame) == 1:
        for name in dataset.frame.columns:
            series = dataset.frame[name]
            if _is_numeric_series(series) and pd.notna(series.iloc[0]):
                key = f"sql.{name}"
                facts.append(
                    NumericFact(
                        key=key,
                        metric="sql_value",
                        value=float(series.iloc[0]),
                        label=str(name),
                        dataset=request.source.database,
                        calculation="validated read-only SELECT",
                        row_count=1,
                    )
                )
    verification = {item.key: item.value for item in facts if item.value is not None}
    return result.model_copy(
        update={
            "facts": facts,
            "verification_facts": verification,
            "explanation": "Executed one validated read-only SELECT and captured deterministic result facts.",
            "provenance": imported.provenance,
        }
    )


def inspect_for_analytics(filename: str, content: bytes, sheet: str | None = None):
    dataset = load_dataset(filename, content, sheet)
    return inspect_dataset(dataset)


def _analyze(frame: pd.DataFrame, plan: AnalyticsPlan, dataset_name: str):
    warnings: list[str] = []
    if plan.analysis == "metrics":
        table = _grouped_metrics(frame, plan)
        facts = _facts_from_metric_table(table, plan, dataset_name, len(frame))
        return table, facts, warnings, "Computed deterministic grouped or overall metrics."
    if plan.analysis == "distribution":
        return _distribution(frame, plan, dataset_name)
    if plan.analysis == "correlation":
        return _correlation(frame, plan, dataset_name)
    if plan.analysis == "rank":
        return _rank(frame, plan, dataset_name)
    if plan.analysis == "rolling_mean":
        return _rolling_mean(frame, plan, dataset_name)
    if plan.analysis in {"percent_change", "growth_rate"}:
        return _change(frame, plan, dataset_name)
    if plan.analysis == "group_compare":
        table = _grouped_metrics(
            frame,
            plan.model_copy(update={"metrics": [MetricSpec(name="count"), MetricSpec(name="mean", column=plan.value_column), MetricSpec(name="sum", column=plan.value_column)]}),
        )
        facts = _facts_from_metric_table(table, plan, dataset_name, len(frame))
        return table, facts, warnings, "Compared groups using deterministic count, mean, and sum."
    if plan.analysis == "target_variance":
        return _target_variance(frame, plan, dataset_name)
    raise AnalyticsError(f"Unsupported analysis '{plan.analysis}'.")


def _grouped_metrics(frame: pd.DataFrame, plan: AnalyticsPlan) -> pd.DataFrame:
    if not plan.group_by:
        row = {spec.alias or _metric_alias(spec): _metric_value(frame, spec) for spec in plan.metrics}
        return pd.DataFrame([row])
    grouped = frame.groupby(plan.group_by, dropna=False, sort=False)
    rows = []
    for keys, group in grouped:
        key_values = keys if isinstance(keys, tuple) else (keys,)
        row = {column: _scalar(value) for column, value in zip(plan.group_by, key_values, strict=True)}
        for spec in plan.metrics:
            row[spec.alias or _metric_alias(spec)] = _metric_value(group, spec)
        rows.append(row)
    table = pd.DataFrame(rows)
    sort_column = next((spec.alias or _metric_alias(spec) for spec in plan.metrics if spec.name != "count"), table.columns[-1])
    return table.sort_values(sort_column, ascending=plan.ascending, kind="mergesort").reset_index(drop=True)


def _metric_value(frame: pd.DataFrame, spec: MetricSpec) -> float:
    if spec.name == "count":
        return float(len(frame))
    series = _numeric_series(frame, spec.column or "")
    if spec.name == "distinct_count":
        return float(series.nunique(dropna=True))
    if spec.name == "sum":
        return float(series.sum(min_count=1)) if not series.empty else _empty_numeric()
    if spec.name == "mean":
        return _require_values(series, 1, "mean") or float(series.mean())
    if spec.name == "median":
        return _require_values(series, 1, "median") or float(series.median())
    if spec.name == "min":
        return _require_values(series, 1, "min") or float(series.min())
    if spec.name == "max":
        return _require_values(series, 1, "max") or float(series.max())
    if spec.name == "variance":
        _require_values(series, 2, "variance")
        return float(series.var(ddof=1))
    if spec.name == "std":
        _require_values(series, 2, "std")
        return float(series.std(ddof=1))
    _require_values(series, 1, "percentile")
    return float(series.quantile((spec.percentile or 0) / 100.0, interpolation="linear"))


def _distribution(frame: pd.DataFrame, plan: AnalyticsPlan, dataset_name: str):
    series = _numeric_series(frame, plan.value_column or "")
    missing = int(frame[plan.value_column].isna().sum()) if plan.value_column else 0
    row = {
        "count": float(len(series)),
        "missing_count": float(missing),
        "min": float(series.min()) if not series.empty else None,
        "max": float(series.max()) if not series.empty else None,
        "mean": float(series.mean()) if not series.empty else None,
        "median": float(series.median()) if not series.empty else None,
        "std": float(series.std(ddof=1)) if len(series) >= 2 else None,
        "p25": float(series.quantile(0.25)) if not series.empty else None,
        "p75": float(series.quantile(0.75)) if not series.empty else None,
    }
    table = pd.DataFrame([row])
    facts = [
        NumericFact(
            key=f"distribution.{name}",
            metric=name,
            value=value,
            label=name,
            dataset=dataset_name,
            calculation=f"distribution of {plan.value_column}",
            row_count=len(frame),
        )
        for name, value in row.items()
        if value is not None
    ]
    return table, facts, [], f"Summarized the distribution of {plan.value_column}."


def _correlation(frame: pd.DataFrame, plan: AnalyticsPlan, dataset_name: str):
    left = _numeric_series(frame, plan.value_column or "", dropna=False)
    right = _numeric_series(frame, plan.second_column or "", dropna=False)
    paired = pd.DataFrame({"x": left, "y": right}).dropna()
    if len(paired) < 2:
        raise AnalyticsError("Correlation requires at least two paired non-null numeric values.")
    if float(paired["x"].std(ddof=1) or 0) == 0 or float(paired["y"].std(ddof=1) or 0) == 0:
        raise AnalyticsError("Correlation is undefined when a column has zero variance.")
    value = float(paired["x"].corr(paired["y"], method="pearson"))
    table = pd.DataFrame([{"x": plan.value_column, "y": plan.second_column, "pearson": value, "paired_rows": len(paired)}])
    facts = [
        NumericFact(
            key="correlation.pearson",
            metric="correlation",
            value=value,
            label="Pearson correlation",
            dataset=dataset_name,
            calculation=f"pearson({plan.value_column}, {plan.second_column})",
            row_count=len(paired),
        )
    ]
    return table, facts, [], f"Computed Pearson correlation between {plan.value_column} and {plan.second_column}."


def _rank(frame: pd.DataFrame, plan: AnalyticsPlan, dataset_name: str):
    working = frame.copy()
    method = {"dense": "dense", "min": "min", "max": "max"}[plan.rank_method]
    working["_rank_value"] = _numeric_series(working, plan.value_column or "", dropna=False)
    working["rank"] = working["_rank_value"].rank(method=method, ascending=plan.ascending)
    working = working.drop(columns=["_rank_value"]).sort_values("rank", kind="mergesort")
    top = working.iloc[0]
    facts = [
        NumericFact(
            key="rank.top_value",
            metric="rank",
            value=_optional_float(top[plan.value_column]),
            label="top ranked value",
            dataset=dataset_name,
            calculation=f"rank({plan.value_column})",
            row_count=len(working),
        )
    ]
    return working, facts, [], f"Ranked rows by {plan.value_column}."


def _rolling_mean(frame: pd.DataFrame, plan: AnalyticsPlan, dataset_name: str):
    working = _ordered(frame, plan.order_column or "")
    if plan.group_by:
        values = []
        for _, group in working.groupby(plan.group_by, dropna=False, sort=False):
            values.append(_rolling_on_group(group, plan))
        table = pd.concat(values, ignore_index=True)
    else:
        table = _rolling_on_group(working, plan)
    last = table.dropna(subset=["rolling_mean"]).iloc[-1] if table["rolling_mean"].notna().any() else None
    facts = []
    if last is not None:
        facts.append(
            NumericFact(
                key="rolling.mean.last",
                metric="rolling_mean",
                value=float(last["rolling_mean"]),
                label="latest rolling mean",
                dataset=dataset_name,
                calculation=f"rolling_mean({plan.value_column}, window={plan.window})",
                row_count=len(table),
            )
        )
    return table, facts, [], f"Computed a {plan.window}-row rolling mean of {plan.value_column}."


def _rolling_on_group(frame: pd.DataFrame, plan: AnalyticsPlan) -> pd.DataFrame:
    working = frame.copy()
    working["rolling_mean"] = _numeric_series(working, plan.value_column or "", dropna=False).rolling(plan.window or 2, min_periods=plan.window).mean()
    return working


def _change(frame: pd.DataFrame, plan: AnalyticsPlan, dataset_name: str):
    working = _ordered(frame, plan.order_column or "")
    series = _numeric_series(working, plan.value_column or "", dropna=False)
    previous = series.shift(1)
    if (previous == 0).any():
        raise AnalyticsError("Division by zero: a previous period value is 0.")
    if previous.isna().all():
        raise AnalyticsError("Percent change requires at least two ordered values.")
    change = (series - previous) / previous
    working = working.copy()
    working["percent_change"] = change * 100.0
    working["growth_rate"] = change
    column = "percent_change" if plan.analysis == "percent_change" else "growth_rate"
    last = working.dropna(subset=[column]).iloc[-1]
    facts = [
        NumericFact(
            key=f"{plan.analysis}.last",
            metric=plan.analysis,
            value=float(last[column]),
            label=f"latest {plan.analysis.replace('_', ' ')}",
            dataset=dataset_name,
            calculation=f"{plan.analysis}({plan.value_column}) ordered by {plan.order_column}",
            row_count=int(working[column].notna().sum()),
        )
    ]
    return working, facts, [], f"Computed {plan.analysis.replace('_', ' ')} for {plan.value_column}."


def _target_variance(frame: pd.DataFrame, plan: AnalyticsPlan, dataset_name: str):
    if not plan.group_by:
        raise AnalyticsError("target_variance requires group_by.")
    grouped = frame.groupby(plan.group_by, dropna=False, sort=False)
    rows = []
    for keys, group in grouped:
        key_values = keys if isinstance(keys, tuple) else (keys,)
        grouping = {column: str(_scalar(value)) for column, value in zip(plan.group_by, key_values, strict=True)}
        actual = _metric_value(group, MetricSpec(name="sum", column=plan.value_column))
        targets = group[plan.second_column]
        unique_targets = pd.Series(targets.dropna().unique())
        if unique_targets.empty:
            raise AnalyticsError("Each group must have a target value.")
        if len(unique_targets) != 1:
            raise AnalyticsError("Target values are not unique within a group.")
        if not _is_numeric_series(unique_targets):
            raise AnalyticsError("Target values must be numeric.")
        target = float(unique_targets.iloc[0])
        variance = actual - target
        shortfall = max(target - actual, 0.0)
        rows.append({**grouping, "actual": actual, "target": target, "variance": variance, "shortfall": shortfall, "row_count": float(len(group))})
    table = pd.DataFrame(rows).sort_values("shortfall", ascending=False, kind="mergesort").reset_index(drop=True)
    worst = table.iloc[0]
    grouping = {column: str(worst[column]) for column in plan.group_by}
    facts = [
        NumericFact(
            key="target.worst_region_shortfall",
            metric="shortfall",
            value=float(worst["shortfall"]),
            label="largest shortfall",
            dataset=dataset_name,
            calculation=f"max(target - sum({plan.value_column}), 0) grouped by {', '.join(plan.group_by)}",
            row_count=int(worst["row_count"]),
            grouping=grouping,
        ),
        NumericFact(
            key="target.worst_region_actual",
            metric="sum",
            value=float(worst["actual"]),
            label="actual at largest shortfall",
            dataset=dataset_name,
            calculation=f"sum({plan.value_column})",
            row_count=int(worst["row_count"]),
            grouping=grouping,
        ),
        NumericFact(
            key="target.worst_region_target",
            metric="target",
            value=float(worst["target"]),
            label="target at largest shortfall",
            dataset=dataset_name,
            calculation=str(plan.second_column),
            row_count=int(worst["row_count"]),
            grouping=grouping,
        ),
    ]
    if plan.contributor_column:
        mask = pd.Series(True, index=frame.index)
        for column in plan.group_by:
            mask &= frame[column].astype(str) == grouping[column]
        contributors = (
            frame.loc[mask]
            .groupby(plan.contributor_column, dropna=False, sort=False)[plan.value_column]
            .apply(lambda series: _metric_value(pd.DataFrame({plan.value_column: series}), MetricSpec(name="sum", column=plan.value_column)))
            .sort_values(ascending=False, kind="mergesort")
        )
        if contributors.empty:
            raise AnalyticsError("No contributor rows were found for the largest shortfall group.")
        top_name = contributors.index[0]
        top_value = float(contributors.iloc[0])
        facts.append(
            NumericFact(
                key="target.top_contributor",
                metric="sum",
                value=top_value,
                label=str(top_name),
                dataset=dataset_name,
                calculation=f"sum({plan.value_column}) by {plan.contributor_column} within the largest shortfall group",
                row_count=int(mask.sum()),
                grouping={**grouping, plan.contributor_column: str(top_name)},
            )
        )
    explanation = (
        f"{' / '.join(str(worst[column]) for column in plan.group_by)} is furthest below target "
        f"with a shortfall of {worst['shortfall']}."
    )
    if plan.contributor_column and any(item.key == "target.top_contributor" for item in facts):
        contributor = next(item for item in facts if item.key == "target.top_contributor")
        explanation += f" {contributor.label} contributed the most with {contributor.value}."
    return table, facts, [], explanation


def _apply_filters(frame: pd.DataFrame, filters: list[AnalyticsFilter]) -> pd.DataFrame:
    working = frame
    for item in filters:
        if item.column not in working.columns:
            raise AnalyticsError(f"Filter column '{item.column}' is not in the dataset.")
        series = working[item.column]
        if item.operator == "eq":
            working = working[series == item.value]
        elif item.operator == "ne":
            working = working[series != item.value]
        elif item.operator == "gt":
            working = working[series > item.value]
        elif item.operator == "gte":
            working = working[series >= item.value]
        elif item.operator == "lt":
            working = working[series < item.value]
        elif item.operator == "lte":
            working = working[series <= item.value]
        elif item.operator == "in":
            if not isinstance(item.value, list):
                raise AnalyticsError("Operator 'in' requires a list value.")
            working = working[series.isin(item.value)]
        elif item.operator == "not_in":
            if not isinstance(item.value, list):
                raise AnalyticsError("Operator 'not_in' requires a list value.")
            working = working[~series.isin(item.value)]
        elif item.operator == "is_null":
            working = working[series.isna()]
        else:
            working = working[series.notna()]
    return working


def _require_plan_columns(plan: AnalyticsPlan, columns: list[str]) -> None:
    names = set(columns)
    referenced = list(plan.group_by)
    referenced.extend(item.column for item in plan.filters)
    referenced.extend(spec.column for spec in plan.metrics if spec.column)
    for field in (plan.value_column, plan.second_column, plan.order_column, plan.contributor_column):
        if field:
            referenced.append(field)
    missing = sorted({name for name in referenced if name not in names})
    if missing:
        raise AnalyticsError(f"Plan references unknown columns: {', '.join(missing)}.")


def _value_columns(plan: AnalyticsPlan) -> list[str]:
    names = [spec.column for spec in plan.metrics if spec.column]
    for field in (plan.value_column, plan.second_column):
        if field:
            names.append(field)
    return names


def _numeric_series(frame: pd.DataFrame, column: str, dropna: bool = True) -> pd.Series:
    if column not in frame.columns:
        raise AnalyticsError(f"Column '{column}' is not in the dataset.")
    series = frame[column]
    if not _is_numeric_series(series):
        raise AnalyticsError(f"Column '{column}' is not numeric; refusing unsafe coercion.")
    values = pd.to_numeric(series, errors="raise")
    return values.dropna() if dropna else values


def _is_numeric_series(series: pd.Series) -> bool:
    return is_numeric_dtype(series) and not is_bool_dtype(series)


def _ordered(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    if column not in frame.columns:
        raise AnalyticsError(f"Order column '{column}' is not in the dataset.")
    working = frame.copy()
    if not _is_numeric_series(working[column]):
        parsed = pd.to_datetime(working[column], errors="coerce", utc=True)
        if parsed.isna().any() and working[column].notna().any():
            raise AnalyticsError(f"Order column '{column}' could not be parsed as dates or numbers.")
        working = working.assign(**{column: parsed})
    return working.sort_values(column, kind="mergesort")


def _facts_from_metric_table(table: pd.DataFrame, plan: AnalyticsPlan, dataset_name: str, row_count: int) -> list[NumericFact]:
    facts = []
    for _, record in table.iterrows():
        grouping = {column: str(record[column]) for column in plan.group_by if column in table.columns}
        suffix = "." + "_".join(grouping.values()) if grouping else ""
        for spec in plan.metrics:
            alias = spec.alias or _metric_alias(spec)
            facts.append(
                NumericFact(
                    key=f"metric.{alias}{suffix}",
                    metric=spec.name,
                    value=_optional_float(record[alias]),
                    label=alias,
                    dataset=dataset_name,
                    calculation=_metric_alias(spec),
                    row_count=row_count,
                    grouping=grouping,
                )
            )
    return facts


def _metric_alias(spec: MetricSpec) -> str:
    if spec.name == "count":
        return "count"
    if spec.name == "percentile":
        return f"p{int(spec.percentile or 0)}_{spec.column}"
    return f"{spec.name}_{spec.column}"


def _json_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records = []
    for record in frame.to_dict(orient="records"):
        records.append({str(key): _scalar(value) for key, value in record.items()})
    return records


def _scalar(value: Any):
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) if isinstance(value, float) else int(value)
    return str(value)


def _optional_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _require_values(series: pd.Series, minimum: int, label: str) -> None:
    if len(series) < minimum:
        raise AnalyticsError(f"{label} requires at least {minimum} non-null numeric value(s).")
    return None


def _empty_numeric() -> float:
    raise AnalyticsError("The selected numeric column has no non-null values.")


def _decode(payload: str) -> bytes:
    import base64

    return base64.b64decode(payload, validate=True)
