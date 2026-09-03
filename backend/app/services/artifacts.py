"""In-memory tabular artifact generation."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pandas as pd
from openpyxl.chart import BarChart, Reference


@dataclass(frozen=True)
class GeneratedArtifact:
    filename: str
    format: str
    media_type: str
    row_count: int
    column_count: int
    content: bytes
    artifact_id: UUID
    created_at: datetime
    producing_task_id: UUID | None = None
    producing_workflow_id: UUID | None = None
    provenance: dict[str, str] | None = None


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
    return GeneratedArtifact(filename, format, media_type, len(frame), len(frame.columns), content, uuid4(), datetime.now(timezone.utc))


def generate_management_workbook(
    frame: pd.DataFrame,
    source_filename: str,
    *,
    task_id: UUID | None = None,
    workflow_id: UUID | None = None,
    provenance: dict[str, str] | None = None,
) -> GeneratedArtifact:
    """Produce a deterministic management workbook with data, summary, and provenance."""
    safe_frame = _sanitize_spreadsheet_strings(frame)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        safe_frame.to_excel(writer, sheet_name="Data", index=False)
        summary = pd.DataFrame(
            {"Metric": ["Rows", "Columns"], "Value": [len(frame), len(frame.columns)]}
        )
        summary.to_excel(writer, sheet_name="Summary", index=False)
        provenance_frame = pd.DataFrame(
            list((provenance or {}).items()), columns=["Property", "Value"]
        )
        provenance_frame.to_excel(writer, sheet_name="Provenance", index=False)
        numeric_columns = [index + 1 for index, column in enumerate(frame.columns) if pd.api.types.is_numeric_dtype(frame[column])]
        if numeric_columns and len(frame) > 0:
            chart = BarChart()
            first_numeric = numeric_columns[0]
            chart.add_data(Reference(writer.book["Data"], min_col=first_numeric, min_row=1, max_row=len(frame) + 1), titles_from_data=True)
            chart.title = f"{frame.columns[first_numeric - 1]} overview"
            writer.book["Summary"].add_chart(chart, "D2")
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(source_filename).stem).strip("_") or "report"
    return GeneratedArtifact(
        filename=f"{stem}_management_report.xlsx",
        format="xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        row_count=len(frame),
        column_count=len(frame.columns),
        content=output.getvalue(),
        artifact_id=uuid4(),
        created_at=datetime.now(timezone.utc),
        producing_task_id=task_id,
        producing_workflow_id=workflow_id,
        provenance=provenance,
    )


class InMemoryArtifactRepository:
    """Request-independent test repository behind a small persistence boundary."""

    def __init__(self) -> None:
        self._artifacts: dict[UUID, GeneratedArtifact] = {}

    def save(self, artifact: GeneratedArtifact) -> None:
        self._artifacts[artifact.artifact_id] = artifact

    def get(self, artifact_id: UUID) -> GeneratedArtifact | None:
        return self._artifacts.get(artifact_id)


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
