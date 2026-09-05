"""Download boundary for process-local generated artifacts."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.config import Settings, get_settings
from app.dependencies import get_artifact_repository
from app.repositories.documents import RepositoryError
from app.services.artifacts import ArtifactRepository

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}")
def download_artifact(
    artifact_id: UUID,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> Response:
    repository: ArtifactRepository | None = getattr(request.app.state, "artifact_repository", None)
    repository = repository or get_artifact_repository(settings)
    try:
        artifact = repository.get(artifact_id)
    except RepositoryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact was not found or has expired.")
    return Response(
        content=artifact.content,
        media_type=artifact.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{_safe_download_name(artifact.filename)}"',
            "X-Artifact-Id": str(artifact.artifact_id),
            "X-Artifact-Rows": str(artifact.row_count),
            "X-Artifact-Columns": str(artifact.column_count),
        },
    )


def _safe_download_name(filename: str) -> str:
    return "".join(character if character.isalnum() or character in "._-" else "_" for character in filename)[:255]
