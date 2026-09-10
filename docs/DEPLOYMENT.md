# V1 Deployment Readiness

## Recommended shape

Use one Next.js frontend, one FastAPI backend, PostgreSQL with pgvector, durable artifact storage mounted at `ARTIFACT_STORAGE_PATH`, and environment-managed provider secrets. Run Alembic as a separate one-shot release step before starting the backend. The application does not migrate its schema during API startup.

This is a simple single-tenant V1 deployment shape. Authentication, authorization, tenant isolation, managed object storage, connection pooling, rate limiting, and retention controls are not implemented; do not expose it as a sensitive multi-user service.

## Environment boundaries

Server-only variables belong on the backend or migration service:

- `DATABASE_URL` and `DATABASE_CONNECT_TIMEOUT_SECONDS`
- `ARTIFACT_STORAGE_PATH`
- `OPENAI_API_KEY` for hosted embeddings
- `ORCHESTRATOR_API_KEY` (or the documented `OPENAI_API_KEY` fallback)
- `ORCHESTRATOR_PROVIDER`, `ORCHESTRATOR_MODEL`, `ORCHESTRATOR_BASE_URL`
- `ORCHESTRATOR_TIMEOUT_SECONDS`, `ORCHESTRATOR_MAX_RETRIES`, `ORCHESTRATOR_MAX_OUTPUT_TOKENS`, `ORCHESTRATOR_CONTEXT_TOKENS`
- optional paired `ORCHESTRATOR_INPUT_COST_PER_MILLION` and `ORCHESTRATOR_OUTPUT_COST_PER_MILLION`
- `CORS_ALLOWED_ORIGINS`, a comma-separated list of exact HTTP(S) frontend origins

`NEXT_PUBLIC_API_URL` is different: it is intentionally browser-visible and compiled into the Next.js bundle at build time. Set it to the public URL a user's browser can reach, then rebuild the frontend. Never put API keys, database URLs, passwords, tokens, internal-only hostnames, or any other secret in a `NEXT_PUBLIC_*` variable.

The checked-in `.env.example` contains placeholders only. Copy it to an untracked `.env`, replace every `replace-me`, and keep that file out of source control and image build contexts.

`ORCHESTRATOR_PROVIDER=ollama` selects the native local adapter without a provider credential. Its base URL must be a literal loopback URL such as `http://127.0.0.1:11434/api`; start Ollama and pull the configured model separately on the backend host. The application never downloads model binaries. Hosted OpenAI orchestration remains available with `ORCHESTRATOR_PROVIDER=openai` and its existing credential requirements.

## Container path

From the repository root:

```powershell
Copy-Item .env.example .env
# Edit .env with a unique PostgreSQL password and provider credentials.
docker compose config
docker compose build --pull
docker compose up
```

Compose starts PostgreSQL, waits for its health check, runs `alembic upgrade head` as a separate one-shot service, starts the backend, then starts the frontend after the backend liveness check passes. Backend readiness remains visible at `/ready`; `/health` is deliberately a liveness check so the UI can still report missing production configuration.

The backend and frontend production images run as non-root users. The frontend uses Next.js standalone output. Docker build contexts exclude local environments, dependencies, caches, test outputs, Git metadata, and local environment files. The artifact volume must remain writable by the backend container user.

## Direct process path

For a non-container host, apply migrations before starting the API:

```powershell
cd backend
$env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST:5432/agentic_intelligence"
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe heads
$env:APP_MODE = "production"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Build the frontend only after setting its public API URL:

```powershell
cd frontend
$env:NEXT_PUBLIC_API_URL = "https://api.example.invalid"
npm.cmd ci
npm.cmd run build
npm.cmd run start
```

Replace the example host with the real public backend origin. Configure the same frontend origin in backend `CORS_ALLOWED_ORIGINS`.

## Health and persistence

- `/health` proves only that the API process responds.
- `/ready` checks production configuration, PostgreSQL/pgvector, migration state, and artifact-path writability. It does not make a paid hosted-provider request.
- PostgreSQL and the artifact volume are durable state. Back up both together; PostgreSQL metadata contains artifact hashes and references while bodies live under the artifact root.
- Uploaded PDF bodies are not retained; extracted chunks are stored in PostgreSQL.

Docker/Compose definitions can be checked statically without Docker. A real release still requires a successful image build, Compose/config validation, migration against an isolated database, and smoke tests in the target environment.
