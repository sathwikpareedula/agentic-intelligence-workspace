# Project Log

This log records verified project progress. Planned work should not be presented as completed work.

## Current Status

Milestones 3-9 foundation: bounded execution, mixed reasoning, verification, workflows, artifacts, sales demo, frontend foundation, and productization implemented and verified where noted below.

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
- 2026-09-02: Added bounded in-memory PDF text extraction, deterministic overlapping page chunks, and stable content-derived document/chunk identifiers with explicit no-OCR behavior.
- 2026-09-02: Added a batched OpenAI embedding provider behind a tested interface and PostgreSQL/pgvector storage using exact cosine similarity, document filtering, and source provenance.
- 2026-09-02: Added `POST /documents` and `POST /retrieval/search`; retrieval returns ranked evidence with document, filename, page, and chunk citations and does not generate answers.
- 2026-09-02: Verified 43 backend tests, a live fake-backed PDF ingestion/search flow through Uvicorn, and a controlled three-query retrieval evaluation with Hit@2 and MRR.
- 2026-09-03: Added the bounded orchestrator, strict tools, deterministic fake model, recoverable observations, trace provenance/timing, and agent API boundary.
- 2026-09-03: Added grades/syllabus mixed reasoning, evidence-based verification, versioned recipes with schema drift, management artifacts/charts, and the known-ground-truth August sales demo.
- 2026-09-03: Added a Next.js workspace foundation; TypeScript and the optimized production build passed. Browser interaction verification remains pending.
- 2026-09-03: Added Docker service composition, CI, request IDs/logging, CORS, and readiness behavior.
- 2026-09-03: Upgraded the frontend to Next.js 16.3.4 after `npm audit` identified transitive PostCSS advisories; the repeat audit reported zero vulnerabilities and typecheck/build passed.

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
- pypdf for non-executing PDF text extraction.
- psycopg and pgvector for the production-intended PostgreSQL vector repository.
- OpenAI SDK for the configured hosted embedding-provider implementation.

Add technologies here only after they are actually used in the project.

## Architecture Decisions

- Prefer one orchestrator with typed deterministic tools for the initial architecture.
- Keep calculations, transformations, joins, statistics, and schema checks in deterministic code.
- Defer implementation technology adoption until its milestone requires it.
- Defer DuckDB and SQL execution because the current typed pandas operations satisfy the bounded analytics scope without introducing another query and security boundary.
- Use PostgreSQL with pgvector as the retrieval store, exact cosine search initially, and interfaces for both vector storage and embedding providers.

Material decisions should receive a record under `docs/decisions/`.

## Bugs and Problems Solved

- Removed known frontend dependency advisories by upgrading to the audit-recommended patched Next.js release and re-verifying the production build.

## Evaluation Results

- Backend test suite: 67 tests passed across structured data, retrieval, orchestration, mixed reasoning, verification, workflows, artifacts, sales evaluation, and API behavior.
- Controlled offline retrieval evaluation: 3 queries at `top_k=2`, Hit@2 = 1.0 and mean reciprocal rank = 1.0. This measures the fixed token-hash test corpus, not hosted embedding quality or production recall.
- Frontend verification: TypeScript passed, Next.js 16.3.4 optimized production build passed, and `npm audit` reported zero vulnerabilities.
- Docker configuration was added but could not be executed or validated because Docker is unavailable in this environment.
- Browser interaction QA could not run because no controllable browser was available; this remains explicitly pending despite successful frontend build verification.

## Performance Results

No performance measurements have been run yet.

## Security Decisions

- Security risks and design requirements are tracked from the engineering-foundation phase.
- Dataset uploads are limited to 10 MiB, processed in memory without permanent persistence, restricted to `.csv` and `.xlsx`, and parsed without executing formulas, macros, or uploaded code.
- Transformation requests use a closed typed operation set with unknown fields rejected; no arbitrary Python or SQL execution is available.
- Exported artifacts remain request-scoped in memory and use service-generated sanitized filenames rather than user-controlled filesystem paths.
- Formula-like text is neutralized during CSV/XLSX export to prevent uploaded strings from becoming active spreadsheet formulas.
- PDF content is bounded and treated as untrusted evidence data; it is never executed or treated as system instructions.
- Retrieval credentials come from environment variables; API responses preserve document/page/chunk provenance and never fabricate citations.

## What I Learned

- Repository location must be verified before implementation begins. The repository was moved while an earlier coding-agent workspace still referenced the obsolete path, causing Phase 0B to initially be created outside the canonical Git repository. The verified backend source was recovered into the canonical repository.

## Resume-Earned Skills

Skills should only be added here once they have been actually implemented, exercised, and understood—not merely planned, discussed, or listed as a future technology.
