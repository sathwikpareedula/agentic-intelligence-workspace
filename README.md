# Agentic Intelligence Workspace

**Turn recurring data work into verified, reusable workflows.**


Agentic Intelligence Workspace is an agentic data-operations platform that combines AI planning with deterministic data tools to analyze structured data and business documents, generate validated deliverables, preserve evidence and provenance, and safely rerun successful workflows on new data.

Instead of asking an AI assistant to repeat the same analysis every month, the workspace turns a successful task into a versioned workflow that can be rerun, inspected, compared, and stopped when new inputs are no longer safe or compatible.

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

After the initial report, select **Create First Run** to record the August baseline. Replace the transactions file, select **Run Again with Current Inputs** to execute the same saved recipe for September, then compare the two completed runs in **What Changed?**. The comparison uses facts persisted by deterministic tools; the browser does not recalculate them.

Finally, replace the transactions file with `sample_data/incompatible_transactions.csv`. The missing required `discount` column must create an inspectable blocked run rather than a report.

## V1 Validation

V1 was validated across the complete browser demo surface and supporting backend integrations.

- All five visible workflows were browser-tested
- August → September recurring-sales rerun verified
- Persisted comparison verified: `2350 → 3030`, `+680`, `+28.94%`
- Incompatible transaction schema correctly creates a blocked run with no generated facts or artifacts
- PostgreSQL 17.4 + pgvector 0.8.6 integration verified locally
- Frontend typecheck and CI checks passing
- Deterministic evaluation suites passing
- Hosted-provider quality is not claimed until a real credential-backed run is completed

## Quick start

Prerequisites: Python 3.11 or newer and Node.js 22. The demo path needs no database or provider credential.

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
$env:APP_MODE = "demo"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

In a second terminal:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Open `http://localhost:3000` and choose **Reusable monthly sales workflow**. `APP_MODE=demo` uses process-local repositories and deterministic token-hash embeddings; it does not call a hosted model.

## Execution modes

**Demo mode** is the default recruiter path above: it is deterministic, credential-free, and reproducible. **Live model mode** uses the same typed tool contracts and deterministic calculation tools, but lets a configured OpenAI Responses-compatible provider drive the bounded orchestration loop. Production mode also requires migrated PostgreSQL with pgvector and durable artifact storage.

Set these server-only placeholders before starting the backend in live model mode:

```powershell
$env:APP_MODE = "production"
$env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST:5432/DATABASE"
$env:OPENAI_API_KEY = "<embedding-provider-key>"
$env:ORCHESTRATOR_PROVIDER = "openai"
$env:ORCHESTRATOR_API_KEY = "<orchestrator-provider-key>"
$env:ORCHESTRATOR_MODEL = "<Responses-compatible model name>"
```

Apply Alembic migrations before startup. `docs/DEPLOYMENT.md` lists the complete production contract, and `docs/MODEL_EVALUATION.md` provides a credential-gated live smoke/evaluation command. The provider path is covered with mocked integration tests, but no hosted model quality result is claimed. Ollama remains an explicitly configured local option; current evidence does not identify a recommended local default.

## Verification and limitations

The backend tests and deterministic evaluations are the executable specification for retrieval, verification, Transform-to-Template, external-source boundaries, analytics, workflow runs, and the recurring-sales lifecycle. See `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, and `docs/MODEL_EVALUATION.md` for the implemented boundaries and validation evidence.

PostgreSQL 17.4 with pgvector 0.8.6 was verified locally against an isolated project database. Hosted-provider execution, cloud deployment, multi-user authentication/authorization, OCR, parser sandboxing, object storage, and Docker runtime remain unverified or out of V1 scope; the repository does not claim them as completed.
