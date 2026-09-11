# ADR 0009: Product-Specific Provider-Neutral Model Evaluation

## Decision

Add a versioned scenario runner above the existing model-provider boundary. Evaluate model decisions against controlled tool observations with strict deterministic checks, while keeping semantic answer quality as a separate optional human judgment. Use the existing OpenAI Responses adapter for opt-in live runs and typed fixtures for credential-free CI. Capture only latency and token-count metadata from provider responses; calculate approximate cost only from operator-supplied rates.

## Alternatives

- Treat the existing scripted orchestration evaluation as hosted-model evidence.
- Benchmark general knowledge or arithmetic instead of workspace tasks.
- Execute live databases, files, and paid providers in CI.
- Couple evaluation cases directly to one provider SDK.
- Hard-code current model prices or a preferred model.

## Why Chosen

The product needs evidence about typed planning, tool selection, resource grounding, recovery, refusal, and faithful explanation. Controlled observations isolate those model responsibilities from deterministic tool correctness. A small provider factory boundary permits later adapters without rewriting scoring, while the existing production adapter supplies the one hosted implementation required for V1.

## Tradeoffs

- Fixture runs prove evaluation contracts, not live model quality.
- Controlled tools do not measure production database or retrieval latency.
- Exact string and argument checks are intentionally conservative and may underrate a semantically acceptable alternative plan.
- Human judgments require reviewer effort and remain subjective, so they are reported separately.
- Provider token metadata may be absent; cost remains unknown unless both usage and operator-verified rates are available.

## When to Revisit

Revisit the scenario suite when production traces reveal common failure modes or new tool families become V1-critical. Add another provider factory only when a real comparison is needed. Revisit scoring thresholds after live results and human review establish a defensible acceptance target.
