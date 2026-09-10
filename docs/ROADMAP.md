# Roadmap

The roadmap expresses sequencing, not completed functionality. Milestones should stay bounded and be revised using implementation and evaluation evidence.

## NOW

### Phase 0 — Engineering foundation

- [x] Establish product, architecture, security, roadmap, and decision-record documentation.
- [x] Establish repository guidance and truthful project logging.
- [x] Complete Phase 0B backend foundation with FastAPI and backend dependency configuration in `backend/pyproject.toml`.
- [x] Add a Pydantic `HealthResponse` and `GET /health` returning `{"status":"ok"}`.
- [x] Add pytest health endpoint coverage and verify 1 passing test.
- [x] Verify local Uvicorn startup using the project Python virtual environment.
- [x] Define and verify the bounded ingestion and profiling scope for the first deterministic data milestone.

## NEXT

### Milestone 1 — Deterministic data intelligence

- [x] Define typed contracts for deterministic CSV and XLSX inspection and profiling.
- [x] Implement bounded in-memory CSV and XLSX ingestion with validation and Excel sheet selection.
- [x] Implement deterministic schema inspection, missing-value and duplicate analysis, and basic numeric and categorical profiles.
- [x] Add API and service tests for supported formats, summaries, malformed inputs, empty data, sheet behavior, and upload limits.
- [x] Implement typed deterministic selection, filtering, sorting, renaming, deduplication, missing-value handling, restricted arithmetic derivation, grouping, aggregation, and joins.
- [x] Add join diagnostics for unmatched rows, repeated-key multiplication, and suspicious many-to-many relationships.
- [x] Add request-scoped CSV and XLSX artifact generation with safe filenames and output metadata.
- [x] Add tests for transformation, aggregation, join diagnostics, validation failures, and artifact read-back.
- [ ] Implement broader calculation, validation, provenance, and evaluation behavior.
- [x] Add Transform-to-Template V1 with typed target/source inspection, deterministic mapping proposals, explicit ambiguity/missing/type states, safe joins/derivations, exact CSV/XLSX output, reopen validation, provenance, reusable drift-checked workflows, task-scoped agent tools, a focused UI, canonical fixtures, and an 18-case controlled evaluation.
- [x] Add bounded JSON/Parquet/TXT adapters and read-only PostgreSQL plus GET-only REST connectors with SSRF/SQL safety, secret references, provenance, task-scoped tools, and a dedicated evaluation family.
- [x] Add typed analytical plans, deterministic pandas analytics, validated read-only SQL reuse, numeric facts grounded in the existing verifier, task-scoped tools, a focused UI, and a dedicated analytics evaluation family.
- [x] Add immutable workflow-run lifecycle/history, input and schema fingerprints, persisted facts/verification/artifacts, bounded APIs and task-scoped tools, and deterministic “What Changed?” comparisons with a controlled two-period evaluation.
- [x] Add compact run-quality/step snapshots and deterministic schema, volume, missing, duplicate, category, join, and trust drift deltas in the same comparison API and UI.
- [x] Prove the recurring-workflow lifecycle with a public-API sales scenario spanning two verified periods, a real artifact, deterministic comparison, provenance, and a recorded blocked input.
- Measure correctness, failure behavior, performance, and cost where applicable.

### Milestone 2 — Retrieval and knowledge foundation

- [x] Add bounded PDF text ingestion with explicit no-OCR behavior.
- [x] Add deterministic page-preserving chunking with stable document and chunk identifiers.
- [x] Add a batched embedding-provider interface and hosted OpenAI implementation with offline test doubles.
- [x] Add PostgreSQL/pgvector document and chunk storage with exact cosine retrieval and document filtering.
- [x] Add typed PDF ingestion and ranked evidence-search APIs with document/page/chunk citations.
- [x] Add controlled retrieval evaluation with per-query rankings, Hit@K, and MRR.
- [x] Add Alembic-managed production schema and PostgreSQL persistence for retrieval, workflows, artifacts, and execution provenance.
- [x] Add an opt-in isolated PostgreSQL/pgvector integration test and CI service-container path.
- [x] Verify PostgreSQL/pgvector persistence, exact cosine retrieval, and the bounded source connector against isolated local infrastructure.
- [ ] Verify hosted embeddings against a configured live provider.
- [ ] Add OCR, tenant isolation, retention, connection pooling, and mature production database operations controls.

## LATER

### Milestone 3 — Agentic execution and trustworthy workflows

- [x] Add one bounded orchestrator, fake provider, strict tool registry, replanning observations, and complete traces.
- [x] Implement the mixed grades/PDF calculation with citations and deterministic arithmetic.
- [x] Add numeric/citation verification and conflict/failure/insufficiency states.
- [x] Add versioned recipes with reruns, validation, and schema-drift detection.
- [x] Distinguish immutable workflow definitions from run records and expose run history, blocked/failure diagnostics, compatible-input reruns, and provenance-linked comparison.
- [x] Add artifact provenance, management XLSX generation, and the known-ground-truth August sales flow.
- [x] Add a functional Next.js workspace foundation and local TypeScript verification.
- [x] Add Docker definitions, service composition, CI, request IDs/logging, CORS, and readiness.
- [x] Wire a production OpenAI-compatible orchestrator provider with structured decisions, timeouts, retries, safe errors, and explicit runtime status.
- [x] Add task-scoped generalized dataset, retrieval, join, aggregation, artifact, and workflow tools plus controlled offline agent evaluations.
- [ ] Run broader quality/cost evaluation against configured hosted orchestrator models.
- [x] Add a native loopback-only Ollama provider and checkpointed/resumable product-model evaluation without changing the orchestrator or deterministic tool authority.
- [x] Run the `qwen3.5:4b` fixed-settings compatibility preflight; skip its ten-case benchmark after it fails to return a bounded decision within 60 seconds, and retain no local default rather than weakening the contract.
- [x] Add durable production workflow repositories, artifact metadata/filesystem storage, and artifact download APIs.
- [x] Turn August sales into the recruiter-facing north-star with schema discovery, policy-bound commissions, named-fact verification, join warnings/failures, a polished six-sheet workbook, structured execution stages, and schema-checked reruns.
- [x] Add a dedicated controlled north-star evaluation covering outputs, evidence, failures, artifacts, and reproducibility.
- [x] Complete frontend typecheck and production-build verification.
- [ ] Complete browser interaction and accessibility verification.

The ordering within this section remains subject to dependencies and evaluation evidence.

- Typed tools
- Agent orchestrator
- Mixed structured + unstructured reasoning
- Verification
- Evaluation
- Reusable workflows
- Thin internal UI
- Production Next.js UI
- Docker
- CI/CD
- AWS deployment
- Real-user testing
