# Architecture

## Status

The implemented backend uses FastAPI and provides `GET /health` plus typed APIs for bounded CSV/XLSX ingestion, inspection, profiling, transformations, joins, aggregation, and in-memory CSV/XLSX artifact generation. These capabilities have pytest coverage. The remaining V1 architecture described below is conceptual and should not be read as implemented.

The frontend will not be built first. Early work will establish deterministic data behavior, contracts, evidence handling, and evaluation before investing in a production interface.

## Intended V1 Shape

```text
Frontend
   ↓
FastAPI
   ↓
Orchestrator
   ↓
Deterministic data tools / Retrieval tools / Verification
   ↓
PostgreSQL + pgvector / File storage
   ↓
Artifacts and trace
```

FastAPI, deterministic structured-data services, and request-scoped tabular artifacts are implemented. The other named technologies and components above remain planned candidates for V1, not current dependencies or implemented services.

## Responsibilities

### Frontend

Provide a thin interaction layer for goals, user confirmations, progress, evidence, traces, and artifact downloads. A thin internal UI is planned before a production Next.js UI.

### API Layer

FastAPI is the implemented API boundary for health checks and typed CSV/XLSX inspection, profiling, transformation, join, and export requests. Authentication, authorization, job interaction, and persistent artifact access remain future work.

### Orchestrator

One orchestrator is preferred initially. It should understand intent, create a bounded plan, select typed tools, interpret results, request clarification when needed, and explain outputs. Multi-agent architecture should be introduced only if future evaluation demonstrates a concrete benefit.

### Deterministic Data Tools

Current deterministic services ingest CSV/XLSX data; inspect and profile datasets; and apply typed selection, filtering, sorting, renaming, deduplication, missing-value handling, restricted arithmetic derivation, grouping, aggregation, and joins. Join diagnostics surface unmatched rows and repeated-key multiplication. Broader calculations, schema checks, and validations remain future work. Inputs and outputs are typed and testable; an LLM is not the computation engine.

### Retrieval Tools

Retrieval should ingest, index, locate, and cite evidence from unstructured documents while preserving source provenance. Retrieval results are evidence candidates, not automatically verified conclusions.

### Verification

Verification should check schemas, tool outputs, evidence coverage, citations, assumptions, and artifact consistency. Missing or conflicting evidence must be surfaced rather than filled in by the model.

### Storage

PostgreSQL and pgvector are intended future storage components for application records and retrieval indexes. File storage is intended for inputs and artifacts. Data isolation, retention, and access policies must be designed before production use.

### Artifacts and Trace

CSV and XLSX tabular artifacts are currently generated in memory with safe generated filenames and response metadata; no persistent artifact store exists. Future trace behavior should record inputs, tool calls, deterministic results, evidence references, decisions, user confirmations, errors, and produced artifacts sufficiently to support inspection and reproducibility. Sensitive data must not be logged indiscriminately.

## Cross-Cutting Requirements

Security, authorization, provenance, observability, testing, evaluation, performance, and cost controls apply across all layers. Exact mechanisms remain to be designed and implemented.
