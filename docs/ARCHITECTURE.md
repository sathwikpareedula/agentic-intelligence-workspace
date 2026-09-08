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

Provide a thin interaction layer for goals, user confirmations, progress, evidence, traces, artifact downloads, saved-workflow reruns, immutable run history, and deterministic run comparison.

### API Layer

FastAPI is the implemented API boundary for health checks, typed structured-data operations, PDF ingestion, evidence retrieval, workflows, workflow runs, and run comparison. Run execution remains synchronous, but stored lifecycle events make terminal success, blocked validation, and failure explicit. Authentication, authorization, and asynchronous job control remain future work.

### Orchestrator

One orchestrator runs a bounded decide/observe/replan loop over a strict task-scoped tool registry. It records validated redacted arguments, outcomes, provenance IDs, stable errors, and timing. Recoverable observations include the failed tool and safe arguments so a provider can correct a call without hidden execution state. The production adapter uses the OpenAI Responses API with a strict Pydantic decision schema, environment-configured key/model/base URL, bounded output, request timeout, SDK retries, disabled response storage, and safe error mapping. Demo mode remains a separate deterministic scripted path.

Production tasks bind up to eight uploaded datasets, eight ingested document IDs, and twenty saved workflow IDs. The model receives identifiers and JSON schemas rather than file bodies. Task tools expose resource listing, inspection/profile, validated transformation and aggregation, joins with diagnostics, complete CSV/XLSX exports, evidence search limited to bound documents, and reruns limited to bound workflows. The model cannot submit Python, SQL, shell, filesystem paths, or unregistered actions.

The north-star sales path is registered in this same task-scoped tool registry. A deterministic demo planner uses resource listing plus inspected columns to identify the transaction, customer, and target roles; production providers receive the same typed capability. The specialized tool returns bounded tables, join/data-quality diagnostics, named verification facts, policy source IDs, a workbook artifact, and a saved workflow reference. It does not return or require hidden model reasoning.

### Deterministic Data Tools

Current deterministic services ingest CSV/XLSX data; inspect and profile datasets; and apply typed selection, filtering, sorting, renaming, deduplication, missing-value handling, restricted arithmetic derivation, grouping, aggregation, and joins. Join diagnostics surface unmatched rows and repeated-key multiplication. Broader calculations, schema checks, and validations remain future work. Inputs and outputs are typed and testable; an LLM is not the computation engine.

Transform-to-Template reuses these ingestion and join boundaries behind a specialized typed plan. Template inspection records target headers/order, likely sheet/header row, examples, basic types/formats, trusted local formulas, workbook sheet structure, and a structural SHA-256 fingerprint. Mapping proposals rank explicit confirmations, exact/normalized names, documented aliases, and conservative semantic candidates; ambiguity, missing requirements, and incompatible values are first-class states. Execution prefixes source fields by role, applies only enumerated transformations/derivations, requires retrieved evidence for policy percentages, blocks configured join anomalies, writes a new in-memory artifact, and reopens it for validation.

JSON and Parquet uploads share `load_dataset` / inspect / profile. UTF-8 `.txt` documents reuse PDF chunking and the retrieval repository. External PostgreSQL is a separate read-only data source from application persistence. REST GET imports JSON through the same table adapter after SSRF checks. Imported tables are ordinary datasets and can feed Transform-to-Template. DOCX is not implemented.

Typed `AnalyticsPlan` objects describe filters, grouping, metrics, ranking, rolling windows, correlation, and target variance. Pandas executes them. Optional external SQL reuses the read-only PostgreSQL connector. DuckDB is not used. Numeric claims verify against named facts from these tools.

### Retrieval Tools

The retrieval service validates and extracts text from PDFs in memory, chunks normalized page text deterministically with configurable overlap, embeds chunks through a provider interface, and stores them through a document repository interface. The production provider is OpenAI `text-embedding-3-small`; tests and evaluation use an offline deterministic fake. Provider name, model, and dimensions are persisted and included in search predicates so vectors from incompatible spaces are not mixed. Results are ranked evidence candidates with document, filename, page, and chunk provenance, not generated answers or verified conclusions. Scanned/image-only documents require future OCR and are rejected when no text is extractable.

### Verification

Verification checks declared numeric claims against deterministic outputs and document claims against observed citation IDs. Product-critical claims may name exact fact keys so an unrelated equal number cannot accidentally verify them. Commission fact keys require both the matching deterministic output and observed policy citation IDs. Data/join warnings produce `verified_with_warnings`; failed tools, conflicts, unsupported values, and insufficient evidence retain stronger precedence. It is deliberately not a universal truth verifier.

### Storage

Alembic owns the production schema; application startup never creates tables or extensions. The PostgreSQL retrieval repository stores document metadata, page-scoped chunks, vector-space metadata, and pgvector embeddings. Search uses exact cosine distance (`<=>`) and returns cosine similarity as `1 - distance`, with parameterized provider/model/dimension predicates, optional document filtering, and deterministic ID tie-breaking. Exact search was chosen to avoid approximate-recall loss before corpus size and latency justify HNSW.

PostgreSQL also stores workflows, immutable workflow-version recipes, immutable run records, artifact metadata, and structured execution/tool provenance. Each new run stores a definition fingerprint, terminal lifecycle, safe source snapshots, deterministic comparison facts, compact missing/duplicate/category summaries, existing join/data-quality diagnostics, step outcomes, warnings, drift findings, artifacts, and verification summary; raw secret values are rejected before persistence. Workflow repositories survive process restart. Artifact bodies are stored under UUID-derived keys inside one configured local root; metadata includes media/type, dimensions, producing task/workflow/run references where available, verification status, byte size, and SHA-256. Bodies are integrity-checked on read and are not stored in PostgreSQL. Uploaded PDFs remain represented by extracted chunks rather than retained source files. Demo repositories remain process-local by design.

### Artifacts and Trace

CSV/XLSX and management workbooks are generated in memory with IDs, shape, producer references, provenance, formula neutralization, and optional deterministic charts. File bodies are redacted from traces. Production writes bodies through the artifact-store boundary and metadata through PostgreSQL; demo mode retains the in-memory repository.

Executions expose structured stages for goal, bounded plan, resource inspection, evidence retrieval, deterministic report phases, verification, and completion. Each stage carries only concise execution facts such as tool name, status, row counts, diagnostics, evidence IDs, verification result, and artifact IDs. Successful north-star runs save a one-step deterministic sales recipe with expected schemas for all nested dataset inputs; compatible resources can replace them on rerun, while missing or reordered columns fail as schema drift before calculation.

Successful template transforms save a one-step `template.transform` recipe through the existing workflow repository. The recipe includes source roles/order, confirmed mappings, joins, derivations, required/unique fields, expected source schemas, template structure fingerprint, and pinned policy evidence. Reruns may replace only sources and the target; mappings, rules, and evidence cannot be overridden. Task-scoped agent tools expose `template.propose` and `template.execute` without placing file bodies in model-visible arguments.

Workflow history APIs list workflows and bounded newest-first runs, return a safe run record, execute a stored workflow, and compare two completed runs. Comparison is deterministic over step-scoped facts and snapshots; every compared value points to its source run/workflow version. Task-scoped `workflow.list_runs`, `workflow.get_run`, and `workflow.compare_runs` tools accept only runs belonging to workflow IDs already bound to the task and return metadata rather than stored dataset bodies.

Run observability reuses tool observations rather than adding a telemetry stack. It stores tool name, success/blocked/failure state, warning/source/artifact counts, and selected numeric leaves from existing join, data-quality, and trace diagnostics. Drift comparison reports added/removed columns, explicit type changes, row/missing/duplicate/unique-count deltas, complete bounded category changes, join-quality deltas, verification/warning changes, and step outcome differences. It makes no statistical anomaly claim.

### Readiness and Failure Behavior

`/health` reports process liveness. `/runtime` describes configuration without claiming live dependencies. `/ready` performs bounded checks for PostgreSQL connectivity, pgvector, current Alembic revision/required tables, artifact-path writability, and required provider configuration. Repository and hosted-provider failures map to stable 5xx responses without exposing DSNs, passwords, credential-bearing URLs, request details, or provider response bodies. `/runtime` reports whether orchestration is `demo`, `configured`, or `unavailable` without making a paid request.

## Cross-Cutting Requirements

Security, authorization, provenance, observability, testing, evaluation, performance, and cost controls apply across all layers. Exact mechanisms remain to be designed and implemented.
