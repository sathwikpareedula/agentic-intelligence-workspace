"""Typed contracts for bounded structured uploads and external data sources."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.datasets import DatasetInspection, DatasetProfile, DatasetProvenance
from app.services.secrets import is_sensitive_name


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DatasetPayload(StrictModel):
    filename: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=1, max_length=200)
    content_base64: str = Field(min_length=1)


class ImportedDataset(StrictModel):
    inspection: DatasetInspection
    profile: DatasetProfile | None = None
    provenance: DatasetProvenance
    dataset: DatasetPayload


class PostgresSourceConfig(StrictModel):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=63, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    user: str = Field(min_length=1, max_length=63)
    password_secret_ref: str = Field(min_length=1, max_length=100, pattern=r"^[A-Z][A-Z0-9_]*$")
    sslmode: Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] = "prefer"
    connect_timeout_seconds: int = Field(default=3, ge=1, le=30)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or "/" in cleaned or "\\" in cleaned or "@" in cleaned:
            raise ValueError("PostgreSQL host must be a hostname or address without credentials or paths.")
        return cleaned


class PostgresTableRef(StrictModel):
    schema_name: str = Field(alias="schema", min_length=1, max_length=63, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    table: str = Field(min_length=1, max_length=63, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PostgresInspectRequest(StrictModel):
    source: PostgresSourceConfig
    table: PostgresTableRef | None = None


class PostgresImportRequest(StrictModel):
    source: PostgresSourceConfig
    table: PostgresTableRef | None = None
    select_sql: str | None = Field(default=None, min_length=12, max_length=4000)
    max_rows: int | None = Field(default=None, ge=1, le=100_000)

    @field_validator("select_sql")
    @classmethod
    def strip_sql(cls, value: str | None) -> str | None:
        return value.strip() if value else value


class PostgresColumnMetadata(StrictModel):
    name: str
    data_type: str
    nullable: bool
    is_primary_key: bool = False


class PostgresTableMetadata(StrictModel):
    schema_name: str = Field(alias="schema")
    name: str
    table_type: Literal["BASE TABLE", "VIEW"]
    columns: list[PostgresColumnMetadata] = Field(default_factory=list)
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PostgresCatalog(StrictModel):
    schemas: list[str]
    tables: list[PostgresTableMetadata]


class RestSourceConfig(StrictModel):
    url: str = Field(min_length=8, max_length=2000)
    method: Literal["GET"] = "GET"
    query: dict[str, str] = Field(default_factory=dict, max_length=20)
    header_secret_refs: dict[str, str] = Field(default_factory=dict, max_length=10)
    timeout_seconds: float = Field(default=5.0, ge=0.5, le=30)
    records_key: str | None = Field(default=None, max_length=100)

    @field_validator("header_secret_refs")
    @classmethod
    def validate_secret_refs(cls, value: dict[str, str]) -> dict[str, str]:
        pattern = re.compile(r"^[A-Z][A-Z0-9_]*$")
        normalized_headers: set[str] = set()
        for header, ref in value.items():
            if not header.strip() or any(char in header for char in "\r\n"):
                raise ValueError("Header names must be a single line.")
            normalized = header.strip().casefold()
            if normalized in normalized_headers:
                raise ValueError("Header names must be unique case-insensitively.")
            if normalized in {
                "connection",
                "content-length",
                "host",
                "proxy-connection",
                "te",
                "trailer",
                "transfer-encoding",
                "upgrade",
            }:
                raise ValueError(f"Header '{header}' cannot be supplied by a REST source.")
            if not pattern.fullmatch(ref):
                raise ValueError("Secret references must be uppercase environment variable names.")
            normalized_headers.add(normalized)
        return value

    @model_validator(mode="after")
    def reject_query_secrets(self) -> "RestSourceConfig":
        from urllib.parse import parse_qsl, urlsplit

        try:
            parsed = urlsplit(self.url)
            _ = parsed.port
            url_query_names = [name for name, _ in parse_qsl(parsed.query, keep_blank_values=True)]
        except ValueError as exc:
            raise ValueError("REST URL contains an invalid hostname or port.") from exc
        sensitive = sorted(
            {name for name in [*url_query_names, *self.query] if is_sensitive_name(name)},
            key=str.casefold,
        )
        if sensitive:
            raise ValueError(
                "Secret-like REST query parameters are not accepted; use a secret-referenced request header."
            )
        return self


class RestImportRequest(StrictModel):
    source: RestSourceConfig
