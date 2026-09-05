# Architecture

## Status

The FastAPI backend provides deterministic structured-data operations, PDF evidence retrieval, one bounded orchestrator, mixed grade and sales tools, evidence-based verification, versioned workflows, and provenance-carrying artifacts. `APP_MODE=demo` uses deterministic in-memory providers. Production mode selects PostgreSQL repositories, pgvector retrieval, hosted embeddings, local filesystem artifact bodies, and PostgreSQL artifact/run metadata without silently falling back to demo implementations.

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

All layers in the diagram have initial implementations. Local live database/provider verification, multi-user controls, pooling, retention, object storage, and production operations remain incomplete.

## Responsibilities

### Frontend

Provide a thin interaction layer for goals, user confirmations, progress, evidence, traces, and artifact downloads. A thin internal UI is planned before a production Next.js UI.

### API Layer

FastAPI is the implemented API boundary for health checks, typed structured-data operations, PDF ingestion, and evidence retrieval. Authentication, authorization, job interaction, and persistent artifact access remain future work.

### Orchestrator

One orchestrator runs a bounded decide/observe/replan loop over a strict task-scoped tool registry. It records validated redacted arguments, outcomes, provenance IDs, stable errors, and timing. Recoverable observations include the failed tool and safe arguments so a provider can correct a call without hidden execution state. The production adapter uses the OpenAI Responses API with a strict Pydantic decision schema, environment-configured key/model/base URL, bounded output, request timeout, SDK retries, disabled response storage, and safe error mapping. Demo mode remains a separate deterministic scripted path.

Production tasks bind up to eight uploaded datasets, eight ingested document IDs, and twenty saved workflow IDs. The model receives identifiers and JSON schemas rather than file bodies. Task tools expose resource listing, inspection/profile, validated transformation and aggregation, joins with diagnostics, complete CSV/XLSX exports, evidence search limited to bound documents, and reruns limited to bound workflows. The model cannot submit Python, SQL, shell, filesystem paths, or unregistered actions.

### Deterministic Data Tools

Current deterministic services ingest CSV/XLSX data; inspect and profile datasets; and apply typed selection, filtering, sorting, renaming, deduplication, missing-value handling, restricted arithmetic derivation, grouping, aggregation, and joins. Join diagnostics surface unmatched rows and repeated-key multiplication. Broader calculations, schema checks, and validations remain future work. Inputs and outputs are typed and testable; an LLM is not the computation engine.

### Retrieval Tools

The retrieval service validates and extracts text from PDFs in memory, chunks normalized page text deterministically with configurable overlap, embeds chunks through a provider interface, and stores them through a document repository interface. The production provider is OpenAI `text-embedding-3-small`; tests and evaluation use an offline deterministic fake. Provider name, model, and dimensions are persisted and included in search predicates so vectors from incompatible spaces are not mixed. Results are ranked evidence candidates with document, filename, page, and chunk provenance, not generated answers or verified conclusions. Scanned/image-only documents require future OCR and are rejected when no text is extractable.

### Verification

Verification checks declared numeric claims against deterministic outputs and document claims against observed citation IDs. It propagates failed calculations and conflict/insufficiency states. It is deliberately not a universal truth verifier.

### Storage

Alembic owns the production schema; application startup never creates tables or extensions. The PostgreSQL retrieval repository stores document metadata, page-scoped chunks, vector-space metadata, and pgvector embeddings. Search uses exact cosine distance (`<=>`) and returns cosine similarity as `1 - distance`, with parameterized provider/model/dimension predicates, optional document filtering, and deterministic ID tie-breaking. Exact search was chosen to avoid approximate-recall loss before corpus size and latency justify HNSW.

PostgreSQL also stores workflows, immutable workflow-version recipes, rerun records, artifact metadata, and structured execution/tool provenance. Workflow repositories survive process restart. Artifact bodies are stored under UUID-derived keys inside one configured local root; metadata includes media/type, dimensions, producing task/workflow/run references where available, verification status, byte size, and SHA-256. Bodies are integrity-checked on read and are not stored in PostgreSQL. Uploaded PDFs remain represented by extracted chunks rather than retained source files. Demo repositories remain process-local by design.

### Artifacts and Trace

CSV/XLSX and management workbooks are generated in memory with IDs, shape, producer references, provenance, formula neutralization, and optional deterministic charts. File bodies are redacted from traces. Production writes bodies through the artifact-store boundary and metadata through PostgreSQL; demo mode retains the in-memory repository.

### Readiness and Failure Behavior

`/health` reports process liveness. `/runtime` describes configuration without claiming live dependencies. `/ready` performs bounded checks for PostgreSQL connectivity, pgvector, current Alembic revision/required tables, artifact-path writability, and required provider configuration. Repository and hosted-provider failures map to stable 5xx responses without exposing DSNs, passwords, credential-bearing URLs, request details, or provider response bodies. `/runtime` reports whether orchestration is `demo`, `configured`, or `unavailable` without making a paid request.

## Cross-Cutting Requirements

Security, authorization, provenance, observability, testing, evaluation, performance, and cost controls apply across all layers. Exact mechanisms remain to be designed and implemented.
