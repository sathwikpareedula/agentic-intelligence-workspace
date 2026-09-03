# Agentic Intelligence Workspace

> Under active development. The repository includes a tested FastAPI backend, bounded single-agent orchestration, evidence-bound mixed reasoning, verification, reusable workflows, management artifacts, and a functional Next.js workspace foundation.

This project turns natural-language goals over structured data and unstructured documents into verified, reproducible workflows and useful artifacts. Calculations remain in deterministic typed tools. A model provider may select tools and explain results, but cannot execute arbitrary Python, SQL, or shell commands.

## Implemented

- CSV/XLSX inspection, profiling, transformations, joins, aggregations, derivations, and safe exports.
- PDF extraction, deterministic chunking, provider/repository abstractions, ranked retrieval, and citations.
- One bounded observe/replan orchestrator with strict arguments, redacted traces, explicit errors, and iteration limits.
- `grades.csv` + `syllabus.pdf` mixed reasoning with a deterministic required-final calculator.
- Numeric/citation verification and versioned deterministic recipes with schema-drift checks.
- Provenance-carrying management XLSX artifacts and a known-ground-truth August sales demonstration.
- Next.js workspace UI for uploads, tasks, traces, evidence, verification, and artifact visibility.

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

For production-shaped retrieval, copy `.env.example` to `.env`, replace placeholders, and run `docker compose up`. The controlled offline evaluation requires neither PostgreSQL nor an API key:

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.evaluation.retrieval ..\evals\retrieval_cases.json
```

## Demonstrations

`sample_data/grades.csv` and `sample_data/syllabus.pdf` exercise cited policy evidence plus deterministic weighted-grade calculation. The August sales files and `commission_policy.pdf` exercise cleaning, join diagnostics, targets, underperformance, deterministic commissions, verification, a management workbook, and a saved/rerunnable recipe. Tests contain the executable end-to-end paths and fixed expected outputs.

## Current limitations

Offline tests use scripted model and embedding providers. The API intentionally returns 503 for agent tasks until a production orchestrator provider and application-scoped tools are configured. Workflow and artifact repositories are in-memory. OCR, authentication, tenant isolation, durable artifact storage, migrations, parser sandboxing, rate limiting, and deployed-cloud verification remain future work. Local Next.js typecheck and production build verification passed. Docker files exist but could not be run because Docker was unavailable in the implementation environment.
