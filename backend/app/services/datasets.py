"""Deterministic structured-data ingestion, inspection, and profiling."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pandas as pd
from pandas.api.types import is_numeric_dtype

from app.models.datasets import (
    CategoricalProfile,
    ColumnInspection,
    DatasetInspection,
    DatasetProfile,
    NumericProfile,
    TopValue,
)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
SUPPORTED_EXTENSIONS = {".csv": "csv", ".xlsx": "xlsx"}
TOP_VALUES_LIMIT = 5


class DatasetError(Exception):
    """Base error for invalid or unreadable datasets."""


class UnsupportedFileTypeError(DatasetError):
    """Raised when an upload does not have a supported extension."""


class DatasetTooLargeError(DatasetError):
    """Raised when an upload exceeds the in-memory processing limit."""


class DatasetReadError(DatasetError):
    """Raised when a supported file cannot be parsed."""


@dataclass(frozen=True)
class LoadedDataset:
    filename: str
    file_type: str
    selected_sheet: str | None
    frame: pd.DataFrame


def load_dataset(filename: str, content: bytes, sheet: str | None = None) -> LoadedDataset:
    """Parse a supported dataset from in-memory bytes without persisting it."""

    extension = Path(filename).suffix.lower()
    file_type = SUPPORTED_EXTENSIONS.get(extension)
    if file_type is None:
        raise UnsupportedFileTypeError("Unsupported file type. Upload a .csv or .xlsx file.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise DatasetTooLargeError(f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB limit.")
    if not content:
        raise DatasetReadError("The uploaded file is empty.")

    try:
        if file_type == "csv":
            if sheet is not None:
                raise DatasetReadError("Sheet selection is only supported for .xlsx files.")
            frame = pd.read_csv(BytesIO(content), encoding="utf-8-sig", on_bad_lines="error")
            selected_sheet = None
        else:
            # Pandas opens .xlsx workbooks through openpyxl in read-only, data-only mode.
            excel = pd.ExcelFile(BytesIO(content), engine="openpyxl")
            if not excel.sheet_names:
                raise DatasetReadError("The workbook contains no readable sheets.")
            selected_sheet = sheet or excel.sheet_names[0]
            if selected_sheet not in excel.sheet_names:
                available = ", ".join(excel.sheet_names)
                raise DatasetReadError(f"Sheet '{selected_sheet}' was not found. Available sheets: {available}.")
            frame = pd.read_excel(excel, sheet_name=selected_sheet)
    except DatasetError:
        raise
    except (ValueError, TypeError, OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise DatasetReadError(f"Could not read {file_type.upper()} dataset: {exc}") from exc
    except Exception as exc:
        raise DatasetReadError(f"Could not read {file_type.upper()} dataset.") from exc

    return LoadedDataset(filename=Path(filename).name, file_type=file_type, selected_sheet=selected_sheet, frame=frame)


def inspect_dataset(dataset: LoadedDataset) -> DatasetInspection:
    frame = dataset.frame
    row_count = len(frame)
    names = [str(column) for column in frame.columns]
    details = []
    for position, name in enumerate(names):
        series = frame.iloc[:, position]
        missing_count = int(series.isna().sum())
        missing_percentage = round((missing_count / row_count * 100), 2) if row_count else 0.0
        details.append(
            ColumnInspection(
                name=name,
                data_type=str(series.dtype),
                missing_count=missing_count,
                missing_percentage=missing_percentage,
            )
        )

    return DatasetInspection(
        filename=dataset.filename,
        file_type=dataset.file_type,
        selected_sheet=dataset.selected_sheet,
        row_count=row_count,
        column_count=len(frame.columns),
        columns=names,
        column_details=details,
        duplicate_row_count=int(frame.duplicated().sum()),
    )


def profile_dataset(dataset: LoadedDataset) -> DatasetProfile:
    inspection = inspect_dataset(dataset)
    profiles: list[NumericProfile | CategoricalProfile] = []

    for position, name in enumerate(inspection.columns):
        series = dataset.frame.iloc[:, position]
        missing_count = int(series.isna().sum())
        non_null = series.dropna()
        if is_numeric_dtype(series.dtype) and not pd.api.types.is_bool_dtype(series.dtype):
            profiles.append(
                NumericProfile(
                    name=name,
                    count=int(non_null.count()),
                    missing_count=missing_count,
                    mean=_finite_float(non_null.mean()) if not non_null.empty else None,
                    minimum=_finite_float(non_null.min()) if not non_null.empty else None,
                    maximum=_finite_float(non_null.max()) if not non_null.empty else None,
                    median=_finite_float(non_null.median()) if not non_null.empty else None,
                )
            )
        else:
            frequencies = non_null.value_counts(dropna=True).head(TOP_VALUES_LIMIT)
            profiles.append(
                CategoricalProfile(
                    name=name,
                    count=int(non_null.count()),
                    missing_count=missing_count,
                    unique_count=int(non_null.nunique(dropna=True)),
                    top_values=[TopValue(value=str(value), count=int(count)) for value, count in frequencies.items()],
                )
            )

    return DatasetProfile(inspection=inspection, columns=profiles)


def _finite_float(value: object) -> float | None:
    number = float(value)
    return number if pd.notna(number) else None
