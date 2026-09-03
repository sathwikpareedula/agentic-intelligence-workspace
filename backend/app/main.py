"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.datasets import router as datasets_router
from app.api.health import router as health_router

app = FastAPI(title="Agentic Intelligence Workspace")
app.include_router(health_router)
app.include_router(datasets_router)
