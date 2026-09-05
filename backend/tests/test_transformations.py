"""API tests for deterministic transformations, joins, and artifacts."""

from io import BytesIO
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.main import app
from app.services.artifacts import InMemoryArtifactRepository

client = TestClient(app)

SALES = b"id,region,amount,cost\n1,North,100,40\n2,South,50,20\n2,South,50,20\n3,North,,30\n"


@pytest.fixture(autouse=True)
def artifact_repository():
    previous = app.state.artifact_repository
    app.state.artifact_repository = InMemoryArtifactRepository()
    try:
        yield
    finally:
        app.state.artifact_repository = previous


def _transform(spec: dict, content: bytes = SALES):
    return client.post(
        "/datasets/transform",
        data={"request": json.dumps(spec)},
        files={"file": ("sales.csv", content, "text/csv")},
    )


def _join(spec: dict, left: bytes, right: bytes):
    return client.post(
        "/datasets/join",
        data={"request": json.dumps(spec)},
        files={
            "left_file": ("left.csv", left, "text/csv"),
            "right_file": ("right.csv", right, "text/csv"),
        },
    )


def test_select_filter_and_sort_rows() -> None:
    response = _transform(
        {
            "operations": [
                {"type": "filter", "column": "amount", "operator": "gte", "value": 50},
                {"type": "sort", "keys": [{"column": "amount", "ascending": False}]},
                {"type": "select", "columns": ["id", "amount"]},
            ]
        }
    )

    assert response.status_code == 200
    assert response.json() == {
        "row_count": 3,
        "column_count": 2,
        "columns": ["id", "amount"],
        "rows": [{"id": 1, "amount": 100.0}, {"id": 2, "amount": 50.0}, {"id": 2, "amount": 50.0}],
    }


def test_rename_drop_duplicates_fill_missing_and_derive() -> None:
    response = _transform(
        {
            "operations": [
                {"type": "drop_duplicates", "columns": ["id"]},
                {"type": "missing", "action": "fill", "columns": ["amount"], "value": 1},
                {"type": "rename", "mapping": {"amount": "revenue"}},
                {
                    "type": "derive",
                    "new_column": "margin",
                    "left_column": "revenue",
                    "operator": "subtract",
                    "right_column": "cost",
                },
                {
                    "type": "derive",
                    "new_column": "margin_pct",
                    "left_column": "margin",
                    "operator": "percentage",
                    "right_column": "revenue",
                },
            ]
        }
    )

    assert response.status_code == 200
    body = response.json()
    assert body["row_count"] == 3
    assert body["rows"][0]["margin"] == 60.0
    assert body["rows"][0]["margin_pct"] == 60.0
    assert body["rows"][2]["margin"] == -29.0
    assert body["rows"][2]["margin_pct"] == -2900.0


def test_drop_missing_rows() -> None:
    response = _transform({"operations": [{"type": "missing", "action": "drop", "columns": ["amount"]}]})

    assert response.status_code == 200
    assert response.json()["row_count"] == 3


def test_derive_column_with_numeric_constant() -> None:
    response = _transform(
        {
            "operations": [
                {"type": "derive", "new_column": "amount_doubled", "left_column": "amount", "operator": "multiply", "constant": 2}
            ]
        }
    )

    assert response.status_code == 200
    assert response.json()["rows"][0]["amount_doubled"] == 200.0
    assert response.json()["rows"][3]["amount_doubled"] is None


def test_group_aggregation_then_derive_metric() -> None:
    response = _transform(
        {
            "operations": [
                {
                    "type": "group",
                    "group_by": ["region"],
                    "aggregations": [
                        {"column": "amount", "function": "sum", "alias": "revenue"},
                        {"column": "cost", "function": "sum", "alias": "cost_total"},
                        {"column": "id", "function": "count", "alias": "transactions"},
                    ],
                },
                {
                    "type": "derive",
                    "new_column": "profit",
                    "left_column": "revenue",
                    "operator": "subtract",
                    "right_column": "cost_total",
                },
            ]
        }
    )

    assert response.status_code == 200
    rows = {row["region"]: row for row in response.json()["rows"]}
    assert rows["North"] == {"region": "North", "revenue": 100.0, "cost_total": 70, "transactions": 2, "profit": 30.0}
    assert rows["South"]["revenue"] == 100.0


def test_rejects_unknown_column_and_incompatible_operations() -> None:
    unknown = _transform({"operations": [{"type": "select", "columns": ["missing"]}]})
    incompatible = _transform(
        {
            "operations": [
                {"type": "derive", "new_column": "bad", "left_column": "region", "operator": "add", "constant": 1}
            ]
        }
    )
    invalid_aggregation = _transform(
        {
            "operations": [
                {
                    "type": "group",
                    "group_by": ["region"],
                    "aggregations": [{"column": "region", "function": "mean"}],
                }
            ]
        }
    )

    assert unknown.status_code == 422
    assert unknown.json()["detail"] == "Unknown column(s) in dataset: missing."
    assert incompatible.status_code == 422
    assert "requires numeric column 'region'" in incompatible.json()["detail"]
    assert invalid_aggregation.status_code == 422
    assert "requires numeric column 'region'" in invalid_aggregation.json()["detail"]


def test_rejects_division_by_zero_and_unknown_operation_type() -> None:
    zero = _transform(
        {
            "operations": [
                {"type": "derive", "new_column": "bad", "left_column": "amount", "operator": "divide", "constant": 0}
            ]
        }
    )
    arbitrary = _transform({"operations": [{"type": "python", "code": "eval('1+1')"}]})
    extra_field = _transform({"operations": [{"type": "select", "columns": ["id"], "code": "ignored"}]})

    assert zero.status_code == 422
    assert zero.json()["detail"] == "Division by zero is not allowed."
    assert arbitrary.status_code == 422
    assert extra_field.status_code == 422


def test_left_join_reports_matches_and_unmatched_rows() -> None:
    response = _join(
        {"join": {"left_on": ["customer_id"], "right_on": ["customer_id"], "how": "left"}},
        b"order_id,customer_id\n1,C1\n2,C2\n3,C9\n",
        b"customer_id,segment\nC1,A\nC2,B\nC3,C\n",
    )

    assert response.status_code == 200
    diagnostics = response.json()["diagnostics"]
    assert diagnostics["left_input_rows"] == 3
    assert diagnostics["right_input_rows"] == 3
    assert diagnostics["output_rows"] == 3
    assert diagnostics["matched_output_rows"] == 2
    assert diagnostics["left_unmatched_rows"] == 1
    assert diagnostics["right_unmatched_rows"] == 1
    assert diagnostics["row_multiplication_occurred"] is False
    assert response.json()["result"]["rows"][2]["segment"] is None


def test_many_to_many_join_surfaces_row_multiplication_warning() -> None:
    response = _join(
        {"join": {"left_on": ["key"], "right_on": ["key"], "how": "inner"}},
        b"key,left_value\nA,1\nA,2\n",
        b"key,right_value\nA,x\nA,y\n",
    )

    assert response.status_code == 200
    diagnostics = response.json()["diagnostics"]
    assert diagnostics["output_rows"] == 4
    assert diagnostics["row_multiplication_occurred"] is True
    assert diagnostics["many_to_many_detected"] is True
    assert diagnostics["warning"] == "Many-to-many join keys produced suspicious row multiplication."


def test_inner_right_and_outer_join_types() -> None:
    left = b"key,left_value\nA,1\nB,2\n"
    right = b"key,right_value\nB,x\nC,y\n"

    inner = _join({"join": {"left_on": ["key"], "right_on": ["key"], "how": "inner"}}, left, right)
    right_join = _join({"join": {"left_on": ["key"], "right_on": ["key"], "how": "right"}}, left, right)
    outer = _join({"join": {"left_on": ["key"], "right_on": ["key"], "how": "outer"}}, left, right)

    assert inner.status_code == right_join.status_code == outer.status_code == 200
    assert inner.json()["result"]["row_count"] == 1
    assert right_join.json()["result"]["row_count"] == 2
    assert outer.json()["result"]["row_count"] == 3
    assert right_join.json()["diagnostics"]["left_unmatched_rows"] == 1
    assert outer.json()["diagnostics"]["right_unmatched_rows"] == 1


def test_join_rejects_invalid_keys() -> None:
    response = _join(
        {"join": {"left_on": ["missing"], "right_on": ["id"], "how": "inner"}},
        b"id,value\n1,a\n",
        b"id,label\n1,b\n",
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown column(s) in left dataset: missing."


def test_csv_export_has_metadata_and_can_be_read_back() -> None:
    response = client.post(
        "/datasets/export",
        data={"request": json.dumps({"format": "csv", "operations": [{"type": "drop_duplicates", "columns": ["id"]}]})},
        files={"file": ("unsafe name.csv", SALES, "text/csv")},
    )

    assert response.status_code == 200
    assert response.headers["x-artifact-filename"] == "unsafe_name_result.csv"
    assert response.headers["x-artifact-format"] == "csv"
    assert response.headers["x-artifact-row-count"] == "3"
    assert response.headers["x-artifact-column-count"] == "4"
    downloaded = client.get(f"/artifacts/{response.headers['x-artifact-id']}")
    assert downloaded.status_code == 200
    assert downloaded.content == response.content
    frame = pd.read_csv(BytesIO(response.content))
    assert frame.shape == (3, 4)


def test_xlsx_export_has_metadata_and_can_be_read_back() -> None:
    response = client.post(
        "/datasets/export",
        data={"request": json.dumps({"format": "xlsx", "operations": [{"type": "select", "columns": ["id", "amount"]}]})},
        files={"file": ("sales.csv", SALES, "text/csv")},
    )

    assert response.status_code == 200
    assert response.headers["x-artifact-filename"] == "sales_result.xlsx"
    assert response.headers["x-artifact-format"] == "xlsx"
    frame = pd.read_excel(BytesIO(response.content), engine="openpyxl")
    assert frame.shape == (4, 2)
    assert frame.columns.tolist() == ["id", "amount"]


def test_join_workflow_export_can_be_read_back() -> None:
    request = {
        "format": "csv",
        "left_operations": [
            {"type": "drop_duplicates", "columns": ["transaction_id"]},
            {"type": "missing", "action": "drop", "columns": ["amount"]},
        ],
        "join": {"left_on": ["customer_id"], "right_on": ["customer_id"], "how": "inner"},
        "operations": [
            {
                "type": "group",
                "group_by": ["segment"],
                "aggregations": [
                    {"column": "amount", "function": "sum", "alias": "revenue"},
                    {"column": "discount", "function": "sum", "alias": "discount_total"},
                ],
            },
            {
                "type": "derive",
                "new_column": "net_revenue",
                "left_column": "revenue",
                "operator": "subtract",
                "right_column": "discount_total",
            },
        ],
    }
    response = client.post(
        "/datasets/join/export",
        data={"request": json.dumps(request)},
        files={
            "left_file": ("transactions.csv", b"transaction_id,customer_id,amount,discount\nT1,C1,100,10\nT1,C1,100,10\nT2,C2,50,5\nT3,C9,25,0\nT4,C1,,2\n", "text/csv"),
            "right_file": ("customers.csv", b"customer_id,segment\nC1,Enterprise\nC2,Consumer\n", "text/csv"),
        },
    )

    assert response.status_code == 200
    assert response.headers["x-artifact-filename"] == "joined_dataset_result.csv"
    assert response.headers["x-artifact-row-count"] == "2"
    frame = pd.read_csv(BytesIO(response.content))
    rows = frame.set_index("segment").to_dict(orient="index")
    assert rows["Enterprise"]["net_revenue"] == 90
    assert rows["Consumer"]["net_revenue"] == 45


def test_xlsx_export_neutralizes_formula_like_text() -> None:
    response = client.post(
        "/datasets/export",
        data={"request": json.dumps({"format": "xlsx"})},
        files={"file": ("formulas.csv", b"label,value\n=2+2,1\n@SUM(A1),2\n", "text/csv")},
    )

    assert response.status_code == 200
    workbook = load_workbook(BytesIO(response.content), read_only=True, data_only=False)
    sheet = workbook["Result"]
    assert sheet["A2"].value == "'=2+2"
    assert sheet["A3"].value == "'@SUM(A1)"
    assert sheet["A2"].data_type == "s"
