"""Tests for the health endpoint."""

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


def test_readiness_and_request_id_propagation(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    try:
        response = client.get("/ready", headers={"x-request-id": "test-request-123"})
        assert response.status_code == 503
        assert response.json()["status"] == "not_ready"
        assert response.json()["mode"] == "production"
        assert "DATABASE_URL is not configured." in response.json()["limitations"]
        assert response.headers["x-request-id"] == "test-request-123"
    finally:
        get_settings.cache_clear()


def test_runtime_diagnostics_do_not_expose_secrets() -> None:
    response = client.get("/runtime")

    assert response.status_code == 200
    assert response.json()["storage"] == "postgresql"
    assert set(response.json()) == {
        "status", "mode", "storage", "embedding_provider", "orchestrator_provider",
        "orchestrator_status", "orchestrator_model", "database", "pgvector",
        "migrations", "artifact_storage", "limitations"
    }


def test_validation_errors_have_stable_schema_and_safe_request_ids() -> None:
    response = client.post(
        "/agent/tasks",
        headers={"x-request-id": "not valid whitespace"},
        json={"goal": "", "max_iterations": 0},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert response.headers["x-request-id"] != "not valid whitespace"
    assert isinstance(response.json()["detail"], list)
