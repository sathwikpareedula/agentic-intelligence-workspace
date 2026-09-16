"""Offline regression coverage for the AWS Lambda Function URL adapter."""

import base64
import json
from types import SimpleNamespace

from app.config import get_settings


def _function_url_event(
    path: str,
    *,
    method: str = "GET",
    body: bytes = b"",
    content_type: str | None = None,
) -> dict:
    headers = {
        "host": "example.lambda-url.us-east-1.on.aws",
        "x-forwarded-proto": "https",
    }
    if content_type:
        headers["content-type"] = content_type
    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": "",
        "headers": headers,
        "requestContext": {
            "accountId": "anonymous",
            "apiId": "test",
            "domainName": headers["host"],
            "domainPrefix": "example",
            "http": {
                "method": method,
                "path": path,
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": "pytest",
            },
            "requestId": "lambda-adapter-test",
            "routeKey": "$default",
            "stage": "$default",
            "time": "16/Sep/2026:00:00:00 +0000",
            "timeEpoch": 0,
        },
        "body": base64.b64encode(body).decode("ascii") if body else None,
        "isBase64Encoded": bool(body),
    }


def _invoke(event: dict) -> tuple[int, dict]:
    from app.lambda_handler import handler

    response = handler(event, SimpleNamespace())
    return response["statusCode"], json.loads(response["body"])


def test_lambda_adapter_exposes_demo_health_runtime_and_dataset_inspection(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "demo")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_API_KEY", raising=False)
    get_settings.cache_clear()

    health_status, health = _invoke(_function_url_event("/health"))
    runtime_status, runtime = _invoke(_function_url_event("/runtime"))
    ready_status, ready = _invoke(_function_url_event("/ready"))

    boundary = "aiw-lambda-test-boundary"
    csv_content = b"facility,amount\nCedar,1000\nLake,800\n"
    multipart = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="facilities.csv"\r\n'
        "Content-Type: text/csv\r\n\r\n"
    ).encode("ascii") + csv_content + f"\r\n--{boundary}--\r\n".encode("ascii")
    inspect_status, inspection = _invoke(
        _function_url_event(
            "/datasets/inspect",
            method="POST",
            body=multipart,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
    )

    assert health_status == 200
    assert health == {"status": "ok"}
    assert runtime_status == 200
    assert runtime["status"] == "ready"
    assert runtime["mode"] == "demo"
    assert runtime["storage"] == "in_memory"
    assert ready_status == 200
    assert ready["status"] == "ready"
    assert inspect_status == 200
    assert inspection["filename"] == "facilities.csv"
    assert inspection["row_count"] == 2
    assert inspection["column_count"] == 2
    assert inspection["columns"] == ["facility", "amount"]

    get_settings.cache_clear()
