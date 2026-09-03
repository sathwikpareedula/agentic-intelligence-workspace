"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.health import router as health_router

app = FastAPI(title="Agentic Intelligence Workspace")
app.include_router(health_router)

