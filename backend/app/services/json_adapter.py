"""Deterministic JSON-to-table conversion with fail-closed ambiguity handling."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

MAX_JSON_ROWS = 100_000
MAX_JSON_COLUMNS = 200


class JsonAdapterError(Exception):
    """Raised when JSON cannot be converted into a table without guessing."""


def frame_from_json(content: bytes, records_key: str | None = None) -> pd.DataFrame:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise JsonAdapterError("JSON datasets must be valid UTF-8.") from exc
    if "\x00" in text:
        raise JsonAdapterError("JSON datasets containing null bytes are not accepted.")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise JsonAdapterError("The uploaded JSON is malformed.") from exc
    records = _select_records(payload, records_key)
    if len(records) > MAX_JSON_ROWS:
        raise JsonAdapterError(f"JSON datasets may contain at most {MAX_JSON_ROWS} records.")
    rows = [_normalize_record(item, index) for index, item in enumerate(records)]
    frame = pd.DataFrame(rows)
    if len(frame.columns) > MAX_JSON_COLUMNS:
        raise JsonAdapterError(f"JSON datasets may contain at most {MAX_JSON_COLUMNS} columns.")
    return frame


def _select_records(payload: Any, records_key: str | None) -> list[Any]:
    if isinstance(payload, list):
        if records_key:
            raise JsonAdapterError("records_key is only valid for a JSON object wrapping a record array.")
        return _require_record_list(payload, "top-level array")
    if not isinstance(payload, dict):
        raise JsonAdapterError("JSON must be an array of records or an object wrapping one record array.")
    if records_key:
        if records_key not in payload:
            raise JsonAdapterError(f"JSON object does not contain records_key '{records_key}'.")
        selected = payload[records_key]
        if not isinstance(selected, list):
            raise JsonAdapterError(f"records_key '{records_key}' must contain an array of records.")
        return _require_record_list(selected, records_key)
    candidates = [key for key, value in payload.items() if isinstance(value, list) and _looks_like_records(value)]
    if len(candidates) == 1:
        return _require_record_list(payload[candidates[0]], candidates[0])
    if len(candidates) > 1:
        names = ", ".join(sorted(candidates))
        raise JsonAdapterError(
            f"JSON object contains multiple record arrays ({names}); specify records_key instead of guessing."
        )
    raise JsonAdapterError("JSON object does not contain a clearly selected array of records.")


def _looks_like_records(value: list[Any]) -> bool:
    return bool(value) and all(isinstance(item, dict) or _is_scalar(item) for item in value)


def _require_record_list(value: list[Any], label: str) -> list[Any]:
    if not value:
        raise JsonAdapterError(f"The JSON {label} is empty.")
    dict_count = sum(isinstance(item, dict) for item in value)
    scalar_count = sum(_is_scalar(item) for item in value)
    if dict_count == len(value):
        return value
    if scalar_count == len(value):
        return [{"value": item} for item in value]
    raise JsonAdapterError(f"The JSON {label} mixes objects and scalars; the structure is ambiguous.")


def _normalize_record(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise JsonAdapterError(f"JSON record {index} is not an object.")
    row: dict[str, Any] = {}
    for key, value in item.items():
        name = str(key)
        if isinstance(value, dict):
            if any(isinstance(nested, (dict, list)) for nested in value.values()):
                raise JsonAdapterError(
                    f"JSON record {index} field '{name}' contains nested structures that cannot be normalized safely."
                )
            for nested_key, nested_value in value.items():
                _assign(row, f"{name}.{nested_key}", _scalar_or_reject(nested_value, index, f"{name}.{nested_key}"), index)
        elif isinstance(value, list):
            raise JsonAdapterError(
                f"JSON record {index} field '{name}' is an array; nested arrays are not auto-normalized."
            )
        else:
            _assign(row, name, _scalar_or_reject(value, index, name), index)
    return row


def _assign(row: dict[str, Any], name: str, value: Any, index: int) -> None:
    if name in row:
        raise JsonAdapterError(f"JSON record {index} has colliding field '{name}'.")
    row[name] = value


def _scalar_or_reject(value: Any, index: int, field: str) -> Any:
    if value is None or _is_scalar(value):
        return value
    raise JsonAdapterError(f"JSON record {index} field '{field}' is not a scalar value.")


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) or value is None
