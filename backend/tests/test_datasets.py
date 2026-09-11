"""API tests for deterministic dataset ingestion, inspection, and profiling."""

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.datasets import MAX_DATASET_COLUMNS, MAX_UPLOAD_BYTES

client = TestClient(app)


@pytest.fixture
def csv_content() -> bytes:
    return (
        b"id,category,amount\n"
        b"1,alpha,10\n"
        b"2,beta,20\n"
        b"2,beta,20\n"
        b"3,,\n"
    )


def _xlsx_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=sheet_name, index=False)
    return output.getvalue()


def test_inspect_csv_reports_shape_missing_values_and_duplicates(csv_content: bytes) -> None:
    response = client.post(
        "/datasets/inspect",
        files={"file": ("records.csv", csv_content, "text/csv")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "records.csv"
    assert body["file_type"] == "csv"
    assert body["selected_sheet"] is None
    assert body["row_count"] == 4
    assert body["column_count"] == 3
    assert body["columns"] == ["id", "category", "amount"]
    assert body["duplicate_row_count"] == 1
    details = {column["name"]: column for column in body["column_details"]}
    assert details["category"]["missing_count"] == 1
    assert details["category"]["missing_percentage"] == 25.0
    assert details["amount"]["missing_count"] == 1


def test_profile_csv_reports_numeric_and_categorical_summaries(csv_content: bytes) -> None:
    response = client.post(
        "/datasets/profile",
        files={"file": ("records.csv", csv_content, "text/csv")},
    )

    assert response.status_code == 200
    profiles = {column["name"]: column for column in response.json()["columns"]}
    assert profiles["amount"] == {
        "name": "amount",
        "kind": "numeric",
        "count": 3,
        "missing_count": 1,
        "mean": pytest.approx(50 / 3),
        "minimum": 10.0,
        "maximum": 20.0,
        "median": 20.0,
    }
    assert profiles["category"]["kind"] == "categorical"
    assert profiles["category"]["count"] == 3
    assert profiles["category"]["missing_count"] == 1
    assert profiles["category"]["unique_count"] == 2
    assert profiles["category"]["top_values"] == [
        {"value": "beta", "count": 2},
        {"value": "alpha", "count": 1},
    ]


def test_xlsx_defaults_to_first_sheet() -> None:
    content = _xlsx_bytes(
        {
            "Overview": pd.DataFrame({"value": [1, 2]}),
            "Details": pd.DataFrame({"value": [3, 4, 5]}),
        }
    )

    response = client.post(
        "/datasets/inspect",
        files={"file": ("workbook.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    assert response.json()["selected_sheet"] == "Overview"
    assert response.json()["row_count"] == 2


def test_xlsx_supports_explicit_sheet_selection() -> None:
    content = _xlsx_bytes(
        {
            "Overview": pd.DataFrame({"value": [1]}),
            "Details": pd.DataFrame({"value": [3, 4, 5]}),
        }
    )

    response = client.post(
        "/datasets/inspect",
        data={"sheet": "Details"},
        files={"file": ("workbook.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    assert response.json()["selected_sheet"] == "Details"
    assert response.json()["row_count"] == 3


def test_xlsx_rejects_unknown_sheet() -> None:
    content = _xlsx_bytes({"Overview": pd.DataFrame({"value": [1]})})

    response = client.post(
        "/datasets/inspect",
        data={"sheet": "Missing"},
        files={"file": ("workbook.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 422
    assert "Available sheets: Overview" in response.json()["detail"]


def test_rejects_unsupported_file_type() -> None:
    response = client.post(
        "/datasets/inspect",
        files={"file": ("records.xml", b"<rows/>", "application/xml")},
    )

    assert response.status_code == 415
    assert "Unsupported file type" in response.json()["detail"]


@pytest.mark.parametrize(
    ("filename", "content"),
    [("broken.csv", b'id,value\n1,"unterminated'), ("broken.xlsx", b"not a workbook")],
)
def test_rejects_malformed_supported_files(filename: str, content: bytes) -> None:
    response = client.post(
        "/datasets/inspect",
        files={"file": (filename, content, "application/octet-stream")},
    )

    assert response.status_code == 422
    assert "Could not read" in response.json()["detail"]


def test_header_only_csv_returns_empty_dataset_profile() -> None:
    response = client.post(
        "/datasets/profile",
        files={"file": ("empty.csv", b"number,label\n", "text/csv")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["inspection"]["row_count"] == 0
    assert body["inspection"]["duplicate_row_count"] == 0
    assert body["columns"] == [
        {
            "name": "number",
            "kind": "categorical",
            "count": 0,
            "missing_count": 0,
            "unique_count": 0,
            "top_values": [],
        },
        {
            "name": "label",
            "kind": "categorical",
            "count": 0,
            "missing_count": 0,
            "unique_count": 0,
            "top_values": [],
        },
    ]


def test_rejects_zero_byte_file() -> None:
    response = client.post(
        "/datasets/inspect",
        files={"file": ("empty.csv", b"", "text/csv")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "The uploaded file is empty."


def test_rejects_sheet_for_csv(csv_content: bytes) -> None:
    response = client.post(
        "/datasets/inspect",
        data={"sheet": "Sheet1"},
        files={"file": ("records.csv", csv_content, "text/csv")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Sheet selection is only supported for .xlsx files."


def test_rejects_file_over_size_limit() -> None:
    response = client.post(
        "/datasets/inspect",
        files={"file": ("large.csv", b"a\n" + b"1" * MAX_UPLOAD_BYTES, "text/csv")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "File exceeds the 10 MiB limit."


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
def test_rejects_wide_tabular_upload_before_full_processing(extension: str) -> None:
    frame = pd.DataFrame(
        columns=[f"column_{index}" for index in range(MAX_DATASET_COLUMNS + 1)]
    )
    content = (
        frame.to_csv(index=False).encode()
        if extension == "csv"
        else _xlsx_bytes({"Data": frame})
    )

    response = client.post(
        "/datasets/inspect",
        files={"file": (f"wide.{extension}", content, "application/octet-stream")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Datasets may contain at most 200 columns."


def test_rejects_xlsx_archive_expansion_before_workbook_parsing(monkeypatch) -> None:
    import app.services.workbook_safety as workbook_safety

    content = _xlsx_bytes({"Data": pd.DataFrame({"value": [1]})})
    monkeypatch.setattr(workbook_safety, "MAX_WORKBOOK_UNCOMPRESSED_BYTES", 1)

    response = client.post(
        "/datasets/inspect",
        files={"file": ("expanded.xlsx", content, "application/octet-stream")},
    )

    assert response.status_code == 413
    assert "expands beyond supported safety limits" in response.json()["detail"]


@pytest.mark.parametrize(
    ("member", "message"),
    [
        ("../escape.xml", "unsafe internal path"),
        ("xl/vbaProject.bin", "Macro-enabled"),
        ("xl/externalLinks/link1.xml", "externally linked active content"),
    ],
)
def test_rejects_unsafe_xlsx_archive_members(member: str, message: str) -> None:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(member, b"unsafe")

    response = client.post(
        "/datasets/inspect",
        files={"file": ("unsafe.xlsx", output.getvalue(), "application/octet-stream")},
    )

    assert response.status_code == 422
    assert message in response.json()["detail"]
