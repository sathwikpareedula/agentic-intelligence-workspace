# ADR 0005: Deterministic Transform-to-Template Plans

## Decision

Implement Transform-to-Template as one typed deterministic service integrated with the existing dataset, join, retrieval, artifact, workflow, and task-scoped orchestrator boundaries. Represent mappings, joins, transformations, derivations, validation requirements, source schemas, and target fingerprints as closed Pydantic contracts. Treat unresolved required fields as a structured clarification state and block execution until each is mapped, derived from supplied evidence, or provided by a trusted local template formula.

## Alternatives

- Ask a model to generate Python or spreadsheet-editing code.
- Treat a target workbook as a plain output schema and rebuild it from scratch.
- Accept fuzzy matches automatically.
- Store transform jobs in a separate recipe/provenance subsystem.

## Why Chosen

The existing deterministic services already provide bounded ingestion and join diagnostics, and the existing repositories provide artifact integrity and durable versioned recipes. A specialized plan captures template-preservation and clarification semantics without expanding execution authority. Structural fingerprints and pinned recipes make rerun assumptions inspectable, while task-scoped wrappers keep uploaded bytes outside model-visible arguments.

## Safety and Trust Boundaries

- Only `.csv` and non-macro `.xlsx` targets are accepted; workbook archives, dimensions, active content, external links, and formulas are bounded or rejected.
- Mapping confidence is evidence, not permission to invent data. Missing, ambiguous, and incompatible required fields prevent completion.
- Joins use the existing diagnostics and block configured many-to-many or repeated-key multiplication.
- Policy-derived percentages require retrieved evidence containing one unambiguous rate; a caller cannot supply that rate as a plan constant.
- Untrusted formula-like source text is neutralized, while supported local formulas already present in the target are translated across output rows.
- Reruns pin mappings, rules, and policy evidence. Only source/template replacements are accepted, and schema/template drift fails before output creation.

## Tradeoffs

The V1 header detector is deterministic and bounded rather than model-assisted. It supports one ordered join chain and a focused operation set, not arbitrary spreadsheet layouts, macros, external links, pivot-table refresh, or generated code. Workbook formulas are preserved but not evaluated by the service, so deterministic validation verifies formula presence/translation rather than calculated cached values. Workflow recipes currently contain uploaded base64 payloads, which inherits the existing retention and tenant-isolation limitations.

## When to Revisit

Expand layout regions, operation types, or formula support only when representative template evaluation demonstrates a concrete need. Add a model suggestion tier only behind the same clarification and deterministic validation boundaries. Move uploaded bodies out of recipes when durable dataset/object storage and tenant authorization are implemented.
