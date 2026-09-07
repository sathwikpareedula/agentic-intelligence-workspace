"""External source connectors: PostgreSQL (read-only) and bounded REST JSON."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import Settings, get_settings
from app.models.sources import (
    ImportedDataset,
    PostgresCatalog,
    PostgresImportRequest,
    PostgresInspectRequest,
    PostgresSourceConfig,
    PostgresTableMetadata,
    RestImportRequest,
)
from app.services.postgres_source import PostgresSourceError, import_source, inspect_table, list_catalog, test_connection
from app.services.rest_source import RestSourceError, import_rest
from app.services.secrets import SecretError

router = APIRouter(prefix="/sources", tags=["sources"])


@router.post("/postgres/test")
def postgres_test(config: PostgresSourceConfig) -> dict:
    try:
        return test_connection(config)
    except (PostgresSourceError, SecretError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.post("/postgres/tables", response_model=PostgresCatalog)
def postgres_tables(config: PostgresSourceConfig) -> PostgresCatalog:
    try:
        return list_catalog(config)
    except (PostgresSourceError, SecretError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.post("/postgres/inspect", response_model=PostgresTableMetadata)
def postgres_inspect(request: PostgresInspectRequest) -> PostgresTableMetadata:
    if request.table is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A table reference is required.")
    try:
        return inspect_table(request.source, request.table)
    except (PostgresSourceError, SecretError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.post("/postgres/import", response_model=ImportedDataset)
def postgres_import(request: PostgresImportRequest) -> ImportedDataset:
    try:
        return import_source(request)
    except (PostgresSourceError, SecretError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.post("/rest/import", response_model=ImportedDataset)
def rest_import(request: RestImportRequest, settings: Settings = Depends(get_settings)) -> ImportedDataset:
    try:
        return import_rest(request.source, allow_private=settings.allow_private_rest_targets)
    except (RestSourceError, SecretError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
