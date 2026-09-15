# Agent Instructions

## Mission

Build a trustworthy agentic AI data and knowledge workspace that turns natural-language goals over structured data and unstructured documents into verified, reproducible workflows and useful artifacts.

## Permanent Technical Pillars

1. Agentic Systems
2. Retrieval & Knowledge
3. Data Intelligence
4. Trustworthy AI Engineering

## Working Rules

- Read `README.md`, `docs/PRODUCT_SPEC.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/SECURITY.md`, and relevant decision records before making major changes.
- Keep changes scoped to the requested outcome. Avoid unrelated cleanup or speculative infrastructure.
- Do not add dependencies unless they are necessary for an implemented requirement. Explain why each new dependency is justified.
- Do not change the documented architecture silently. Record material decisions and update affected documentation before or with the change.
- Add or update tests for every behavioral change. Report the tests run and their results.
- Use deterministic code for calculations, transformations, joins, statistics, validation, and schema checks. The LLM may understand intent, plan, select tools, interpret results, and explain results; it must not substitute for deterministic computation.
- Never execute arbitrary LLM-generated code unsafely. Generated SQL, Python, shell commands, and tool calls require constrained execution, validation, least privilege, and appropriate user confirmation.
- Do not fabricate missing data or evidence. Report ambiguity and insufficient evidence explicitly.
- Involve the user before ambiguous, destructive, irreversible, or unexpectedly broad operations.
- Report assumptions, affected files, and verification or test results when handing off work.
- Never claim functionality, security controls, evaluations, or performance characteristics that have not been implemented and verified.
- Prefer one orchestrator with typed deterministic tools initially. Do not introduce multi-agent architecture unless evaluation evidence justifies it.
- Treat artifacts, provenance, reproducibility, security, testing, evaluation, and cost as core engineering concerns.

## Cloud Agent environment

- `.cursor/environment.json` defines the Cloud Agent setup. `APP_MODE=demo` is the default: no PostgreSQL or API keys required.
- Install: `./scripts/cloud-agent-install.sh` (backend venv + frontend `npm ci`).
- Dev servers start via `terminals`: backend on port 8000, frontend on port 3000.
- Offline checks: `cd backend && .venv/bin/python -m pytest -q --ignore=tests/test_postgres_integration.py` and the evaluation modules under `app.evaluation.*`.
- Production mode needs `DATABASE_URL`, `alembic upgrade head`, and orchestrator/embedding API keys; see `compose.yaml` and `.env.example`.

