# ADR 0010: Native Local Ollama Provider and Resumable Evaluation

## Decision

Retain the existing single bounded orchestrator and add a native Ollama `/api/chat` provider behind the existing `ModelProvider.decide(goal, observations)` boundary. Require the same strict `ModelDecisionEnvelope`, pass its JSON schema through Ollama structured output, keep typed tools in the existing registry, and restrict V1 endpoints to literal loopback URLs. Local evaluation reuses the existing ten product scenarios and atomically checkpoints each completed case under a full configuration fingerprint.

## Alternatives

- Pretend Ollama is fully OpenAI Responses-compatible.
- Replace or fork the orchestrator and tool schemas for local models.
- Permit remote Ollama URLs or model-controlled endpoints.
- Keep live evaluation as one non-resumable process that writes only after all cases.
- Download or benchmark a broad model catalog.

## Why Chosen

Ollama exposes native schema-constrained JSON, token counts, generation durations, load duration, context controls, and output controls. Using those capabilities directly avoids relying on incomplete protocol compatibility. The existing envelope and registry already enforce the product's authority boundary. Per-case atomic checkpoints make slow CPU-only inference operationally recoverable without changing scenario rules or treating partial output as a complete comparison.

## Tradeoffs

- Remote Ollama servers are unsupported in V1, including otherwise legitimate LAN deployments.
- Local structured-output quality and latency vary by model and hardware; the adapter does not compensate with model-specific prompts.
- An interrupted case is rerun from its start, while already checkpointed cases are skipped.
- Local monetary cost remains unknown/null; the system does not invent a dollar value from local token counts.
- The application does not install Ollama or pull model binaries.

## When to Revisit

Revisit remote endpoints only with an explicit allowlist, redirect policy, authentication design, and SSRF review. Revisit the common generation/context limits when product traces show legitimate strict decisions cannot fit. Revisit the local default after the deferred `qwen3.5:4b` compatibility preflight and unchanged ten-case benchmark provide enough reliability, safety, latency, and resource evidence; the current evidence does not justify a default.
