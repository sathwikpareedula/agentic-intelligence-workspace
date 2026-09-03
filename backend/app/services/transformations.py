"""Validated deterministic dataframe transformations and joins."""

from dataclasses import dataclass

import pandas as pd
from pandas.api.types import is_numeric_dtype

from app.models.transformations import (
    DatasetResult,
    DeriveColumn,
    DropDuplicates,
    FilterRows,
    GroupAggregate,
    HandleMissing,
    JoinDiagnostics,
    JoinSpec,
    RenameColumns,
    SelectColumns,
    SortRows,
    Transformation,
)


class TransformationError(Exception):
    """Raised when a requested deterministic operation is invalid."""


@dataclass(frozen=True)
class JoinedDataset:
    frame: pd.DataFrame
    diagnostics: JoinDiagnostics


def apply_transformations(frame: pd.DataFrame, operations: list[Transformation]) -> pd.DataFrame:
    result = frame.copy()
    for operation in operations:
        if isinstance(operation, SelectColumns):
            _require_columns(result, operation.columns)
            result = result.loc[:, operation.columns]
        elif isinstance(operation, FilterRows):
            result = _filter_rows(result, operation)
        elif isinstance(operation, SortRows):
            if not operation.keys:
                raise TransformationError("Sort requires at least one key.")
            columns = [key.column for key in operation.keys]
            _require_columns(result, columns)
            result = result.sort_values(columns, ascending=[key.ascending for key in operation.keys], kind="stable")
        elif isinstance(operation, RenameColumns):
            result = _rename_columns(result, operation)
        elif isinstance(operation, DropDuplicates):
            if operation.columns is not None:
                _require_columns(result, operation.columns)
            result = result.drop_duplicates(subset=operation.columns, keep=operation.keep)
        elif isinstance(operation, HandleMissing):
            result = _handle_missing(result, operation)
        elif isinstance(operation, DeriveColumn):
            result = _derive_column(result, operation)
        elif isinstance(operation, GroupAggregate):
            result = _group_aggregate(result, operation)
        else:
            raise TransformationError("Unsupported transformation operation.")
    return result.reset_index(drop=True)


def join_datasets(left: pd.DataFrame, right: pd.DataFrame, spec: JoinSpec) -> JoinedDataset:
    if not spec.left_on or not spec.right_on:
        raise TransformationError("Join keys cannot be empty.")
    if len(spec.left_on) != len(spec.right_on):
        raise TransformationError("Left and right joins require the same number of keys.")
    _require_columns(left, spec.left_on, "left dataset")
    _require_columns(right, spec.right_on, "right dataset")

    left_work = left.copy()
    right_work = right.copy()
    left_marker = _internal_name(left_work, right_work, "left_row_id")
    right_marker = _internal_name(left_work, right_work, "right_row_id")
    merge_marker = _internal_name(left_work, right_work, "merge_state")
    left_work[left_marker] = range(len(left_work))
    right_work[right_marker] = range(len(right_work))

    try:
        merged = left_work.merge(
            right_work,
            how=spec.how,
            left_on=spec.left_on,
            right_on=spec.right_on,
            suffixes=("_left", "_right"),
            indicator=merge_marker,
            sort=False,
        )
    except (ValueError, TypeError, pd.errors.MergeError) as exc:
        raise TransformationError(f"Join could not be completed: {exc}") from exc

    matched = merged[merge_marker] == "both"
    matched_output_rows = int(matched.sum())
    matched_left_rows = int(merged.loc[matched, left_marker].nunique())
    matched_right_rows = int(merged.loc[matched, right_marker].nunique())
    left_unmatched_rows = len(left) - matched_left_rows
    right_unmatched_rows = len(right) - matched_right_rows
    row_multiplication = matched_output_rows > matched_left_rows or matched_output_rows > matched_right_rows
    many_to_many = _has_many_to_many_keys(left, right, spec)
    warning = None
    if many_to_many:
        warning = "Many-to-many join keys produced suspicious row multiplication."
    elif row_multiplication:
        warning = "Repeated join keys caused output row multiplication."

    diagnostics = JoinDiagnostics(
        left_input_rows=len(left),
        right_input_rows=len(right),
        output_rows=len(merged),
        matched_output_rows=matched_output_rows,
        left_unmatched_rows=left_unmatched_rows,
        right_unmatched_rows=right_unmatched_rows,
        left_keys=spec.left_on,
        right_keys=spec.right_on,
        join_type=spec.how,
        row_multiplication_occurred=row_multiplication,
        many_to_many_detected=many_to_many,
        warning=warning,
    )
    return JoinedDataset(
        frame=merged.drop(columns=[left_marker, right_marker, merge_marker]),
        diagnostics=diagnostics,
    )


def dataframe_result(frame: pd.DataFrame) -> DatasetResult:
    safe = frame.astype(object).where(pd.notna(frame), None)
    rows = []
    for record in safe.to_dict(orient="records"):
        rows.append({str(key): _json_scalar(value) for key, value in record.items()})
    return DatasetResult(row_count=len(frame), column_count=len(frame.columns), columns=[str(c) for c in frame.columns], rows=rows)


def _filter_rows(frame: pd.DataFrame, operation: FilterRows) -> pd.DataFrame:
    _require_columns(frame, [operation.column])
    series = frame[operation.column]
    if operation.operator == "is_null":
        mask = series.isna()
    elif operation.operator == "not_null":
        mask = series.notna()
    elif operation.operator == "contains":
        if not isinstance(operation.value, str):
            raise TransformationError("The contains filter requires a string value.")
        mask = series.astype("string").str.contains(operation.value, regex=False, na=False)
    elif operation.operator == "in":
        if not isinstance(operation.value, list):
            raise TransformationError("The in filter requires a list value.")
        mask = series.isin(operation.value)
    else:
        if isinstance(operation.value, list) or operation.value is None:
            raise TransformationError(f"The {operation.operator} filter requires a scalar value.")
        try:
            comparisons = {
                "eq": lambda: series == operation.value,
                "ne": lambda: series != operation.value,
                "gt": lambda: series > operation.value,
                "gte": lambda: series >= operation.value,
                "lt": lambda: series < operation.value,
                "lte": lambda: series <= operation.value,
            }
            mask = comparisons[operation.operator]()
        except (TypeError, ValueError) as exc:
            raise TransformationError(f"Filter is incompatible with column '{operation.column}'.") from exc
    return frame.loc[mask]


def _rename_columns(frame: pd.DataFrame, operation: RenameColumns) -> pd.DataFrame:
    _require_columns(frame, list(operation.mapping))
    if any(not name for name in operation.mapping.values()):
        raise TransformationError("Renamed columns cannot be empty.")
    resulting = [operation.mapping.get(str(column), str(column)) for column in frame.columns]
    if len(resulting) != len(set(resulting)):
        raise TransformationError("Rename would create duplicate column names.")
    return frame.rename(columns=operation.mapping)


def _handle_missing(frame: pd.DataFrame, operation: HandleMissing) -> pd.DataFrame:
    columns = operation.columns or [str(column) for column in frame.columns]
    _require_columns(frame, columns)
    if operation.action == "drop":
        return frame.dropna(subset=columns)
    result = frame.copy()
    try:
        result.loc[:, columns] = result.loc[:, columns].fillna(operation.value)
    except (TypeError, ValueError) as exc:
        raise TransformationError("Fill value is incompatible with one or more selected columns.") from exc
    return result


def _derive_column(frame: pd.DataFrame, operation: DeriveColumn) -> pd.DataFrame:
    if not operation.new_column:
        raise TransformationError("Derived column name cannot be empty.")
    if operation.new_column in frame.columns:
        raise TransformationError(f"Derived column '{operation.new_column}' already exists.")
    required = [operation.left_column] + ([operation.right_column] if operation.right_column else [])
    _require_columns(frame, required)
    left = frame[operation.left_column]
    if not is_numeric_dtype(left):
        raise TransformationError(f"Derived operation requires numeric column '{operation.left_column}'.")
    right = operation.constant if operation.constant is not None else frame[operation.right_column]  # type: ignore[index]
    if isinstance(right, pd.Series) and not is_numeric_dtype(right):
        raise TransformationError(f"Derived operation requires numeric column '{operation.right_column}'.")
    if operation.operator in {"divide", "ratio", "percentage"}:
        zero = right == 0
        if bool(zero.any()) if isinstance(zero, pd.Series) else bool(zero):
            raise TransformationError("Division by zero is not allowed.")
    calculations = {
        "add": lambda: left + right,
        "subtract": lambda: left - right,
        "multiply": lambda: left * right,
        "divide": lambda: left / right,
        "ratio": lambda: left / right,
        "percentage": lambda: left / right * 100,
    }
    result = frame.copy()
    result[operation.new_column] = calculations[operation.operator]()
    return result


def _group_aggregate(frame: pd.DataFrame, operation: GroupAggregate) -> pd.DataFrame:
    if not operation.group_by or not operation.aggregations:
        raise TransformationError("Grouping requires keys and at least one aggregation.")
    _require_columns(frame, operation.group_by)
    output_names: set[str] = set(operation.group_by)
    named_aggregations = {}
    for aggregation in operation.aggregations:
        _require_columns(frame, [aggregation.column])
        if aggregation.function in {"sum", "mean", "median"} and not is_numeric_dtype(frame[aggregation.column]):
            raise TransformationError(f"Aggregation '{aggregation.function}' requires numeric column '{aggregation.column}'.")
        output = aggregation.alias or f"{aggregation.column}_{aggregation.function}"
        if output in output_names:
            raise TransformationError(f"Duplicate aggregation output column '{output}'.")
        output_names.add(output)
        named_aggregations[output] = pd.NamedAgg(column=aggregation.column, aggfunc=aggregation.function)
    return frame.groupby(operation.group_by, dropna=False, sort=False).agg(**named_aggregations).reset_index()


def _require_columns(frame: pd.DataFrame, columns: list[str], label: str = "dataset") -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise TransformationError(f"Unknown column(s) in {label}: {', '.join(missing)}.")


def _has_many_to_many_keys(left: pd.DataFrame, right: pd.DataFrame, spec: JoinSpec) -> bool:
    left_counts = left.groupby(spec.left_on, dropna=False).size()
    right_counts = right.groupby(spec.right_on, dropna=False).size()
    left_repeated = set(left_counts[left_counts > 1].index.tolist())
    right_repeated = set(right_counts[right_counts > 1].index.tolist())
    return bool(left_repeated & right_repeated)


def _internal_name(left: pd.DataFrame, right: pd.DataFrame, stem: str) -> str:
    candidate = f"__aiw_{stem}__"
    while candidate in left.columns or candidate in right.columns:
        candidate = f"_{candidate}"
    return candidate


def _json_scalar(value: object):
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
