# ADR 0006: Bounded External Source Connectors

## Decision

Add JSON, Parquet, and UTF-8 text adapters plus two external connectors—read-only PostgreSQL and GET-only REST JSON—behind typed configs that reuse existing dataset inspection/profiling, retrieval chunking, provenance, workflows, and task-scoped tools. Secrets are environment references, never recipe values. DOCX is deferred.

## Alternatives

- Generate SQL from natural language.
- Allow arbitrary URLs, POST/PUT, or browser fetching.
- Store passwords in workflow recipes or browser storage.
- Build a parallel ingestion stack for each source type.

## Why Chosen

Phase 2 needs high-value structured and document sources without expanding execution authority. Reusing `load_dataset`, retrieval chunking, and workflow tools keeps provenance and Transform-to-Template integration intact. Application-level SQL allowlisting plus read-only sessions, and SSRF URL/IP checks plus test-only private REST, fail closed.

## Safety and Trust Boundaries

- JSON refuses ambiguous envelopes instead of guessing.
- Parquet is metadata-bounded then loaded through pyarrow.
- TXT uses the PDF chunker and is stored as untrusted evidence text.
- PostgreSQL accepts only one lexically validated non-recursive WITH/SELECT or identifier-quoted non-system table read; writes, system catalogs, known side-effecting functions, and multi-statements are rejected; the transaction verifies `READ ONLY`. The lexical allowlist is defense in depth and the source database role must remain least privilege.
- REST is GET/HTTPS (HTTP private targets only when `ALLOW_PRIVATE_REST_TARGETS=1`), with redirect revalidation, IP pinning at connect time, original-host TLS verification/Host, IPv4-mapped address classification, size limits, JSON content types, no secret-like query parameters, and fail-closed cross-origin redirects whenever any secret-referenced header is configured.
- Agent tools bind pre-approved source names; they cannot supply raw passwords or invent production URLs that skip SSRF checks.

## Tradeoffs

No production secret manager, OAuth, or pagination is implemented. DNS is still resolved through the operating system; connecting to the validated `getaddrinfo` address closes the hostname-rebinding window for that request but is not a standalone DNS architecture. External Postgres is a separate data source from application persistence even when tests share the CI database.

## When to Revisit

Add DOCX after OOXML zip/active-content review. Revisit secret management when authentication/tenancy exists. Revisit DNS resolution if a dedicated resolver or Happy Eyeballs policy is required.
