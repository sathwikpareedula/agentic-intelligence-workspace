"""Read-only PostgreSQL and schema readiness probes."""

from dataclasses import dataclass

import psycopg


MIGRATION_HEAD = "20260909_0004"
REQUIRED_TABLES = (
    "documents",
    "document_chunks",
    "workflows",
    "workflow_versions",
    "workflow_runs",
    "artifacts",
    "execution_runs",
)


@dataclass(frozen=True)
class DatabaseProbe:
    database_available: bool
    pgvector_available: bool
    migration_current: bool
    error: str | None = None


def probe_database(database_url: str, timeout_seconds: int = 3) -> DatabaseProbe:
    try:
        with psycopg.connect(database_url, connect_timeout=timeout_seconds) as connection:
            vector_row = connection.execute(
                "SELECT extversion FROM pg_extension WHERE extname = %s", ("vector",)
            ).fetchone()
            revision_row = connection.execute(
                "SELECT to_regclass(%s)", ("public.alembic_version",)
            ).fetchone()
            current_revision = None
            if revision_row and revision_row[0] is not None:
                current_revision_row = connection.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchone()
                current_revision = current_revision_row[0] if current_revision_row else None
            table_rows = connection.execute(
                "SELECT " + ", ".join("to_regclass(%s)" for _ in REQUIRED_TABLES),
                tuple(f"public.{table}" for table in REQUIRED_TABLES),
            ).fetchone()
            tables_present = bool(table_rows and all(table_rows))
            return DatabaseProbe(
                database_available=True,
                pgvector_available=vector_row is not None,
                migration_current=current_revision == MIGRATION_HEAD and tables_present,
            )
    except psycopg.Error:
        return DatabaseProbe(False, False, False, "PostgreSQL is unavailable or rejected the configured credentials.")
