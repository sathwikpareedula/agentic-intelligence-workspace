# ADR 0002: Bounded Orchestrator and Deterministic Recipes

## Decision

Use one custom bounded orchestrator over strict Pydantic tools. Providers return either a tool call or completion. Successful deterministic calls can be saved as ordered versioned recipes and rerun without a model.

## Alternatives

- Adopt an orchestration framework.
- Build a multi-agent system.
- Save chat transcripts as workflows.

## Why Chosen

The loop is small enough to test directly. Existing services remain the computation boundary, recipes describe executable operations, and deterministic fakes keep evaluation offline.

## Tradeoffs

The current provider is test-only, repositories are not durable, and workflow parameter references are basic. Verification covers only claims tied to observed system evidence.

## When to Revisit

Revisit orchestration infrastructure when evaluation shows the custom loop cannot support required resumability, approvals, or durability. Revisit multi-agent design only with measured quality or reliability evidence.
