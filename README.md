# Agentic Intelligence Workspace

> Under active development. The repository includes a tested FastAPI backend, bounded single-agent orchestration, evidence-bound mixed reasoning, versioned workflows, durable production persistence adapters, management artifacts, and a functional Next.js workspace foundation.

This project turns natural-language goals over structured data and unstructured documents into verified, reproducible workflows and useful artifacts. Calculations remain in deterministic typed tools. A model provider may select tools and explain results, but cannot execute arbitrary Python, SQL, or shell commands.

## Implemented

- CSV/XLSX inspection, profiling, transformations, joins, aggregations, derivations, and safe exports.
- PDF extraction, deterministic chunking, provider/repository abstractions, ranked retrieval, and citations.
- One bounded observe/replan orchestrator with strict arguments, redacted traces, explicit errors, and iteration limits.
- Environment-configured OpenAI-compatible Responses provider with strict structured decisions, bounded output, timeouts, retries, safe provider errors, and optional base URL.
- Task-scoped general tools for dataset inspection/profiling, transformations, joins, aggregations, artifact exports, grounded document retrieval, and authorized workflow reruns.
- `grades.csv` + `syllabus.pdf` mixed reasoning with a deterministic required-final calculator.
- Numeric/citation verification and versioned deterministic recipes with schema-drift checks.
- Provenance-carrying management XLSX artifacts and a known-ground-truth August sales demonstration.
- Next.js workspace UI for uploads, tasks, traces, evidence, verification, and artifact visibility.
- Alembic-managed PostgreSQL schema for documents/chunks, workflow versions and runs, artifact metadata, and structured execution records.
- Production pgvector exact-cosine retrieval with provider/model/dimension isolation and optional document filtering.
- PostgreSQL-backed workflow metadata plus local-filesystem artifact bodies with hashes and PostgreSQL provenance metadata.
- A recruiter-focused August sales workflow that discovers the three uploaded table roles from inspected schemas, retrieves commission evidence, runs deterministic cleaning/joins/analysis/commissions, verifies named facts, generates a six-sheet workbook with three charts, and saves a schema-checked recipe.
- A deterministic Transform-to-Template workflow for CSV/XLSX targets with structural inspection, evidence-ranked mappings, first-class clarification states, guarded joins and derivations, policy-grounded rates, exact template writing, reopen validation, field provenance, and drift-checked reruns.
- Bounded JSON/Parquet dataset adapters, UTF-8 text document ingestion through the existing retriever, a read-only external PostgreSQL connector, and a GET-only REST JSON connector with SSRF protections and secret references.
- Typed deterministic analytics over workspace datasets, with named numeric facts, existing-verifier grounding, optional validated read-only SQL against external PostgreSQL, and a focused analytics UI. DuckDB is not used.

## Quick start

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

`APP_MODE=demo` is the zero-dependency path. It intentionally uses process-local repositories, deterministic token-hash embeddings, and the explicit bounded grades demonstration provider. It never silently calls a hosted model.

For production mode, create a project-owned PostgreSQL database, configure `DATABASE_URL` without committing credentials, and apply migrations before starting the API:

```powershell
cd backend
$env:DATABASE_URL = "postgresql://USER:PASSWORD@localhost:5432/agentic_intelligence"
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe current
$env:APP_MODE = "production"
$env:ORCHESTRATOR_PROVIDER = "openai"
$env:ORCHESTRATOR_API_KEY = "..." # or use OPENAI_API_KEY
$env:ORCHESTRATOR_MODEL = "gpt-6-astra"
# Optional for a Responses-compatible endpoint:
$env:ORCHESTRATOR_BASE_URL = "https://api.openai.com/v1"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The initial migration enables pgvector and creates every production table. The database role used for migration must be permitted to create the `vector` extension; the runtime should use a least-privilege role in a real deployment. For each schema change, create a new revision with `alembic revision -m "description"`, implement both directions, review generated SQL, and apply `alembic upgrade head`. Never edit a revision after it has been deployed.

Alternatively, copy `.env.example` to `.env`, replace placeholders, set `APP_MODE=production`, and run `docker compose up`. Compose has a one-shot migration service and persistent volumes for PostgreSQL and artifact bodies. The controlled offline evaluation requires neither PostgreSQL nor an API key:

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.evaluation.retrieval ..\evals\retrieval_cases.json
.\.venv\Scripts\python.exe -m app.evaluation.product ..\evals\product_cases.json
.\.venv\Scripts\python.exe -m app.evaluation.agent ..\evals\agent_cases.json
.\.venv\Scripts\python.exe -m app.evaluation.north_star ..\evals\north_star_cases.json
.\.venv\Scripts\python.exe -m app.evaluation.template_transform ..\evals\template_transform_cases.json
.\.venv\Scripts\python.exe -m app.evaluation.sources ..\evals\source_cases.json
.\.venv\Scripts\python.exe -m app.evaluation.analytics ..\evals\analytics_cases.json
```

All commands exit nonzero when a controlled case fails. The product evaluation covers deterministic grade calculation and evidence states, numeric verification, demo tool selection, workflow schema drift, and fixed August sales ground truth. The agent evaluation covers controlled aggregation/join selection, recoverable replanning, iteration limits, and insufficient evidence with a scripted provider. The north-star evaluation covers the complete sales plan, totals, regional variance, commissions, citations, policy refusal, join warnings, verification, artifact contents, recipe reruns, schema drift, and bounded failures. Source and analytics evaluations exercise the bounded connector and typed-computation contracts. These offline evaluations do not exercise hosted models, hosted embeddings, or a live database unless the source evaluator receives an explicit isolated `TEST_DATABASE_URL`.

The Transform-to-Template evaluation covers all 18 controlled cases from exact and normalized mappings through ambiguity, missing fields, type refusal, safe/unsafe joins, derivations, exact schema order, workbook reopen/preservation, formula-injection protection, policy grounding/refusal, workflow reruns, source/template drift, and confirmed-mapping reuse.

## Demonstrations

`sample_data/grades.csv` and `sample_data/syllabus.pdf` exercise cited policy evidence plus deterministic weighted-grade calculation. The August sales files and `commission_policy.pdf` exercise cleaning, join diagnostics, targets, underperformance, deterministic commissions, verification, a management workbook, and a saved/rerunnable recipe. Tests contain the executable end-to-end paths and fixed expected outputs.

### Recruiter north-star: August sales management report

In the browser, choose **August sales report**, enter the goal, and upload:

- `sample_data/august_transactions.csv` as transactions;
- `sample_data/sales_customers.csv` as customers;
- `sample_data/sales_targets.csv` as targets; and
- `sample_data/commission_policy.pdf` as policy evidence.

The bounded orchestrator lists and inspects the authorized resources, identifies their roles from required columns rather than filenames, retrieves the commission rule with page/chunk provenance, and invokes `sales.north_star_report`. Deterministic code preserves the source frames, handles safe cleaning, rejects ambiguous duplicates and policy rules, reports join losses, computes every total/variance/commission, and emits named verification facts.

The downloadable workbook contains **Executive Summary**, **Regional Performance**, **Salesperson Performance**, **Cleaned Transactions**, **Data Quality**, and **Provenance & Sources** sheets plus actual-vs-target, shortfall, and commission charts. The UI shows a user-facing Goal → Plan → Inspect → Retrieve → Clean → Join → Analyze → Calculate commissions → Generate workbook → Verify → Complete trace, citations, warnings, verification findings, and the saved recipe version. Reruns accept compatible replacement resources and fail on material schema drift.

The controlled fixture currently yields total net sales `2350.00`, total commission `117.50`, North net sales `1350.00`, and a North shortfall of `650.00`; Alice's cited-policy commission is `67.50`. An unmatched customer remains visible under `Unassigned`, and that missing customer/target relationship is reported as a warning rather than hidden. These are synthetic deterministic results, not hosted-model quality evidence.

### Transform-to-Template demo

Choose **Transform to supplied template** in the browser and upload `sample_data/raw_orders.xlsx`, `sample_data/customer_master.csv`, `sample_data/reporting_policy.pdf`, and `sample_data/required_template.xlsx`. The first action inspects the sources and target and displays mappings, confidence, and unresolved fields. The second executes the displayed deterministic customer join, currency cleaning, net-sales derivation, cited commission rule, exact workbook write, reopen checks, provenance, and workflow save.

The output preserves the target's `Monthly Submission` and `Instructions` sheets, translates its trusted local formulas into each output row, and neutralizes untrusted formula-like source text. The original uploads are never overwritten. The public API is `POST /template-transforms/proposals` followed by `POST /template-transforms/executions`; successful executions return artifact and reusable-workflow references, while unresolved requirements and failed validation are explicit response states.

### External and file sources

Choose **External and file sources** to inspect `sample_data/source_orders.json`, `sample_data/source_orders.parquet`, or `sample_data/source_notes.txt`, or to import from PostgreSQL/REST using environment secret references (`EXTERNAL_PG_PASSWORD`, `REST_BEARER_TOKEN`). The UI does not store passwords. Private REST URLs require `ALLOW_PRIVATE_REST_TARGETS=1` on the server. DOCX is not implemented.

## Verification boundaries and current limitations

Implemented and tested offline: repository behavior, migration shape/static SQL, runtime separation, readiness failures, demo workflows, deterministic evaluations, and frontend build checks. CI is configured to run an isolated PostgreSQL 17 + pgvector integration test, but that workflow was not executed from this local run.

Implemented but not live-verified locally: PostgreSQL writes/reads, pgvector similarity execution, Alembic upgrade against a live server, hosted embeddings, and hosted orchestrator execution. PostgreSQL 17 is listening locally, but no `DATABASE_URL`, PostgreSQL environment credentials, `.env`, or pgpass entry was available; a single passwordless `psql` probe was rejected. No provider key was available for this milestone, and no password was guessed or authentication changed.

Planned or still incomplete: OCR, authentication/authorization, tenant isolation, parser sandboxing/malware scanning, retention controls, connection pooling, object storage, production rate limiting, broad hosted-provider quality evaluation, and deployed-cloud verification. Local filesystem artifact storage is intentionally the current production body store; PostgreSQL stores only metadata, references, and integrity hashes.
