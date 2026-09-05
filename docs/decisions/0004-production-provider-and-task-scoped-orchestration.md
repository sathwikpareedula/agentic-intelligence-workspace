# ADR 0004: Production Provider and Task-Scoped General Orchestration

## Decision

Keep one custom bounded orchestrator and add an OpenAI-compatible Responses adapter that emits one strictly validated decision per turn. Configure its key, model, optional base URL, timeout, retry count, and output bound through environment variables. Build the production tool registry per request from explicitly bound dataset, document, and workflow resources. Keep `APP_MODE=demo` as a separate deterministic grades workflow.

## Alternatives

- Replace the custom loop with an orchestration framework.
- Add specialized agents or a multi-agent swarm.
- Send uploaded file bodies to the model and use unbound generic tools.
- Permit model-generated Python or SQL for generality.
- Keep only the narrow grades tool path.

## Why Chosen

The existing loop already provides typed validation, bounded iterations, traces, and deterministic computation boundaries. A task-scoped registry expands useful planning across datasets, retrieval, joins, aggregations, exports, and saved workflows without expanding authority. Strict structured decisions fail closed before execution, while deterministic services remain responsible for numeric and data work.

## Tradeoffs

- Responses-compatible endpoints must implement the structured-output behavior used by the adapter; a configurable base URL does not guarantee third-party compatibility.
- Tool observations intentionally include bounded result samples for planning, while exported artifacts retain complete deterministic results.
- The scripted offline evaluation measures orchestration contracts and failure behavior, not hosted-model language understanding, quality, latency, or cost.
- General workflow creation remains an explicit API action; the agent may rerun only workflow IDs bound to its task.

## When to Revisit

Revisit the provider protocol if controlled hosted-model evaluations show material incompatibility or if another endpoint is required. Revisit orchestration infrastructure only when measured needs for resumability, approvals, or durable asynchronous jobs exceed the custom loop. Revisit multi-agent design only with evaluation evidence that one orchestrator cannot meet a defined task-quality target.
