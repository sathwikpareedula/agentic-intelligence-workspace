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
- [ ] Implement deterministic transformation, calculation, and broader validation behavior.
- Add tests, evaluation cases, provenance, and artifact output for the milestone.
- Measure correctness, failure behavior, performance, and cost where applicable.

## LATER

The ordering within this section remains subject to dependencies and evaluation evidence.

- Document ingestion and RAG
- PostgreSQL and pgvector
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
