# Architecture

## Status

The implemented FastAPI backend provides deterministic structured-data operations, PDF evidence retrieval, a bounded single orchestrator, mixed grade and sales tools, evidence-based verification, in-memory workflow persistence, and provenance-carrying artifacts. Tests use deterministic in-memory providers; live provider/database verification remains pending.

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

All layers in the diagram now have initial implementations. Durable workflow/artifact persistence, production model-provider wiring, and production operations remain incomplete.

## Responsibilities

### Frontend

Provide a thin interaction layer for goals, user confirmations, progress, evidence, traces, and artifact downloads. A thin internal UI is planned before a production Next.js UI.

### API Layer

FastAPI is the implemented API boundary for health checks, typed structured-data operations, PDF ingestion, and evidence retrieval. Authentication, authorization, job interaction, and persistent artifact access remain future work.

### Orchestrator

One orchestrator runs a bounded decide/observe loop over a strict tool registry. It records validated redacted arguments, outcomes, provenance IDs, errors, and timing. A scripted provider supports offline tests; no production chat-model provider is wired yet.

### Deterministic Data Tools

Current deterministic services ingest CSV/XLSX data; inspect and profile datasets; and apply typed selection, filtering, sorting, renaming, deduplication, missing-value handling, restricted arithmetic derivation, grouping, aggregation, and joins. Join diagnostics surface unmatched rows and repeated-key multiplication. Broader calculations, schema checks, and validations remain future work. Inputs and outputs are typed and testable; an LLM is not the computation engine.

### Retrieval Tools

The retrieval service validates and extracts text from PDFs in memory, chunks normalized page text deterministically with configurable overlap, embeds chunks through a provider interface, and stores them through a document repository interface. The default hosted provider is OpenAI `text-embedding-3-small`; tests and evaluation use an offline deterministic fake. Results are ranked evidence candidates with document, filename, page, and chunk provenance, not generated answers or verified conclusions. Scanned/image-only documents require future OCR and are rejected when no text is extractable.

### Verification

Verification checks declared numeric claims against deterministic outputs and document claims against observed citation IDs. It propagates failed calculations and conflict/insufficiency states. It is deliberately not a universal truth verifier.

### Storage

The implemented retrieval repository stores document metadata, page-scoped chunks, and fixed-dimension vectors in PostgreSQL with pgvector. Search uses exact cosine distance and returns cosine similarity as `1 - distance`, with optional document filtering and deterministic ID tie-breaking. The repository interface also has an in-memory exact-cosine implementation for tests and controlled evaluation. Live PostgreSQL integration has not been verified in the current environment. Uploaded PDFs are not persisted as files. Tenant isolation, retention, migration tooling, connection pooling, and production access policies remain future work.

### Artifacts and Trace

CSV/XLSX and management workbooks are generated in memory with IDs, shape, producer references, provenance, formula neutralization, and optional deterministic charts. File bodies are redacted from traces. In-memory repositories support tests; durable persistence is not implemented.

## Cross-Cutting Requirements

Security, authorization, provenance, observability, testing, evaluation, performance, and cost controls apply across all layers. Exact mechanisms remain to be designed and implemented.
