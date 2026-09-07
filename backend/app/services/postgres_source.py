"""Read-only external PostgreSQL connector with statement validation and secret refs."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any

import pandas as pd
import psycopg
from psycopg import sql

from app.models.datasets import DatasetProvenance
from app.models.sources import (
    ImportedDataset,
    PostgresCatalog,
    PostgresColumnMetadata,
    PostgresImportRequest,
    PostgresSourceConfig,
    PostgresTableMetadata,
    PostgresTableRef,
    DatasetPayload,
)
from app.services.datasets import MAX_DATASET_ROWS, inspect_dataset, loaded_from_frame, profile_dataset
from app.services.secrets import SecretError, resolve_secret

SYSTEM_SCHEMAS = {"pg_catalog", "information_schema", "pg_toast"}
FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|COPY|CALL|DO|"
    r"EXECUTE|SECURITY|LOAD|LISTEN|NOTIFY|UNLISTEN|LOCK|VACUUM|ANALYZE|CLUSTER|REINDEX|REFRESH|"
    r"RESET|SHOW|EXPLAIN|PREPARE|DEALLOCATE|DISCARD|FETCH|MOVE|CLOSE|DECLARE|INTO|OUTFILE|"
    r"DUMPFILE|PROGRAM|SET|COMMENT|REASSIGN|OWNER|RULE|TRIGGER|POLICY|PUBLICATION|SUBSCRIPTION|"
    r"CHECKPOINT|COMMIT|ROLLBACK|SAVEPOINT|BEGIN|START|pg_read_file|pg_write_file|"
    r"pg_read_binary_file|pg_ls_dir|pg_stat_file|pg_terminate_backend|pg_cancel_backend|"
    r"pg_reload_conf|set_config|dblink|lo_import|lo_export|lo_unlink)\b",
    re.IGNORECASE,
)
LOCKING_SELECT = re.compile(
    r"\bFOR\s+(NO\s+KEY\s+)?(UPDATE|SHARE|KEY\s+SHARE)\b",
    re.IGNORECASE,
)
DEFAULT_MAX_ROWS = 5000
STATEMENT_TIMEOUT_MS = 5000


class PostgresSourceError(Exception):
    """User-facing external PostgreSQL connector failure."""


def test_connection(config: PostgresSourceConfig) -> dict[str, str | int | bool]:
    with _connect(config) as connection:
        row = connection.execute("SELECT current_database() AS database, pg_is_in_recovery() AS replica").fetchone()
        assert row is not None
        return {
            "status": "ok",
            "database": str(row[0]),
            "read_only_session": True,
            "host": config.host,
            "port": config.port,
        }


def list_catalog(config: PostgresSourceConfig) -> PostgresCatalog:
    with _connect(config) as connection:
        schemas = [
            item[0]
            for item in connection.execute(
                """
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name <> ALL(%s)
                ORDER BY schema_name
                LIMIT 200
                """,
                (list(SYSTEM_SCHEMAS),),
            ).fetchall()
        ]
        tables = []
        for schema_name, name, table_type in connection.execute(
            """
            SELECT table_schema, table_name, table_type
            FROM information_schema.tables
            WHERE table_schema <> ALL(%s)
              AND table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY table_schema, table_name
            LIMIT 500
            """,
            (list(SYSTEM_SCHEMAS),),
        ).fetchall():
            tables.append(
                PostgresTableMetadata(
                    schema=schema_name,
                    name=name,
                    table_type=table_type,
                    columns=_columns(connection, schema_name, name),
                )
            )
        return PostgresCatalog(schemas=schemas, tables=tables)


def inspect_table(config: PostgresSourceConfig, table: PostgresTableRef) -> PostgresTableMetadata:
    with _connect(config) as connection:
        row = connection.execute(
            """
            SELECT table_type
            FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s AND table_type IN ('BASE TABLE', 'VIEW')
            """,
            (table.schema_name, table.table),
        ).fetchone()
        if row is None:
            raise PostgresSourceError("The requested table was not found in a non-system schema.")
        return PostgresTableMetadata(
            schema=table.schema_name,
            name=table.table,
            table_type=row[0],
            columns=_columns(connection, table.schema_name, table.table),
        )


def import_source(request: PostgresImportRequest) -> ImportedDataset:
    if (request.table is None) == (request.select_sql is None):
        raise PostgresSourceError("Provide either a table reference or a single bounded SELECT statement.")
    max_rows = min(request.max_rows or DEFAULT_MAX_ROWS, MAX_DATASET_ROWS)
    query, fingerprint_sql = _query_for_request(request, max_rows)
    with _connect(request.source) as connection:
        try:
            with connection.cursor() as cursor:
                cursor.execute(query)
                columns = [item.name for item in cursor.description or []]
                rows = cursor.fetchmany(max_rows + 1)
        except psycopg.errors.ReadOnlySqlTransaction as exc:
            raise PostgresSourceError("The external PostgreSQL session is read-only.") from exc
        except psycopg.Error as exc:
            raise PostgresSourceError("The bounded read failed.") from exc
    if len(rows) > max_rows:
        raise PostgresSourceError(f"The result exceeded the {max_rows}-row import limit.")
    frame = pd.DataFrame(list(rows), columns=columns)
    identity = (
        f"postgres://{request.source.host}:{request.source.port}/{request.source.database}"
        f"/{request.table.schema_name}.{request.table.table}"
        if request.table
        else f"postgres://{request.source.host}:{request.source.port}/{request.source.database}#select"
    )
    provenance = DatasetProvenance(
        source_type="postgres",
        identity=identity,
        display_name=request.table.table if request.table else "bounded_select",
        retrieved_at=datetime.now(timezone.utc),
        config_fingerprint=_fingerprint(request.source, fingerprint_sql),
        row_count=len(frame),
        details={
            "host": request.source.host,
            "port": request.source.port,
            "database": request.source.database,
            "schema": request.table.schema_name if request.table else None,
            "table": request.table.table if request.table else None,
            "query_fingerprint": sha256(fingerprint_sql.encode()).hexdigest(),
            "password_secret_ref": request.source.password_secret_ref,
        },
    )
    dataset = loaded_from_frame("postgres_import.csv", "csv", frame, provenance)
    filename, media_type, content = _csv_bytes(dataset.filename, frame)
    return ImportedDataset(
        inspection=inspect_dataset(dataset),
        profile=profile_dataset(dataset),
        provenance=provenance,
        dataset=DatasetPayload(filename=filename, media_type=media_type, content_base64=_b64(content)),
    )


def _query_for_request(request: PostgresImportRequest, max_rows: int) -> tuple[sql.Composed | str, str]:
    if request.table is not None:
        composed = sql.SQL("SELECT * FROM {}.{} LIMIT {}").format(
            sql.Identifier(request.table.schema_name),
            sql.Identifier(request.table.table),
            sql.Literal(max_rows),
        )
        return composed, f"SELECT * FROM {request.table.schema_name}.{request.table.table} LIMIT {max_rows}"
    assert request.select_sql is not None
    validated = validate_select(request.select_sql)
    wrapped = f"SELECT * FROM ({validated}) AS bounded_source LIMIT {max_rows}"
    return wrapped, wrapped


def validate_select(statement: str) -> str:
    cleaned = _strip_sql_comments(statement).strip().rstrip(";").strip()
    if not cleaned:
        raise PostgresSourceError("The SELECT statement is empty.")
    if ";" in cleaned:
        raise PostgresSourceError("Multiple SQL statements are not allowed.")
    if FORBIDDEN_SQL.search(cleaned) or LOCKING_SELECT.search(cleaned):
        raise PostgresSourceError("The statement is not a permitted read-only SELECT.")
    if not re.match(r"^(WITH|SELECT)\b", cleaned, re.IGNORECASE):
        raise PostgresSourceError("Only a single WITH/SELECT statement is allowed.")
    return cleaned


def _strip_sql_comments(statement: str) -> str:
    without_block = re.sub(r"/\*.*?\*/", " ", statement, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", " ", without_block)


def _columns(connection, schema_name: str, table: str) -> list[PostgresColumnMetadata]:
    primary = {
        item[0]
        for item in connection.execute(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = %s AND tc.table_name = %s
            """,
            (schema_name, table),
        ).fetchall()
    }
    columns = []
    for name, data_type, nullable in connection.execute(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        LIMIT 500
        """,
        (schema_name, table),
    ).fetchall():
        columns.append(
            PostgresColumnMetadata(
                name=name,
                data_type=data_type,
                nullable=nullable == "YES",
                is_primary_key=name in primary,
            )
        )
    return columns


def _connect(config: PostgresSourceConfig):
    try:
        password = resolve_secret(config.password_secret_ref)
    except SecretError as exc:
        raise PostgresSourceError(str(exc)) from exc
    try:
        connection = psycopg.connect(
            host=config.host,
            port=config.port,
            dbname=config.database,
            user=config.user,
            password=password,
            sslmode=config.sslmode,
            connect_timeout=config.connect_timeout_seconds,
            autocommit=True,
        )
    except psycopg.Error as exc:
        raise PostgresSourceError("Could not connect to the external PostgreSQL source.") from exc
    try:
        connection.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        connection.execute("SET default_transaction_read_only = on")
        connection.execute("SET statement_timeout = %s", (STATEMENT_TIMEOUT_MS,))
        connection.execute("BEGIN READ ONLY")
    except psycopg.Error as exc:
        connection.close()
        raise PostgresSourceError("Could not establish a read-only PostgreSQL session.") from exc
    return connection


def _fingerprint(config: PostgresSourceConfig, query: str) -> str:
    payload = {
        "host": config.host,
        "port": config.port,
        "database": config.database,
        "user": config.user,
        "sslmode": config.sslmode,
        "password_secret_ref": config.password_secret_ref,
        "query": query,
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _csv_bytes(filename: str, frame: pd.DataFrame) -> tuple[str, str, bytes]:
    return filename, "text/csv", frame.to_csv(index=False).encode("utf-8")


def _b64(content: bytes) -> str:
    import base64

    return base64.b64encode(content).decode("ascii")
