# ADR 0008: Immutable workflow runs and deterministic comparison

## Decision

Keep an immutable workflow version as the executable definition and store each execution as a separate immutable run. A run records its workflow/version fingerprint, terminal lifecycle events, safe input/source snapshots, schema and type fingerprints, deterministic facts, warnings, verification summary, artifacts, and drift/failure details.

Compare only completed runs of the same workflow. Match numeric results by step-scoped fact identity and require metric, unit, grouping, and calculation semantics to remain equal. Compute absolute and percentage changes deterministically; report missing metrics as added/removed and omit percentage change when the previous value is zero. Preserve references to both source run IDs.

## Rationale

Workflow definitions answer what should execute; run records answer what actually executed with which inputs and results. Keeping those concepts separate prevents later workflow changes from rewriting history and makes recurring operations inspectable. Structured comparison facts provide a reliable “What Changed?” layer without asking a model to recompute numbers or infer causality.

The current executor is synchronous, so lifecycle events are persisted with the terminal run rather than requiring premature job infrastructure. The schema remains compatible with future asynchronous execution.

## Consequences

- Run-history reads are bounded and newest-first.
- Compatible file content may change while expected columns and inferred types stay pinned; unsafe drift is recorded as a blocked run.
- External-source configuration and secrets remain governed by the existing pinned-source and secret-reference policies.
- Task-scoped agent tools can list, inspect, or compare runs only through an already bound workflow ID and do not return stored dataset bodies.
- Comparison reports observations, verification changes, and provenance. Causal interpretation remains outside this deterministic subsystem.
- Compact quality and step summaries reuse existing deterministic inspections/tool observations. Category labels are stored only for complete bounded sets; incomplete sets expose counts without added/removed claims. These signals are called drift, reserving anomaly for a future explicit statistical method.
