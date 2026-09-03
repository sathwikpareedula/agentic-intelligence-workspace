# ADR 0001: PostgreSQL + pgvector Retrieval Boundary

## Decision

Adopt PostgreSQL with pgvector as the production-intended store for document metadata, text chunks, provenance, and embeddings. Use exact cosine distance initially and expose storage and embedding providers through small typed interfaces. Use OpenAI `text-embedding-3-small` as the default hosted embedding model, configured only through environment variables. Tests and controlled evaluation use deterministic offline implementations.

## Alternatives

- Keep retrieval entirely in memory.
- Add a separate managed vector database.
- Use a retrieval framework that bundles chunking, embeddings, and storage.
- Add an approximate pgvector index immediately.

## Why Chosen

PostgreSQL keeps vector evidence and relational provenance in one transactional system already named in the intended architecture. The repository interface prevents route-level database coupling and permits reliable offline tests. Exact cosine search avoids approximate-recall behavior before corpus scale and retrieval evaluation justify an index. A direct embedding-provider interface keeps credentials, batching, dimensions, and provider failures explicit without an agent or retrieval framework.

## Tradeoffs

- PostgreSQL and hosted embeddings add operational setup, secrets, latency, and cost.
- The current schema initialization is application-managed and lacks a migration framework.
- Exact search will require performance evaluation as the chunk corpus grows.
- The deterministic evaluation provider validates ranking mechanics, not semantic model quality.
- Live PostgreSQL/pgvector and OpenAI integration were not available for verification in the implementation environment.

## When to Revisit

Revisit exact search when measured corpus size or latency misses an explicit target; evaluate HNSW recall before adoption. Revisit the embedding model or provider when controlled semantic evaluations, cost, privacy, or deployment constraints show a material deficiency. Add formal migrations before schema evolution or production deployment.
