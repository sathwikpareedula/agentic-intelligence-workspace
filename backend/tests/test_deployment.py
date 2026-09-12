"""Static deployment contracts for hosts where Docker is unavailable."""

from pathlib import Path


ROOT = Path(__file__).parents[2]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_backend_container_is_non_root_health_checked_and_context_bounded() -> None:
    dockerfile = _text("backend/Dockerfile")
    ignored = set(_text("backend/.dockerignore").splitlines())

    assert "USER app" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "127.0.0.1:8000/health" in dockerfile
    assert "/app/var/artifacts" in dockerfile
    assert {".venv", ".git", ".env", "__pycache__", ".pytest_cache", "tests", "var"}.issubset(ignored)


def test_frontend_container_uses_build_time_public_url_and_standalone_non_root_runtime() -> None:
    dockerfile = _text("frontend/Dockerfile")
    next_config = _text("frontend/next.config.ts")
    ignored = set(_text("frontend/.dockerignore").splitlines())

    assert dockerfile.index("ARG NEXT_PUBLIC_API_URL") < dockerfile.index("RUN npm run build")
    assert "USER nextjs" in dockerfile
    assert "/app/.next/standalone" in dockerfile
    assert 'CMD ["node", "server.js"]' in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert 'output: "standalone"' in next_config
    assert {"node_modules", ".next", ".git", ".env*"}.issubset(ignored)
    for secret_name in ("OPENAI_API_KEY", "ORCHESTRATOR_API_KEY", "DATABASE_URL", "POSTGRES_PASSWORD"):
        assert secret_name not in dockerfile
        assert secret_name not in next_config


def test_compose_preserves_one_shot_migrations_and_health_dependencies() -> None:
    compose = _text("compose.yaml")

    assert 'command: ["alembic", "upgrade", "head"]' in compose
    assert "condition: service_completed_successfully" in compose
    assert "condition: service_healthy" in compose
    assert "NEXT_PUBLIC_API_URL: ${NEXT_PUBLIC_API_URL:-http://localhost:8000}" in compose
    frontend = compose.split("  frontend:", 1)[1].split("  postgres:", 1)[0]
    assert "args:" in frontend
    assert "environment:" not in frontend


def test_compose_forwards_documented_backend_runtime_configuration() -> None:
    compose = _text("compose.yaml")
    backend = compose.split("  backend:", 1)[1].split("  migrate:", 1)[0]

    for setting in (
        "DATABASE_CONNECT_TIMEOUT_SECONDS",
        "EMBEDDING_MODEL",
        "EMBEDDING_DIMENSIONS",
        "EMBEDDING_BATCH_SIZE",
        "ORCHESTRATOR_CONTEXT_TOKENS",
        "PDF_MAX_UPLOAD_BYTES",
        "RETRIEVAL_CHUNK_SIZE",
        "RETRIEVAL_CHUNK_OVERLAP",
        "ALLOW_PRIVATE_REST_TARGETS",
        "EXTERNAL_PG_PASSWORD",
        "REST_BEARER_TOKEN",
    ):
        assert f"{setting}: ${{{setting}:-" in backend
