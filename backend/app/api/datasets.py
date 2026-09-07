"""Dataset inspection and profiling API endpoints."""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.models.datasets import DatasetInspection, DatasetProfile
from app.services.datasets import (
    MAX_UPLOAD_BYTES,
    DatasetReadError,
    DatasetTooLargeError,
    UnsupportedFileTypeError,
    inspect_dataset,
    load_dataset,
    profile_dataset,
)

router = APIRouter(prefix="/datasets", tags=["datasets"])


async def _read_upload(file: UploadFile, sheet: str | None, records_key: str | None = None):
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        return load_dataset(file.filename or "", content, sheet, records_key)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)) from exc
    except DatasetTooLargeError as exc:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)) from exc
    except DatasetReadError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    finally:
        await file.close()


@router.post("/inspect", response_model=DatasetInspection)
async def inspect_uploaded_dataset(
    file: UploadFile = File(...),
    sheet: str | None = Form(default=None),
    records_key: str | None = Form(default=None),
) -> DatasetInspection:
    dataset = await _read_upload(file, sheet, records_key)
    return inspect_dataset(dataset)


@router.post("/profile", response_model=DatasetProfile)
async def profile_uploaded_dataset(
    file: UploadFile = File(...),
    sheet: str | None = Form(default=None),
    records_key: str | None = Form(default=None),
) -> DatasetProfile:
    dataset = await _read_upload(file, sheet, records_key)
    return profile_dataset(dataset)
