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

This is intended scope, not implemented functionality.

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

## Evidence-First Behavior

The system must distinguish sourced facts, deterministic results, model interpretation, assumptions, and unknowns. It must not fabricate missing information. When evidence is insufficient, it should say so explicitly and identify what would be needed to continue. Outputs should be traceable to source material and tool results.

## Initial Demo: `grades.csv` + `syllabus.pdf`

The first planned demonstration will combine a grade table with syllabus policies. A user might ask who is at risk, how deterministic grade calculations apply, and which syllabus passages govern the interpretation. The workflow should eventually produce computed results, cited document evidence, stated assumptions, verification findings, and a useful artifact. No part of this demo is implemented yet.

## Future Demo: August Sales Recruiter

A later demonstration may help a sales recruiter analyze August pipeline or activity data alongside unstructured candidate, role, or process documents. Its exact question, dataset, privacy constraints, and success criteria must be defined before implementation. This is a future concept, not a current feature.

