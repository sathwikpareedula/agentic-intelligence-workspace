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
from app.services.datasets import (
    MAX_DATASET_COLUMNS,
    MAX_DATASET_ROWS,
    inspect_dataset,
    loaded_from_frame,
    profile_dataset,
)
from app.services.secrets import SecretError, resolve_secret

SYSTEM_SCHEMAS = {"pg_catalog", "information_schema", "pg_toast"}
FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|COPY|CALL|DO|"
    r"EXECUTE|SECURITY|LOAD|LISTEN|NOTIFY|UNLISTEN|LOCK|VACUUM|ANALYZE|CLUSTER|REINDEX|REFRESH|"
    r"RESET|SHOW|EXPLAIN|PREPARE|DEALLOCATE|DISCARD|FETCH|MOVE|CLOSE|DECLARE|INTO|OUTFILE|"
    r"DUMPFILE|PROGRAM|SET|COMMENT|REASSIGN|OWNER|RULE|TRIGGER|POLICY|PUBLICATION|SUBSCRIPTION|"
    r"CHECKPOINT|COMMIT|ROLLBACK|SAVEPOINT|BEGIN|START|pg_read_file|pg_write_file|"
    r"pg_read_binary_file|pg_ls_dir|pg_stat_file|pg_terminate_backend|pg_cancel_backend|"
    r"pg_reload_conf|pg_sleep|pg_advisory_[A-Za-z0-9_]*|pg_export_snapshot|"
    r"pg_log_backend_memory_contexts|pg_promote|pg_rotate_logfile|pg_backup_start|pg_backup_stop|"
    r"pg_switch_wal|pg_create_restore_point|current_setting|set_config|dblink|lo_[A-Za-z0-9_]*)\b",
    re.IGNORECASE,
)
SYSTEM_OBJECT_SQL = re.compile(r"(?:pg_catalog|information_schema|pg_toast)", re.IGNORECASE)
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
        row = connection.execute(
            "SELECT current_database() AS database, pg_is_in_recovery() AS replica, "
            "current_setting('transaction_read_only') AS transaction_read_only"
        ).fetchone()
        assert row is not None
        if row[2] != "on":
            raise PostgresSourceError("The external PostgreSQL connection did not enter a read-only transaction.")
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
    _require_user_schema(table.schema_name)
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
    if request.table is not None:
        _require_user_schema(request.table.schema_name)
    query, fingerprint_sql = _query_for_request(request, max_rows)
    with _connect(request.source) as connection:
        try:
            with connection.cursor() as cursor:
                cursor.execute(query)
                columns = [item.name for item in cursor.description or []]
                if len(columns) > MAX_DATASET_COLUMNS:
                    raise PostgresSourceError(
                        f"The result exceeded the {MAX_DATASET_COLUMNS}-column import limit."
                    )
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
    cleaned, code = _lex_sql(statement)
    if not cleaned:
        raise PostgresSourceError("The SELECT statement is empty.")
    if FORBIDDEN_SQL.search(code) or LOCKING_SELECT.search(code) or SYSTEM_OBJECT_SQL.search(code):
        raise PostgresSourceError("The statement is not a permitted read-only SELECT.")
    if re.search(r"\bWITH\s+RECURSIVE\b", code, re.IGNORECASE):
        raise PostgresSourceError("Recursive CTEs are not allowed in bounded external reads.")
    if not re.match(r"^(WITH|SELECT)\b", code.strip(), re.IGNORECASE):
        raise PostgresSourceError("Only a single WITH/SELECT statement is allowed.")
    return cleaned


def _lex_sql(statement: str) -> tuple[str, str]:
    """Remove comments and mask literals while enforcing one SQL statement.

    This is deliberately a lexical defense-in-depth check, not a PostgreSQL
    semantic parser. The read-only transaction and least-privilege source role
    remain the final database safety boundary.
    """

    cleaned: list[str] = []
    code: list[str] = []
    semicolons: list[int] = []
    index = 0
    length = len(statement)
    while index < length:
        char = statement[index]
        following = statement[index + 1] if index + 1 < length else ""
        if char == "-" and following == "-":
            index += 2
            while index < length and statement[index] not in "\r\n":
                index += 1
            cleaned.append(" ")
            code.append(" ")
            continue
        if char == "/" and following == "*":
            depth = 1
            index += 2
            while index < length and depth:
                pair = statement[index : index + 2]
                if pair == "/*":
                    depth += 1
                    index += 2
                elif pair == "*/":
                    depth -= 1
                    index += 2
                else:
                    index += 1
            if depth:
                raise PostgresSourceError("The SELECT statement contains an unterminated block comment.")
            cleaned.append(" ")
            code.append(" ")
            continue
        if char == "'":
            start = index
            index += 1
            while index < length:
                if statement[index] == "'":
                    if index + 1 < length and statement[index + 1] == "'":
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            else:
                raise PostgresSourceError("The SELECT statement contains an unterminated string literal.")
            literal = statement[start:index]
            cleaned.append(literal)
            code.append(" " * len(literal))
            continue
        if char == "$":
            match = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", statement[index:])
            if match:
                delimiter = match.group(0)
                end = statement.find(delimiter, index + len(delimiter))
                if end < 0:
                    raise PostgresSourceError("The SELECT statement contains an unterminated dollar-quoted literal.")
                end += len(delimiter)
                literal = statement[index:end]
                cleaned.append(literal)
                code.append(" " * len(literal))
                index = end
                continue
        if char == ";":
            semicolons.append(sum(len(part) for part in cleaned))
        cleaned.append(char)
        code.append(char)
        index += 1

    cleaned_sql = "".join(cleaned).strip()
    code_sql = "".join(code).strip()
    if semicolons:
        without_trailing = cleaned_sql.rstrip()
        if len(semicolons) != 1 or not without_trailing.endswith(";"):
            raise PostgresSourceError("Multiple SQL statements are not allowed.")
        cleaned_sql = without_trailing[:-1].rstrip()
        code_sql = code_sql.rstrip()
        if code_sql.endswith(";"):
            code_sql = code_sql[:-1].rstrip()
    return cleaned_sql, code_sql


def _require_user_schema(schema_name: str) -> None:
    lowered = schema_name.casefold()
    if lowered in SYSTEM_SCHEMAS or lowered.startswith("pg_"):
        raise PostgresSourceError("System PostgreSQL schemas are not available through table imports.")


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
        connection.execute("SELECT set_config('statement_timeout', %s, false)", (str(STATEMENT_TIMEOUT_MS),))
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
