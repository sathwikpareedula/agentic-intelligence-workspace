# Project Log

This log records verified project progress. Planned work should not be presented as completed work.

## Current Status

Bounded execution, mixed reasoning, verification, workflows, artifacts, sales and Transform-to-Template demos, durable persistence, production provider integration, generalized task-scoped orchestration, and the frontend foundation are implemented and verified where noted below.

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
- 2026-09-04: Added an environment-configured OpenAI-compatible Responses adapter with strict structured decisions, bounded output, SDK retries, timeouts, stable safe errors, and explicit demo/configured/unavailable runtime status.
- 2026-09-04: Generalized the one orchestrator with task-scoped dataset, retrieval, join, aggregation, artifact-export, and saved-workflow tools while keeping deterministic services responsible for data and numeric work.
- 2026-09-04: Added controlled generalized-agent evaluation and tests for malformed provider output, timeout/failure mapping, invalid arguments, replanning, iteration limits, mixed structured/unstructured tasks, artifacts, workflows, and insufficient evidence.
- 2026-09-06: Added Transform-to-Template V1 with typed CSV/XLSX target inspection, source profiling/key candidates, deterministic mapping proposals, structured clarification/refusal, guarded joins and derivations, evidence-bound policy rates, exact template writing/reopen validation, per-field provenance, reusable drift-checked workflows, task-scoped agent tools, public multipart APIs, focused frontend workflow, canonical fixtures, and an 18-case controlled evaluation.
- 2026-09-07: Completed Phase 1 Transform-to-Template integration with user-confirmed mapping controls, fixture-scoped demo rules, formula-origin-aware translation and reopen verification, confirmed mapping persistence, CI evaluation coverage, responsive browser QA, and final backend/frontend/security gates.

## Technologies Actually Used

- Markdown for project documentation.
- Git for version control repository structure.
- Python with a project virtual environment for backend development and verification.
- FastAPI for the backend application foundation.
- Pydantic for the typed health response model.
- Uvicorn for local ASGI application verification.
- pytest and HTTPX for health endpoint testing.
- pandas for deterministic tabular ingestion, inspection, and profiling.
- openpyxl for bounded `.xlsx` workbook inspection, preservation, formula translation, and new artifact generation.
- python-multipart for bounded FastAPI file-upload request parsing.
- pypdf for non-executing PDF text extraction.
- psycopg and pgvector for the production-intended PostgreSQL vector repository.
- OpenAI SDK for configured hosted embedding and Responses-based orchestration providers.

Add technologies here only after they are actually used in the project.

## Architecture Decisions

- Prefer one orchestrator with typed deterministic tools for the initial architecture.
- Keep calculations, transformations, joins, statistics, and schema checks in deterministic code.
- Defer implementation technology adoption until its milestone requires it.
- Defer DuckDB and SQL execution because the current typed pandas operations satisfy the bounded analytics scope without introducing another query and security boundary.
- Use PostgreSQL with pgvector as the retrieval store, exact cosine search initially, and interfaces for both vector storage and embedding providers.
- Use one task-scoped orchestrator with strictly structured provider decisions; do not expose uploaded bodies or add arbitrary execution to gain generality.

Material decisions should receive a record under `docs/decisions/`.

## Bugs and Problems Solved

- Removed known frontend dependency advisories by upgrading to the audit-recommended patched Next.js release and re-verifying the production build.

## Evaluation Results

- Backend test suite: 132 tests passed, 1 opt-in live PostgreSQL integration test skipped, and 2 framework deprecation warnings were reported.
- Controlled offline retrieval evaluation: 5 queries at `top_k=2`, Hit@2 = 1.0 and mean reciprocal rank = 1.0. This measures the fixed token-hash test corpus, not hosted embedding quality or production recall.
- Controlled product evaluation: 7/7 cases passed. Controlled scripted-provider agent evaluation: 5/5 cases passed. Controlled north-star evaluation: 14/14 cases passed. Controlled Transform-to-Template evaluation: 18/18 cases passed. These offline evaluations do not measure hosted-model quality, latency, or cost.
- Frontend verification: TypeScript passed, the Next.js 16.3.4 optimized production build passed, and `npm audit --audit-level=high` reported zero vulnerabilities without changing `package.json` or `package-lock.json`.
- Browser verification: the canonical Transform-to-Template fixture completed through the live local UI with proposal visibility, 13 passing validation checks, policy provenance, workbook download, and saved-workflow visibility; the narrow responsive layout was visually checked.
- Workbook verification: the generated canonical artifact reopened in both the backend validation and the spreadsheet inspection runtime, preserved both sheets and their order, retained translated formulas in `F2:F4`, neutralized the formula-like customer value, and rendered both worksheets for visual review.
- No real orchestrator request was run because neither `ORCHESTRATOR_API_KEY` nor `OPENAI_API_KEY` was available.
- Docker configuration was added but could not be executed or validated because Docker is unavailable in this environment.

## Performance Results

No performance measurements have been run yet.

## Security Decisions

- Security risks and design requirements are tracked from the engineering-foundation phase.
- Dataset uploads are limited to 10 MiB, processed in memory without permanent persistence, restricted to `.csv` and `.xlsx`, and parsed without executing formulas, macros, or uploaded code.
- Transformation requests use a closed typed operation set with unknown fields rejected; no arbitrary Python or SQL execution is available.
- Exported artifacts remain request-scoped in memory and use service-generated sanitized filenames rather than user-controlled filesystem paths.
- Formula-like text is neutralized during CSV/XLSX export to prevent uploaded strings from becoming active spreadsheet formulas.
- Transform templates reject macro-enabled formats, unsafe XLSX archive paths, oversized/over-complex workbook structures, embedded or externally linked active content, and external/active formulas. Untrusted source formula strings remain neutralized while supported local target formulas are preserved and translated.
- PDF content is bounded and treated as untrusted evidence data; it is never executed or treated as system instructions.
- Retrieval credentials come from environment variables; API responses preserve document/page/chunk provenance and never fabricate citations.
- Orchestrator keys, model, base URL, timeout, retry count, and output bound come from environment configuration. Credential-bearing base URLs are rejected, file bodies and secret-like arguments are redacted, and provider failures expose only stable safe messages.

## What I Learned

- Repository location must be verified before implementation begins. The repository was moved while an earlier coding-agent workspace still referenced the obsolete path, causing Phase 0B to initially be created outside the canonical Git repository. The verified backend source was recovered into the canonical repository.

## Resume-Earned Skills

Skills should only be added here once they have been actually implemented, exercised, and understood—not merely planned, discussed, or listed as a future technology.
