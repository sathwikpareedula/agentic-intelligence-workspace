"""Download boundary for process-local generated artifacts."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.services.artifacts import InMemoryArtifactRepository

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}")
def download_artifact(artifact_id: UUID, request: Request) -> Response:
    repository: InMemoryArtifactRepository | None = getattr(request.app.state, "artifact_repository", None)
    artifact = repository.get(artifact_id) if repository is not None else None
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact was not found or has expired.")
    return Response(
        content=artifact.content,
        media_type=artifact.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "X-Artifact-Id": str(artifact.artifact_id),
            "X-Artifact-Rows": str(artifact.row_count),
            "X-Artifact-Columns": str(artifact.column_count),
        },
    )
