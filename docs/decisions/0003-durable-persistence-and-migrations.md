# ADR 0003: Durable Production Persistence and Explicit Migrations

## Decision

Use Alembic for explicit PostgreSQL schema evolution. In production mode, use PostgreSQL repositories for documents, chunks, immutable workflow versions, workflow reruns, artifact metadata, and structured execution provenance. Store artifact bodies behind a separate local-filesystem abstraction with UUID-derived keys and SHA-256 integrity metadata. Keep deterministic in-memory repositories for `APP_MODE=demo` and offline tests.

## Alternatives

- Continue with process-local repositories.
- Create tables automatically during application startup.
- Store artifact bodies as PostgreSQL byte arrays.
- Introduce S3-compatible object storage in this milestone.
- Add a full ORM and rewrite existing repository SQL.

## Why Chosen

Alembic is the standard migration mechanism for the current Python/PostgreSQL stack and makes production schema changes reviewable and repeatable. Repository interfaces preserve the domain-service boundaries already in use. PostgreSQL provides transactions and relational provenance for metadata while the artifact-store boundary avoids large binary database rows and permits object storage later without changing callers. Direct parameterized psycopg operations keep this milestone narrow and avoid an unnecessary ORM rewrite.

## Schema and Retrieval Decisions

- pgvector embeddings use the unbounded `vector` column type plus validated provider, model, and dimension metadata. Queries filter all three before applying cosine distance, allowing explicit future migrations between embedding spaces without mixing them.
- Exact cosine distance is used initially. Approximate indexes are deferred until corpus/latency measurements justify HNSW and recall evaluation.
- Workflow recipes are immutable per `(workflow_id, version)`; a workflow row points to the current version. Reruns record overrides, typed observations, timestamps, status, failures, and artifact references.
- Execution records contain structured trace and verification data only, never hidden reasoning.
- Artifact metadata and bodies are written through separate abstractions. Read-back validates size and SHA-256; storage keys cannot contain user paths.

## Tradeoffs

- Local artifact bodies require a persistent mounted directory and do not provide distributed storage or replication.
- Direct connections are simple but need pooling and operational tuning before scale.
- Cross-store artifact body/metadata writes are not one atomic transaction; orphan reconciliation is future work.
- Workflow recipes can contain input arguments and therefore require retention, classification, tenant isolation, and authorization work before sensitive multi-user deployment.
- The initial migration needs a role permitted to create pgvector; production should separate migration and runtime credentials.

## Verification Boundary

Repository behavior, migration static SQL, demo/production selection, readiness failures, and deterministic evaluations are tested offline. The opt-in integration contract is also live-verified against an isolated local PostgreSQL 17.4 database with pgvector 0.8.6: Alembic reaches head, vector rows persist and rank by exact cosine distance with filtering, rollback behavior is retained, and workflow/run/artifact/execution records survive repository recreation. The source evaluation additionally exercises catalog discovery and constrained reads through the external PostgreSQL adapter. Verification uses a restricted project role and ephemeral/local password resolution; credentials are never committed.

## When to Revisit

Adopt connection pooling when concurrency measurements require it. Add HNSW only after recall/latency evaluation. Replace local storage with object storage when deployment topology requires it. Add tenant keys and row-level authorization before multi-user access.
