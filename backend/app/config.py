"""Environment-backed application configuration."""

from dataclasses import dataclass
from functools import lru_cache
import os
from typing import Literal
from urllib.parse import urlparse


class ConfigurationError(Exception):
    """Raised when required runtime configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    app_mode: Literal["production", "demo"]
    database_url: str | None
    database_connect_timeout_seconds: int
    artifact_storage_path: str
    embedding_provider: str
    openai_api_key: str | None
    embedding_model: str
    embedding_dimensions: int
    embedding_batch_size: int
    pdf_max_upload_bytes: int
    chunk_size: int
    chunk_overlap: int
    orchestrator_provider: str
    orchestrator_api_key: str | None
    orchestrator_base_url: str | None
    orchestrator_model: str
    orchestrator_timeout_seconds: float
    orchestrator_max_retries: int
    orchestrator_max_output_tokens: int
    orchestrator_context_tokens: int
    orchestrator_input_cost_per_million: float | None
    orchestrator_output_cost_per_million: float | None
    allow_private_rest_targets: bool
    cors_allowed_origins: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            app_mode=_choice("APP_MODE", "production", {"production", "demo"}),
            database_url=os.getenv("DATABASE_URL"),
            database_connect_timeout_seconds=_positive_int("DATABASE_CONNECT_TIMEOUT_SECONDS", 3),
            artifact_storage_path=os.getenv("ARTIFACT_STORAGE_PATH", "./var/artifacts").strip(),
            embedding_provider=os.getenv("EMBEDDING_PROVIDER", "openai"),
            openai_api_key=_optional_env("OPENAI_API_KEY"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            embedding_dimensions=_positive_int("EMBEDDING_DIMENSIONS", 1536),
            embedding_batch_size=_positive_int("EMBEDDING_BATCH_SIZE", 100),
            pdf_max_upload_bytes=_positive_int("PDF_MAX_UPLOAD_BYTES", 20 * 1024 * 1024),
            chunk_size=_positive_int("RETRIEVAL_CHUNK_SIZE", 1200),
            chunk_overlap=_non_negative_int("RETRIEVAL_CHUNK_OVERLAP", 200),
            orchestrator_provider=_choice("ORCHESTRATOR_PROVIDER", "openai", {"none", "ollama", "openai"}),
            orchestrator_api_key=_optional_env("ORCHESTRATOR_API_KEY") or _optional_env("OPENAI_API_KEY"),
            orchestrator_base_url=_optional_http_url("ORCHESTRATOR_BASE_URL"),
            orchestrator_model=os.getenv("ORCHESTRATOR_MODEL", "gpt-6-astra").strip(),
            orchestrator_timeout_seconds=_positive_float("ORCHESTRATOR_TIMEOUT_SECONDS", 30.0),
            orchestrator_max_retries=_non_negative_int("ORCHESTRATOR_MAX_RETRIES", 2),
            orchestrator_max_output_tokens=_positive_int("ORCHESTRATOR_MAX_OUTPUT_TOKENS", 3000),
            orchestrator_context_tokens=_positive_int("ORCHESTRATOR_CONTEXT_TOKENS", 8192),
            orchestrator_input_cost_per_million=_optional_non_negative_float("ORCHESTRATOR_INPUT_COST_PER_MILLION"),
            orchestrator_output_cost_per_million=_optional_non_negative_float("ORCHESTRATOR_OUTPUT_COST_PER_MILLION"),
            allow_private_rest_targets=os.getenv("ALLOW_PRIVATE_REST_TARGETS", "").strip() == "1",
            cors_allowed_origins=_http_origins("CORS_ALLOWED_ORIGINS"),
        )
        if settings.chunk_overlap >= settings.chunk_size:
            raise ConfigurationError("RETRIEVAL_CHUNK_OVERLAP must be smaller than RETRIEVAL_CHUNK_SIZE.")
        if not settings.orchestrator_model:
            raise ConfigurationError("ORCHESTRATOR_MODEL cannot be empty.")
        if settings.orchestrator_timeout_seconds > 120:
            raise ConfigurationError("ORCHESTRATOR_TIMEOUT_SECONDS must be at most 120.")
        if settings.orchestrator_max_retries > 5:
            raise ConfigurationError("ORCHESTRATOR_MAX_RETRIES must be at most 5.")
        if settings.orchestrator_max_output_tokens > 20_000:
            raise ConfigurationError("ORCHESTRATOR_MAX_OUTPUT_TOKENS must be at most 20000.")
        if not 2048 <= settings.orchestrator_context_tokens <= 131_072:
            raise ConfigurationError("ORCHESTRATOR_CONTEXT_TOKENS must be between 2048 and 131072.")
        if (
            settings.orchestrator_provider == "ollama"
            and settings.orchestrator_max_output_tokens >= settings.orchestrator_context_tokens
        ):
            raise ConfigurationError("ORCHESTRATOR_MAX_OUTPUT_TOKENS must be smaller than ORCHESTRATOR_CONTEXT_TOKENS for Ollama.")
        if (settings.orchestrator_input_cost_per_million is None) != (
            settings.orchestrator_output_cost_per_million is None
        ):
            raise ConfigurationError("Configure both orchestrator cost rates, or neither.")
        if settings.orchestrator_provider == "openai" and settings.orchestrator_base_url:
            _validate_openai_base_url(settings.orchestrator_base_url)
        if settings.orchestrator_provider == "ollama":
            _validate_ollama_base_url(settings.orchestrator_base_url or "http://127.0.0.1:11434/api")
            if settings.orchestrator_input_cost_per_million is not None:
                raise ConfigurationError("Do not configure monetary token rates for the local Ollama provider.")
        if not settings.artifact_storage_path:
            raise ConfigurationError("ARTIFACT_STORAGE_PATH cannot be empty.")
        return settings


def _choice(name: str, default: str, choices: set[str]):
    value = os.getenv(name, default).strip().lower()
    if value not in choices:
        expected = ", ".join(sorted(choices))
        raise ConfigurationError(f"{name} must be one of: {expected}.")
    return value


def _positive_int(name: str, default: int) -> int:
    value = _non_negative_int(name, default)
    if value == 0:
        raise ConfigurationError(f"{name} must be greater than zero.")
    return value


def _non_negative_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer.") from exc
    if value < 0:
        raise ConfigurationError(f"{name} cannot be negative.")
    return value


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number.") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero.")
    return value


def _optional_non_negative_float(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number.") from exc
    if value < 0:
        raise ConfigurationError(f"{name} cannot be negative.")
    return value


def _optional_http_url(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    value = raw.strip().rstrip("/")
    try:
        parsed = urlparse(value)
        parsed.port
    except ValueError as exc:
        raise ConfigurationError(f"{name} is malformed or contains an invalid port.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or "?" in value
        or "#" in value
        or any(character.isspace() for character in value)
        or parsed.netloc.endswith(":")
    ):
        raise ConfigurationError(
            f"{name} must be an HTTP(S) base URL and cannot contain credentials, query, or fragment."
        )
    return value


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _validate_openai_base_url(value: str) -> None:
    """Require TLS for remote OpenAI-compatible endpoints."""

    parsed = urlparse(value)
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ConfigurationError(
            "ORCHESTRATOR_BASE_URL must use HTTPS, except for literal loopback HTTP."
        )


def _validate_ollama_base_url(value: str) -> None:
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError:
        port = -1
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or port == -1
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/", "/api"}
    ):
        raise ConfigurationError(
            "ORCHESTRATOR_BASE_URL must be a loopback Ollama HTTP(S) URL without credentials, query, fragment, or custom path."
        )


def _http_origins(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "http://localhost:3000,http://127.0.0.1:3000")
    values = tuple(item.strip().rstrip("/") for item in raw.split(",") if item.strip())
    if not values:
        raise ConfigurationError(f"{name} must contain at least one HTTP(S) origin.")
    if len(values) > 20 or len(values) != len(set(values)):
        raise ConfigurationError(f"{name} must contain at most 20 unique origins.")
    for value in values:
        parsed = urlparse(value)
        try:
            port = parsed.port
        except ValueError:
            port = -1
        if (
            len(value) > 2048
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or port == -1
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ConfigurationError(
                f"{name} entries must be HTTP(S) origins without credentials, paths, queries, or fragments."
            )
    return values


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
