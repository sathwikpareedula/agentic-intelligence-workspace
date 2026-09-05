"""Filesystem artifact bodies with PostgreSQL metadata and integrity checks."""

from hashlib import sha256
import os
from pathlib import Path
import re
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from app.repositories.documents import RepositoryError
from app.services.artifacts import GeneratedArtifact


class LocalArtifactStore:
    """Store artifact bytes under server-generated keys inside one configured root."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        if not self._root.is_dir():
            raise RepositoryError("Artifact storage path is not a directory.")

    @property
    def root(self) -> Path:
        return self._root

    def save(self, artifact_id: UUID, content: bytes) -> tuple[str, str, bool]:
        key = f"{artifact_id.hex}.bin"
        target = self._safe_path(key)
        digest = sha256(content).hexdigest()
        if target.exists():
            existing = self.load(key)
            if sha256(existing).hexdigest() != digest:
                raise RepositoryError("Artifact ID already exists with different content.")
            return key, digest, False
        temporary = self._safe_path(f"{artifact_id.hex}.tmp")
        try:
            temporary.write_bytes(content)
            os.replace(temporary, target)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise RepositoryError("Could not write artifact content.") from exc
        return key, digest, True

    def load(self, key: str) -> bytes:
        try:
            return self._safe_path(key).read_bytes()
        except OSError as exc:
            raise RepositoryError("Could not read artifact content.") from exc

    def delete(self, key: str) -> None:
        try:
            self._safe_path(key).unlink(missing_ok=True)
        except OSError:
            pass

    def _safe_path(self, key: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}\.(?:bin|tmp)", key):
            raise RepositoryError("Artifact storage metadata contains an invalid key.")
        candidate = (self._root / key).resolve()
        if candidate.parent != self._root:
            raise RepositoryError("Artifact storage path escaped the configured root.")
        return candidate


class PostgresArtifactRepository:
    def __init__(self, database_url: str, store: LocalArtifactStore, connect_timeout_seconds: int = 3) -> None:
        self._database_url = database_url
        self._store = store
        self._connect_timeout_seconds = connect_timeout_seconds

    def save(self, artifact: GeneratedArtifact) -> None:
        key, digest, created = self._store.save(artifact.artifact_id, artifact.content)
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO artifacts
                        (id, filename, artifact_type, media_type, row_count, column_count,
                         storage_key, size_bytes, content_sha256, producing_task_id,
                         producing_workflow_id, producing_run_id, verification_status,
                         provenance, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        filename = EXCLUDED.filename,
                        artifact_type = EXCLUDED.artifact_type,
                        media_type = EXCLUDED.media_type,
                        row_count = EXCLUDED.row_count,
                        column_count = EXCLUDED.column_count,
                        storage_key = EXCLUDED.storage_key,
                        size_bytes = EXCLUDED.size_bytes,
                        content_sha256 = EXCLUDED.content_sha256,
                        producing_task_id = EXCLUDED.producing_task_id,
                        producing_workflow_id = EXCLUDED.producing_workflow_id,
                        producing_run_id = EXCLUDED.producing_run_id,
                        verification_status = EXCLUDED.verification_status,
                        provenance = EXCLUDED.provenance
                    """,
                    (
                        artifact.artifact_id,
                        artifact.filename,
                        artifact.format,
                        artifact.media_type,
                        artifact.row_count,
                        artifact.column_count,
                        key,
                        len(artifact.content),
                        digest,
                        artifact.producing_task_id,
                        artifact.producing_workflow_id,
                        artifact.producing_run_id,
                        artifact.verification_status,
                        Jsonb(artifact.provenance) if artifact.provenance is not None else None,
                        artifact.created_at,
                    ),
                )
        except psycopg.Error as exc:
            if created:
                self._store.delete(key)
            raise RepositoryError("Could not persist artifact metadata.") from exc

    def get(self, artifact_id: UUID) -> GeneratedArtifact | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT filename, artifact_type, media_type, row_count, column_count,
                           storage_key, size_bytes, content_sha256, producing_task_id,
                           producing_workflow_id, producing_run_id, verification_status,
                           provenance, created_at
                    FROM artifacts WHERE id = %s
                    """,
                    (artifact_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise RepositoryError("Could not load artifact metadata.") from exc
        if row is None:
            return None
        content = self._store.load(row[5])
        if len(content) != row[6] or sha256(content).hexdigest() != row[7]:
            raise RepositoryError("Artifact content failed its integrity check.")
        return GeneratedArtifact(
            filename=row[0],
            format=row[1],
            media_type=row[2],
            row_count=row[3],
            column_count=row[4],
            content=content,
            artifact_id=artifact_id,
            created_at=row[13],
            producing_task_id=row[8],
            producing_workflow_id=row[9],
            producing_run_id=row[10],
            verification_status=row[11],
            provenance=row[12],
        )

    def link_to_execution(self, artifact_ids: list[UUID], task_id: UUID, verification_status: str) -> None:
        if not artifact_ids:
            return
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE artifacts
                    SET producing_task_id = %s, producing_run_id = %s, verification_status = %s
                    WHERE id = ANY(%s)
                    """,
                    (task_id, task_id, verification_status, artifact_ids),
                )
        except psycopg.Error as exc:
            raise RepositoryError("Could not link artifacts to execution provenance.") from exc

    def link_to_workflow(self, artifact_ids: list[UUID], workflow_id: UUID, run_id: UUID) -> None:
        if not artifact_ids:
            return
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE artifacts
                    SET producing_workflow_id = %s, producing_run_id = %s
                    WHERE id = ANY(%s)
                    """,
                    (workflow_id, run_id, artifact_ids),
                )
        except psycopg.Error as exc:
            raise RepositoryError("Could not link artifacts to workflow provenance.") from exc

    def _connect(self):
        return psycopg.connect(self._database_url, connect_timeout=self._connect_timeout_seconds)
