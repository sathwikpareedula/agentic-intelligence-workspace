"""Deterministic structured-data ingestion, inspection, and profiling."""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
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
from app.models.datasets import DatasetProvenance
from app.services.json_adapter import JsonAdapterError, frame_from_json
from app.services.workbook_safety import (
    WorkbookArchiveError,
    WorkbookArchiveTooLargeError,
    validate_workbook_archive,
)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_DATASET_ROWS = 100_000
MAX_DATASET_COLUMNS = 200
MAX_PARQUET_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
SUPPORTED_EXTENSIONS = {".csv": "csv", ".xlsx": "xlsx", ".json": "json", ".parquet": "parquet", ".pq": "parquet"}
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
    provenance: DatasetProvenance | None = None


def load_dataset(
    filename: str,
    content: bytes,
    sheet: str | None = None,
    records_key: str | None = None,
) -> LoadedDataset:
    """Parse a supported dataset from in-memory bytes without persisting it."""

    extension = Path(filename).suffix.lower()
    file_type = SUPPORTED_EXTENSIONS.get(extension)
    if file_type is None:
        raise UnsupportedFileTypeError("Unsupported file type. Upload a .csv, .xlsx, .json, or .parquet file.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise DatasetTooLargeError(f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB limit.")
    if not content:
        raise DatasetReadError("The uploaded file is empty.")
    if sheet is not None and file_type != "xlsx":
        raise DatasetReadError("Sheet selection is only supported for .xlsx files.")
    if records_key and file_type != "json":
        raise DatasetReadError("records_key is only supported for JSON datasets.")

    try:
        if file_type == "csv":
            header = pd.read_csv(
                BytesIO(content), encoding="utf-8-sig", on_bad_lines="error", nrows=0
            )
            _validate_frame_width(header)
            frame = pd.read_csv(BytesIO(content), encoding="utf-8-sig", on_bad_lines="error")
            selected_sheet = None
        elif file_type == "xlsx":
            try:
                validate_workbook_archive(content)
            except WorkbookArchiveTooLargeError as exc:
                raise DatasetTooLargeError(str(exc)) from exc
            except WorkbookArchiveError as exc:
                raise DatasetReadError(f"Could not read XLSX dataset: {exc}") from exc
            excel = pd.ExcelFile(BytesIO(content), engine="openpyxl")
            if not excel.sheet_names:
                raise DatasetReadError("The workbook contains no readable sheets.")
            selected_sheet = sheet or excel.sheet_names[0]
            if selected_sheet not in excel.sheet_names:
                available = ", ".join(excel.sheet_names)
                raise DatasetReadError(f"Sheet '{selected_sheet}' was not found. Available sheets: {available}.")
            header = pd.read_excel(excel, sheet_name=selected_sheet, nrows=0)
            _validate_frame_width(header)
            frame = pd.read_excel(excel, sheet_name=selected_sheet)
        elif file_type == "json":
            frame = frame_from_json(content, records_key)
            selected_sheet = records_key
        else:
            frame = _read_parquet(content)
            selected_sheet = None
    except DatasetError:
        raise
    except JsonAdapterError as exc:
        raise DatasetReadError(str(exc)) from exc
    except (ValueError, TypeError, OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise DatasetReadError(f"Could not read {file_type.upper()} dataset: {exc}") from exc
    except Exception as exc:
        raise DatasetReadError(f"Could not read {file_type.upper()} dataset.") from exc

    _validate_frame_bounds(frame)
    return LoadedDataset(
        filename=Path(filename).name,
        file_type=file_type,
        selected_sheet=selected_sheet,
        frame=frame,
        provenance=_upload_provenance(Path(filename).name, file_type, len(frame), content),
    )


def loaded_from_frame(
    filename: str,
    file_type: str,
    frame: pd.DataFrame,
    provenance: DatasetProvenance,
    selected_sheet: str | None = None,
) -> LoadedDataset:
    _validate_frame_bounds(frame)
    return LoadedDataset(
        filename=Path(filename).name,
        file_type=file_type,
        selected_sheet=selected_sheet,
        frame=frame,
        provenance=provenance,
    )


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
        file_type=dataset.file_type,  # type: ignore[arg-type]
        selected_sheet=dataset.selected_sheet,
        row_count=row_count,
        column_count=len(frame.columns),
        columns=names,
        column_details=details,
        duplicate_row_count=int(frame.duplicated().sum()),
        provenance=dataset.provenance,
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


def dataset_payload(dataset: LoadedDataset) -> tuple[str, str, bytes]:
    content = dataset.frame.to_csv(index=False).encode("utf-8")
    return dataset.filename.rsplit(".", 1)[0] + ".csv", "text/csv", content


def _validate_frame_width(frame: pd.DataFrame) -> None:
    if len(frame.columns) > MAX_DATASET_COLUMNS:
        raise DatasetTooLargeError(
            f"Datasets may contain at most {MAX_DATASET_COLUMNS} columns."
        )


def _validate_frame_bounds(frame: pd.DataFrame) -> None:
    if len(frame) > MAX_DATASET_ROWS:
        raise DatasetTooLargeError(f"Datasets may contain at most {MAX_DATASET_ROWS} rows.")
    _validate_frame_width(frame)


def _read_parquet(content: bytes) -> pd.DataFrame:
    import pyarrow as pa
    import pyarrow.parquet as pq

    try:
        parquet_file = pq.ParquetFile(BytesIO(content))
    except (pa.ArrowInvalid, OSError, ValueError) as exc:
        raise DatasetReadError("Could not read PARQUET dataset: the file is malformed or unsupported.") from exc
    if parquet_file.metadata is not None and parquet_file.metadata.num_rows > MAX_DATASET_ROWS:
        raise DatasetTooLargeError(f"Datasets may contain at most {MAX_DATASET_ROWS} rows.")
    if parquet_file.metadata is not None and parquet_file.metadata.num_columns > MAX_DATASET_COLUMNS:
        raise DatasetTooLargeError(f"Datasets may contain at most {MAX_DATASET_COLUMNS} columns.")
    arrow_schema = parquet_file.schema_arrow
    if len(arrow_schema.names) != len(set(arrow_schema.names)):
        raise DatasetReadError("Parquet datasets must have unique column names.")
    if any(pa.types.is_nested(field.type) for field in arrow_schema):
        raise DatasetReadError("Nested Parquet column types are not supported by the bounded table adapter.")
    if parquet_file.metadata is not None:
        uncompressed_bytes = sum(
            parquet_file.metadata.row_group(index).total_byte_size
            for index in range(parquet_file.metadata.num_row_groups)
        )
        if uncompressed_bytes > MAX_PARQUET_UNCOMPRESSED_BYTES:
            raise DatasetTooLargeError(
                f"Parquet data expands beyond the {MAX_PARQUET_UNCOMPRESSED_BYTES // (1024 * 1024)} MiB processing limit."
            )
    table = parquet_file.read()
    if table.num_rows > MAX_DATASET_ROWS:
        raise DatasetTooLargeError(f"Datasets may contain at most {MAX_DATASET_ROWS} rows.")
    if table.num_columns > MAX_DATASET_COLUMNS:
        raise DatasetTooLargeError(f"Datasets may contain at most {MAX_DATASET_COLUMNS} columns.")
    return table.to_pandas()


def _upload_provenance(filename: str, file_type: str, row_count: int, content: bytes) -> DatasetProvenance:
    digest = sha256(content).hexdigest()
    return DatasetProvenance(
        source_type="upload",
        identity=f"upload:{filename}",
        display_name=filename,
        retrieved_at=datetime.now(timezone.utc),
        config_fingerprint=digest,
        row_count=row_count,
        details={"file_type": file_type, "byte_size": len(content)},
    )


def _finite_float(value: object) -> float | None:
    number = float(value)
    return number if pd.notna(number) else None
