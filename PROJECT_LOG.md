# Project Log

This log records verified project progress. Planned work should not be presented as completed work.

## Current Status

Milestone 1A: deterministic structured-data ingestion and profiling foundation verified. The backend accepts bounded in-memory CSV and XLSX uploads for typed inspection and basic profiling.

## Milestone History

- 2026-09-02: Created the initial project documentation and empty implementation directories.
- 2026-09-02: Completed and verified the Phase 0B backend foundation: a FastAPI application, Pydantic `HealthResponse`, and `GET /health` returning `{"status":"ok"}`.
- 2026-09-02: Added pytest coverage for the health endpoint and verified 1 passing test.
- 2026-09-02: Successfully verified the backend locally with Uvicorn using the project Python virtual environment.
- 2026-09-02: Configured backend runtime and test dependencies in `backend/pyproject.toml`.
- 2026-09-02: Added deterministic CSV and XLSX ingestion with extension validation, clean parse errors, a 10 MiB upload limit, and optional Excel sheet selection.
- 2026-09-02: Added typed `POST /datasets/inspect` and `POST /datasets/profile` APIs for dataset metadata, missing values, duplicates, numeric summaries, and categorical frequencies.
- 2026-09-02: Verified the complete backend suite with 13 passing tests and manually verified the dataset and health APIs through local Uvicorn.

## Technologies Actually Used

- Markdown for project documentation.
- Git for version control repository structure.
- Python with a project virtual environment for backend development and verification.
- FastAPI for the backend application foundation.
- Pydantic for the typed health response model.
- Uvicorn for local ASGI application verification.
- pytest and HTTPX for health endpoint testing.
- pandas for deterministic tabular ingestion, inspection, and profiling.
- openpyxl for read-only, data-only `.xlsx` workbook ingestion.
- python-multipart for bounded FastAPI file-upload request parsing.

Add technologies here only after they are actually used in the project.

## Architecture Decisions

- Prefer one orchestrator with typed deterministic tools for the initial architecture.
- Keep calculations, transformations, joins, statistics, and schema checks in deterministic code.
- Defer implementation technology adoption until its milestone requires it.

Material decisions should receive a record under `docs/decisions/`.

## Bugs and Problems Solved

None yet.

## Evaluation Results

- Backend test suite: 13 tests passed, covering health, CSV and XLSX ingestion, sheet behavior, inspection, profiling, malformed and unsupported inputs, empty datasets, and upload-size enforcement.

## Performance Results

No performance measurements have been run yet.

## Security Decisions

- Security risks and design requirements are tracked from the engineering-foundation phase.
- Dataset uploads are limited to 10 MiB, processed in memory without permanent persistence, restricted to `.csv` and `.xlsx`, and parsed without executing formulas, macros, or uploaded code.

## What I Learned

- Repository location must be verified before implementation begins. The repository was moved while an earlier coding-agent workspace still referenced the obsolete path, causing Phase 0B to initially be created outside the canonical Git repository. The verified backend source was recovered into the canonical repository.

## Resume-Earned Skills

Skills should only be added here once they have been actually implemented, exercised, and understood—not merely planned, discussed, or listed as a future technology.
