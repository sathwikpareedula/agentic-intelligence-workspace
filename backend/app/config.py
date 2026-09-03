"""Environment-backed application configuration."""

from dataclasses import dataclass
from functools import lru_cache
import os
from typing import Literal


class ConfigurationError(Exception):
    """Raised when required runtime configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    app_mode: Literal["production", "demo"]
    database_url: str | None
    embedding_provider: str
    openai_api_key: str | None
    embedding_model: str
    embedding_dimensions: int
    embedding_batch_size: int
    pdf_max_upload_bytes: int
    chunk_size: int
    chunk_overlap: int
    orchestrator_provider: str
    orchestrator_model: str
    orchestrator_timeout_seconds: float
    orchestrator_max_retries: int

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            app_mode=_choice("APP_MODE", "production", {"production", "demo"}),
            database_url=os.getenv("DATABASE_URL"),
            embedding_provider=os.getenv("EMBEDDING_PROVIDER", "openai"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            embedding_dimensions=_positive_int("EMBEDDING_DIMENSIONS", 1536),
            embedding_batch_size=_positive_int("EMBEDDING_BATCH_SIZE", 100),
            pdf_max_upload_bytes=_positive_int("PDF_MAX_UPLOAD_BYTES", 20 * 1024 * 1024),
            chunk_size=_positive_int("RETRIEVAL_CHUNK_SIZE", 1200),
            chunk_overlap=_non_negative_int("RETRIEVAL_CHUNK_OVERLAP", 200),
            orchestrator_provider=os.getenv("ORCHESTRATOR_PROVIDER", "none").strip().lower(),
            orchestrator_model=os.getenv("ORCHESTRATOR_MODEL", "gpt-5-mini").strip(),
            orchestrator_timeout_seconds=_positive_float("ORCHESTRATOR_TIMEOUT_SECONDS", 30.0),
            orchestrator_max_retries=_non_negative_int("ORCHESTRATOR_MAX_RETRIES", 2),
        )
        if settings.chunk_overlap >= settings.chunk_size:
            raise ConfigurationError("RETRIEVAL_CHUNK_OVERLAP must be smaller than RETRIEVAL_CHUNK_SIZE.")
        if not settings.orchestrator_model:
            raise ConfigurationError("ORCHESTRATOR_MODEL cannot be empty.")
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


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
