"""In-memory tabular artifact generation."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re

import pandas as pd


@dataclass(frozen=True)
class GeneratedArtifact:
    filename: str
    format: str
    media_type: str
    row_count: int
    column_count: int
    content: bytes


def generate_artifact(frame: pd.DataFrame, source_filename: str, format: str) -> GeneratedArtifact:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(source_filename).stem).strip("_") or "dataset"
    filename = f"{stem}_result.{format}"
    safe_frame = _sanitize_spreadsheet_strings(frame)
    output = BytesIO()
    if format == "csv":
        content = safe_frame.to_csv(index=False).encode("utf-8")
        media_type = "text/csv"
    elif format == "xlsx":
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            safe_frame.to_excel(writer, sheet_name="Result", index=False)
        content = output.getvalue()
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        raise ValueError("Artifact format must be csv or xlsx.")
    return GeneratedArtifact(filename, format, media_type, len(frame), len(frame.columns), content)


def _sanitize_spreadsheet_strings(frame: pd.DataFrame) -> pd.DataFrame:
    """Prevent uploaded text from becoming a spreadsheet formula on export."""

    result = frame.copy()
    for column in result.columns:
        result[column] = result[column].map(_sanitize_cell)
    return result


def _sanitize_cell(value: object) -> object:
    if not isinstance(value, str):
        return value
    if value.lstrip().startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value
