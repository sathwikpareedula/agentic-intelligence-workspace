# Project Log

This log records verified project progress. Planned work should not be presented as completed work.

## Current Status

Milestone 1B: deterministic dataset transformation, analysis, joins, and artifact generation verified through typed APIs and service-layer operations.

## Milestone History

- 2026-09-02: Created the initial project documentation and empty implementation directories.
- 2026-09-02: Completed and verified the Phase 0B backend foundation: a FastAPI application, Pydantic `HealthResponse`, and `GET /health` returning `{"status":"ok"}`.
- 2026-09-02: Added pytest coverage for the health endpoint and verified 1 passing test.
- 2026-09-02: Successfully verified the backend locally with Uvicorn using the project Python virtual environment.
- 2026-09-02: Configured backend runtime and test dependencies in `backend/pyproject.toml`.
- 2026-09-02: Added deterministic CSV and XLSX ingestion with extension validation, clean parse errors, a 10 MiB upload limit, and optional Excel sheet selection.
- 2026-09-02: Added typed `POST /datasets/inspect` and `POST /datasets/profile` APIs for dataset metadata, missing values, duplicates, numeric summaries, and categorical frequencies.
- 2026-09-02: Verified the complete backend suite with 13 passing tests and manually verified the dataset and health APIs through local Uvicorn.
- 2026-09-02: Added typed deterministic selection, filtering, sorting, renaming, deduplication, missing-value handling, restricted arithmetic derivation, grouping, and aggregation.
- 2026-09-02: Added inner, left, right, and outer joins with matched/unmatched counts and explicit repeated-key and many-to-many multiplication diagnostics.
- 2026-09-02: Added in-memory CSV/XLSX artifact generation with safe generated filenames and response metadata.
- 2026-09-02: Verified 28 backend tests and a live inspect, clean, join, aggregate, derive, XLSX export, and artifact read-back workflow through Uvicorn; `GET /health` remained healthy.

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
- Defer DuckDB and SQL execution because the current typed pandas operations satisfy the bounded analytics scope without introducing another query and security boundary.

Material decisions should receive a record under `docs/decisions/`.

## Bugs and Problems Solved

None yet.

## Evaluation Results

- Backend test suite: 28 tests passed, covering health, ingestion, inspection, profiling, transformations, aggregation, all supported join types and diagnostics, validation failures, upload limits, CSV/XLSX artifact read-back, and spreadsheet-formula neutralization.

## Performance Results

No performance measurements have been run yet.

## Security Decisions

- Security risks and design requirements are tracked from the engineering-foundation phase.
- Dataset uploads are limited to 10 MiB, processed in memory without permanent persistence, restricted to `.csv` and `.xlsx`, and parsed without executing formulas, macros, or uploaded code.
- Transformation requests use a closed typed operation set with unknown fields rejected; no arbitrary Python or SQL execution is available.
- Exported artifacts remain request-scoped in memory and use service-generated sanitized filenames rather than user-controlled filesystem paths.
- Formula-like text is neutralized during CSV/XLSX export to prevent uploaded strings from becoming active spreadsheet formulas.

## What I Learned

- Repository location must be verified before implementation begins. The repository was moved while an earlier coding-agent workspace still referenced the obsolete path, causing Phase 0B to initially be created outside the canonical Git repository. The verified backend source was recovered into the canonical repository.

## Resume-Earned Skills

Skills should only be added here once they have been actually implemented, exercised, and understood—not merely planned, discussed, or listed as a future technology.
