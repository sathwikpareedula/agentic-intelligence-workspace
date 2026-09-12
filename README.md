# Agentic Intelligence Workspace

**Turn recurring data work into verified, reusable workflows.**

Agentic Intelligence Workspace is an agentic data-operations platform that combines AI planning with deterministic data tools to analyze structured data and business documents, generate validated deliverables, preserve evidence and provenance, and safely rerun successful workflows on new data.

Instead of asking an AI assistant to repeat the same analysis every month, the workspace turns a successful task into a versioned workflow that can be rerun, inspected, compared, and stopped when new inputs are no longer safe or compatible.

---

## What It Demonstrates

- Agentic planning with typed tool contracts
- Deterministic analytics and data transformations
- Evidence-backed document retrieval
- Verification and provenance
- Reusable versioned workflows
- Schema-drift detection and run comparison

## Tech Stack

**Backend:** Python · FastAPI · Pydantic · pandas · PostgreSQL · pgvector · Alembic

**Frontend:** Next.js · TypeScript

**AI / Orchestration:** OpenAI-compatible providers · Ollama · typed tool calling · bounded agent loops

**Data / Retrieval:** CSV · XLSX · JSON · Parquet · PDF · REST · read-only PostgreSQL

---

## Architecture

```text
User Goal
   ↓
Orchestrator
   ↓
Typed Tools
   ↓
Data / Retrieval / External Sources
   ↓
Deterministic Execution
   ↓
Verification
   ↓
Artifacts + Provenance
   ↓
Saved Workflow + Run History
```

The model handles planning and semantic reasoning, while deterministic tools perform calculations, transformations, validation, and artifact generation.

---

## Why I Built This

General-purpose AI assistants are already good at one-off spreadsheet analysis.

The harder engineering problem is making recurring AI-assisted data work:

- reproducible;
- verifiable;
- evidence-backed;
- safe around changing inputs;
- deterministic where correctness matters;
- inspectable after execution;
- reusable across future reporting periods.

The core design principle is:

> **Use the model for planning and semantic reasoning. Use deterministic tools for calculations, transformations, validation, and artifact generation.**

The model can choose from approved tools and explain results, but it cannot execute arbitrary Python, shell commands, or unrestricted SQL.

---

## Flagship Demo: Reusable Monthly Sales Workflow

The main demo shows the full lifecycle of a recurring analytical workflow.

### First run

Upload:

- `sample_data/august_transactions.csv`
- `sample_data/sales_customers.csv`
- `sample_data/sales_targets.csv`
- `sample_data/commission_policy.pdf`

The system:

1. inspects the uploaded datasets;
2. identifies their roles from their schemas;
3. retrieves the relevant commission policy evidence;
4. cleans and joins the data;
5. calculates sales, targets, shortfalls, and commissions using deterministic code;
6. verifies important numeric and policy-backed claims;
7. generates a management workbook;
8. records provenance and execution history;
9. saves the successful operation as a reusable workflow.

The generated workbook contains:

- Executive Summary
- Regional Performance
- Salesperson Performance
- Cleaned Transactions
- Data Quality
- Provenance & Sources

It also contains charts for actual vs. target sales, shortfalls, and commissions.

### Run it again

Replace only the transactions file with:

```text
sample_data/september_transactions.csv
```

After the initial report, select **Create First Run** to record the August baseline.

Replace the transactions file, select **Run Again with Current Inputs** to execute the same saved recipe for September, then compare the two completed runs in **What Changed?**

The comparison uses facts persisted by deterministic tools; the browser does not recalculate them.

Finally, replace the transactions file with:

```text
sample_data/incompatible_transactions.csv
```

The missing required `discount` column must create an inspectable blocked run rather than a report.

---

## V1 Validation

V1 was validated across the browser demo surface and supporting backend integrations.

- All five visible workflows were browser-tested
- August → September recurring-sales rerun verified
- Persisted comparison verified: `2350 → 3030`, `+680`, `+28.94%`
- Incompatible transaction schema correctly creates a blocked run with no generated facts or artifacts
- PostgreSQL 17.4 + pgvector 0.8.6 integration verified locally
- Frontend typecheck and CI checks passing
- Deterministic evaluation suites passing
- Hosted-provider quality is not claimed until a real credential-backed run is completed

---

## Quick Start

### Prerequisites

- Python 3.11 or newer
- Node.js 22

The demo path requires no database or hosted-model credential.

### 1. Start the backend

From the repository root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
$env:APP_MODE = "demo"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

### 2. Start the frontend

Open a second terminal from the repository root:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

### 3. Open the workspace

Open:

```text
http://localhost:3000
```

Choose **Reusable monthly sales workflow**.

`APP_MODE=demo` uses process-local repositories and deterministic token-hash embeddings; it does not call a hosted model.

---

## Execution Modes

### Demo mode

Demo mode is the default recruiter path above. It is deterministic, credential-free, and reproducible.

It exercises the real ingestion, transformation, analytics, retrieval, verification, artifact-generation, workflow, provenance, and run-comparison code without requiring an external model provider.

### Live model mode

Live model mode uses the same typed tool contracts and deterministic calculation tools, but lets a configured OpenAI Responses-compatible provider drive the bounded orchestration loop.

Production mode also requires migrated PostgreSQL with pgvector and durable artifact storage.

Example server-side configuration:

```powershell
$env:APP_MODE = "production"
$env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST:5432/DATABASE"
$env:OPENAI_API_KEY = "<embedding-provider-key>"
$env:ORCHESTRATOR_PROVIDER = "openai"
$env:ORCHESTRATOR_API_KEY = "<orchestrator-provider-key>"
$env:ORCHESTRATOR_MODEL = "<Responses-compatible model name>"
```

Apply Alembic migrations before startup.

See:

- [Deployment guide](docs/DEPLOYMENT.md) for the production configuration contract
- [Model evaluation](docs/MODEL_EVALUATION.md) for credential-gated live and local execution
- [Architecture](docs/ARCHITECTURE.md) for the system design
- [Security](docs/SECURITY.md) for implemented boundaries and remaining limitations

The provider path is covered with integration tests, but no hosted-model quality result is currently claimed.

Ollama remains an explicitly configured local option. Current evidence does not identify a recommended local model default.

---

## Trust and Verification

The workspace separates probabilistic reasoning from deterministic execution.

The model can decide **what operation should happen**, while deterministic tools perform operations where correctness matters, including:

- calculations;
- joins;
- transformations;
- statistics;
- schema inspection;
- workflow comparisons;
- artifact generation.

Important claims can be connected to executed calculations or retrieved document evidence.

Execution records preserve tool traces, source references, artifact references, verification output, and workflow metadata without storing hidden model reasoning or chain-of-thought.

When required inputs become incompatible, the system is designed to fail closed instead of silently producing a potentially incorrect deliverable.

---

## Security Boundaries

V1 includes controls around:

- bounded file ingestion;
- PDF validation;
- XLSX archive and active-content checks;
- spreadsheet formula-injection protection;
- typed tool permissions;
- restricted read-only PostgreSQL access;
- REST/SSRF protections;
- secret handling and redaction;
- bounded orchestration loops;
- artifact path isolation;
- workflow and run integrity.

V1 is designed for **single-user, local, or controlled deployment**.

It is not intended for sensitive multi-user production use because authentication, authorization, tenancy, retention policies, and additional deployment-hardening controls remain out of scope.

See [Security](docs/SECURITY.md) for the full threat model, implemented controls, residual risks, and deployment limitations.

---

## Verification and Limitations

The backend tests and deterministic evaluations act as executable specifications for retrieval, verification, Transform-to-Template, external-source boundaries, analytics, workflow runs, and the recurring-sales lifecycle.

PostgreSQL 17.4 with pgvector 0.8.6 was verified locally against an isolated project database.

The following remain unverified or outside V1 scope:

- hosted-provider quality on a real credential-backed run;
- cloud deployment;
- multi-user authentication and authorization;
- OCR;
- parser sandboxing;
- object storage;
- Docker runtime verification.

The repository does not claim these as completed.

---

## Project Status

**V1.0.1**

The current V1 focuses on the core engineering question:

> How can an agentic AI system turn recurring data work into workflows that are reproducible, inspectable, evidence-backed, deterministic where correctness matters, and safe to rerun when inputs change?

Future work may include authentication and tenancy, durable object storage, asynchronous and scheduled execution, broader document support, richer dashboards, and additional external integrations.
