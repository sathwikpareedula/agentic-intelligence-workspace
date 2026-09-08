# ADR 0007: Structured Analytics Plans Without DuckDB

## Decision

Phase 3 analytical questions are represented as typed `AnalyticsPlan` objects and executed with pandas over workspace datasets. Optional analytical SQL against external PostgreSQL reuses the Phase 2 single-statement validator and read-only session. DuckDB is not introduced.

## Alternatives

- Free-form SQL over local files.
- DuckDB as an in-process analytical SQL engine.
- LLM arithmetic over retrieved rows.

## Why Chosen

The existing pandas stack already computes the bounded metric set. Adding DuckDB would create a second SQL dialect and security boundary without a verified capability gap. Structured plans keep recipes inspectable and rerunnable. External SQL remains an explicit, validated, read-only connector path rather than a general query engine.

## Safety and Trust Boundaries

- Plans forbid unknown fields and do not accept Python expressions.
- Numeric work is pandas-only: no `eval`, `exec`, or generated code.
- Important answer claims reuse `EvidenceVerifier` against named `verification_facts`.
- Non-finite inputs and integers outside exact IEEE-754 fact range fail closed; sample variance and standard deviation use `ddof=1`; percent-change facts use percent units while growth-rate facts use ratios.
- Grouped fact identities encode typed grouping context, duplicate identities across tool calls are ambiguous rather than silently overwriting stale facts, and unit-bearing claims must preserve the deterministic unit.
- External SQL is still one WITH/SELECT, with application validation plus `READ ONLY` sessions.

## When to Revisit

Introduce DuckDB only if local multi-dataset SQL or out-of-core scans are required and the SQL validator/read-only story is evaluated for that engine.
