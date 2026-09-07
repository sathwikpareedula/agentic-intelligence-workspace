# Product Specification

## Problem

People need to answer consequential questions using both structured data and unstructured documents. Existing workflows often separate those sources, hide calculations inside model output, lose provenance, and make results difficult to reproduce or verify.

## Mission

Turn natural-language goals over structured data and unstructured documents into verified, reproducible workflows and useful artifacts.

## Primary Users

- Analysts and operations professionals who work across datasets and documents.
- Knowledge workers who need explainable answers without writing every data transformation themselves.
- Technical teams that need reusable, inspectable workflows rather than opaque chat responses.

These user definitions are initial hypotheses and require real-user validation.

## V1 Scope

V1 is intended to support a bounded workflow that:

- accepts a natural-language goal;
- works with structured files and unstructured documents;
- plans and invokes typed, constrained tools;
- performs calculations and transformations deterministically;
- retrieves document evidence with provenance;
- verifies outputs and reports uncertainty or insufficient evidence;
- produces useful downloadable artifacts and a trace; and
- saves a workflow so it can be inspected and reproduced.

The current implementation covers this bounded scope with task-scoped typed tools, offline deterministic demonstrations, and an environment-configured production model adapter. Hosted-model quality, multi-user controls, and deployed operations still require separate validation.

## Non-Goals

- A general autonomous agent that can take unrestricted actions.
- Unsafe execution of arbitrary model-generated Python, SQL, or shell commands.
- A multi-agent system without evaluation evidence that it is necessary.
- Supporting every data source, file type, or enterprise integration in V1.
- Replacing expert judgment for high-stakes decisions.
- Adding technologies for résumé value rather than product need.

## Signature Mixed-Reasoning Capability

The signature capability will combine structured and unstructured evidence in one reproducible workflow. For example, deterministic tools may compute results from tabular records while retrieval tools locate relevant policy language in documents; the orchestrator may then relate those results, cite their origins, identify gaps, and explain the conclusion. Calculations must come from deterministic tools, not model arithmetic.

## Artifacts

Artifacts are first-class outputs rather than incidental downloads. Planned artifact types include cleaned datasets, Excel workbooks, charts, reports, verification reports, and saved workflows. Each artifact should eventually carry sufficient provenance to understand its inputs and production steps.

## Human-in-the-Loop Behavior

The system should ask for user input when intent is materially ambiguous, evidence conflicts, or an operation could be destructive, irreversible, unexpectedly broad, or security-sensitive. Confirmations should describe the proposed action and its scope. Routine read-only work should not create unnecessary friction.

## Transform-to-Template V1

The workspace accepts one to eight CSV/XLSX sources, an exact CSV/XLSX target template, and optional retrieved policy evidence. It inspects workbook structure and source profiles, proposes mappings in a deterministic evidence order, and returns field-specific clarification requirements instead of inventing missing business data. Confirmed or high-confidence mappings feed typed joins, cleaning, arithmetic/concatenation derivations, and policy-rate derivations; suspicious multiplication, excessive unmatched rows, incompatible values, and unresolved required fields fail closed.

Successful XLSX jobs write a new artifact while preserving sheet names/order, unrelated sheets, formats, and trusted local template formulas. CSV jobs preserve exact headers/order. Both formats neutralize untrusted formula-like source text, reopen the result, validate schema and required/unique fields, attach per-field provenance, and save a recipe that pins mappings/rules/evidence. Reruns accept replacement sources/templates only when their roles, schemas, and structural template fingerprint remain compatible.

## Evidence-First Behavior

The system must distinguish sourced facts, deterministic results, model interpretation, assumptions, and unknowns. It must not fabricate missing information. When evidence is insufficient, it should say so explicitly and identify what would be needed to continue. Outputs should be traceable to source material and tool results.

## Initial Demo: `grades.csv` + `syllabus.pdf`

The implemented demonstration combines a grade table with syllabus policies. A user can ask how deterministic grade calculations apply and which syllabus passages govern the interpretation. The bounded workflow produces computed results, cited document evidence, explicit insufficiency/conflict states, verification findings, and a trace.

## August Sales Operations Demo

The August sales workflow is the recruiter-facing north-star demonstration. It accepts transactions, customers, regional targets, a commission-policy PDF, and a natural-language goal. The one orchestrator inspects authorized resources, identifies dataset roles from schemas, retrieves cited policy evidence, and invokes a typed deterministic report tool. The tool preserves originals, performs bounded cleaning, diagnoses both joins, calculates regional and salesperson performance, calculates commissions only when the policy establishes one unambiguous rate, creates a six-sheet management workbook with decision-useful charts, and saves a schema-checked recipe.

Numeric answer claims identify the exact deterministic fact they depend on. Commission claims must additionally cite observed policy evidence. Missing/conflicting policy, conflicting business keys, duplicate targets, and row-multiplying joins fail closed; unmatched customers and missing target relationships remain visible as warnings and workbook diagnostics. The browser exposes concise execution facts rather than hidden reasoning. Synthetic fixed-ground-truth evaluation is not evidence of hosted-model or production-data performance.
