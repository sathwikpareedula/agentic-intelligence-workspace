"""Health endpoint."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    """Response returned when the API process is healthy."""

    status: Literal["ok"]


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Report that the API process is available."""

    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse)
def get_readiness() -> HealthResponse:
    """Report process readiness; external providers are checked at operation time."""
    return HealthResponse(status="ok")
