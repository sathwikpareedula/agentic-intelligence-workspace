# Architecture

## Status

Application code is not implemented yet. This document describes the intended V1 architecture conceptually and does not claim that any component, integration, or control exists.

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

All named technologies and components above are planned candidates for V1, not current dependencies or implemented services.

## Responsibilities

### Frontend

Provide a thin interaction layer for goals, user confirmations, progress, evidence, traces, and artifact downloads. A thin internal UI is planned before a production Next.js UI.

### API Layer

FastAPI is the intended boundary for validated requests, authentication and authorization integration, job interaction, and artifact access. Its contracts will be defined when implementation begins.

### Orchestrator

One orchestrator is preferred initially. It should understand intent, create a bounded plan, select typed tools, interpret results, request clarification when needed, and explain outputs. Multi-agent architecture should be introduced only if future evaluation demonstrates a concrete benefit.

### Deterministic Data Tools

Important calculations, transformations, joins, statistics, schema checks, and validations belong in deterministic tools. Their inputs and outputs should be typed, testable, and traceable. The LLM must not be the computation engine.

### Retrieval Tools

Retrieval should ingest, index, locate, and cite evidence from unstructured documents while preserving source provenance. Retrieval results are evidence candidates, not automatically verified conclusions.

### Verification

Verification should check schemas, tool outputs, evidence coverage, citations, assumptions, and artifact consistency. Missing or conflicting evidence must be surfaced rather than filled in by the model.

### Storage

PostgreSQL and pgvector are intended future storage components for application records and retrieval indexes. File storage is intended for inputs and artifacts. Data isolation, retention, and access policies must be designed before production use.

### Artifacts and Trace

The system should record inputs, tool calls, deterministic results, evidence references, decisions, user confirmations, errors, and produced artifacts sufficiently to support inspection and reproducibility. Sensitive data must not be logged indiscriminately.

## Cross-Cutting Requirements

Security, authorization, provenance, observability, testing, evaluation, performance, and cost controls apply across all layers. Exact mechanisms remain to be designed and implemented.

