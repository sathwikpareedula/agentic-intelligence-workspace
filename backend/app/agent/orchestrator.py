"""Bounded observe/replan loop for one orchestrating model."""

from datetime import datetime, timezone
from time import perf_counter

from pydantic import ValidationError

from app.agent.models import (
    AgentExecution,
    ArtifactReference,
    Complete,
    ExecutionStage,
    ToolObservation,
    TraceStep,
    WorkflowReference,
)
from app.models.retrieval import SourceReference
from app.agent.providers import ModelProvider, ModelProviderError
from app.agent.tools import ToolRegistry
from app.agent.verification import EvidenceVerifier
from app.services.sales_report import SalesReportError


class AgentOrchestrator:
    def __init__(self, provider: ModelProvider, registry: ToolRegistry, verifier: EvidenceVerifier | None = None) -> None:
        self._provider = provider
        self._registry = registry
        self._verifier = verifier

    def execute(self, goal: str, max_iterations: int = 8) -> AgentExecution:
        started_at = datetime.now(timezone.utc)
        observations: list[ToolObservation] = []
        trace: list[TraceStep] = []
        for step_number in range(1, max_iterations + 1):
            try:
                decision = self._provider.decide(goal, observations)
            except ModelProviderError as exc:
                return self._finish(
                    goal,
                    started_at,
                    trace,
                    observations,
                    "failed",
                    failure_reason=str(exc),
                    failure_code=exc.code,
                )
            except Exception:
                return self._finish(
                    goal,
                    started_at,
                    trace,
                    observations,
                    "failed",
                    failure_reason="Orchestrator provider failed unexpectedly.",
                    failure_code="provider_failure",
                )
            if isinstance(decision, Complete):
                verification = self._verifier.verify(decision.claims, observations) if self._verifier else None
                unresolved_failure = bool(
                    observations
                    and not observations[-1].success
                    and (observations[-1].error_code in {"tool_error", "workflow_failed"} or not observations[-1].recoverable)
                )
                return self._finish(
                    goal,
                    started_at,
                    trace,
                    observations,
                    "failed" if unresolved_failure else "completed",
                    answer=decision.answer,
                    failure_reason=observations[-1].summary if unresolved_failure else None,
                    failure_code=observations[-1].error_code if unresolved_failure else None,
                    verification=verification,
                )

            began = perf_counter()
            tool = self._registry.get(decision.tool)
            validated = None
            if tool is None:
                observation = ToolObservation(success=False, summary=f"Unknown tool '{decision.tool}'.", error_code="unknown_tool")
            else:
                try:
                    arguments = tool.input_model.model_validate(decision.arguments)
                    validated = _trace_safe(arguments.model_dump(mode="json"))
                    observation = tool.handler(arguments)
                except ValidationError as exc:
                    observation = ToolObservation(
                        success=False,
                        summary=_validation_summary(exc),
                        error_code="invalid_arguments",
                    )
                except SalesReportError as exc:
                    observation = ToolObservation(
                        success=False, summary=str(exc), error_code="sales_report_failed",
                        result={"status": exc.status}, recoverable=False,
                    )
                except Exception as exc:
                    observation = ToolObservation(success=False, summary=str(exc), error_code="tool_error")
            observation = observation.model_copy(
                update={
                    "tool_name": decision.tool,
                    "arguments": validated if validated is not None else _trace_safe(decision.arguments),
                }
            )
            observations.append(observation)
            trace.append(
                TraceStep(
                    step=step_number,
                    requested_tool=decision.tool,
                    validated_arguments=validated,
                    success=observation.success,
                    observation=observation.summary,
                    error_code=observation.error_code,
                    artifact_ids=observation.artifact_ids,
                    source_ids=observation.source_ids,
                    duration_ms=(perf_counter() - began) * 1000,
                    stage=_tool_stage(decision.tool),
                    metadata=(observation.result or {}).get("trace_metadata", {}),
                    warnings=observation.warnings,
                )
            )
        return self._finish(
            goal,
            started_at,
            trace,
            observations,
            "iteration_limit",
            failure_reason=f"Agent reached the {max_iterations}-iteration limit.",
            failure_code="iteration_limit",
        )

    @staticmethod
    def _finish(
        goal,
        started_at,
        trace,
        observations,
        status,
        answer=None,
        failure_reason=None,
        failure_code=None,
        verification=None,
    ) -> AgentExecution:
        return AgentExecution(
            goal=goal,
            status=status,
            answer=answer,
            trace=trace,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            failure_reason=failure_reason,
            failure_code=failure_code,
            verification=verification,
            citations=_citations(observations),
            evidence=[
                {"text": hit["text"], "source": hit["source"]}
                for item in observations if item.success and item.tool_name == "document.search"
                for hit in (item.result or {}).get("hits", [])
            ],
            artifacts=_artifacts(observations),
            stages=_execution_stages(goal, trace, observations, status, verification),
            warnings=list(dict.fromkeys(warning for item in observations for warning in item.warnings)),
            saved_workflow=_saved_workflow(observations),
        )


def _validation_summary(exc: ValidationError) -> str:
    problems = []
    for error in exc.errors(include_context=False, include_input=False):
        location = ".".join(str(part) for part in error["loc"]) or "arguments"
        problems.append(f"{location}: {error['msg']}")
    return "Invalid tool arguments: " + "; ".join(problems)


def _trace_safe(arguments: dict) -> dict:
    """Retain validated parameters without copying potentially sensitive file bodies."""
    result = {}
    for key, value in arguments.items():
        normalized_key = str(key).lower().replace("-", "_")
        if normalized_key == "content_base64" and isinstance(value, str):
            result[key] = f"<redacted:{len(value)} chars>"
        elif any(marker in normalized_key for marker in ("api_key", "authorization", "password", "secret", "token")):
            result[key] = "<redacted>"
        elif isinstance(value, dict):
            result[key] = _trace_safe(value)
        elif isinstance(value, list):
            result[key] = [_trace_safe(item) if isinstance(item, dict) else item for item in value]
        else:
            result[key] = value
    return result


def _citations(observations: list[ToolObservation]) -> list[SourceReference]:
    citations: dict[str, SourceReference] = {}
    for observation in observations:
        if not observation.result:
            continue
        for candidate in _source_candidates(observation.result):
            try:
                source = SourceReference.model_validate(candidate)
            except ValidationError:
                continue
            citations[str(source.chunk_id)] = source
    return list(citations.values())


def _source_candidates(value):
    if isinstance(value, dict):
        if {"document_id", "filename", "page_number", "chunk_id"}.issubset(value):
            yield value
        for child in value.values():
            yield from _source_candidates(child)
    elif isinstance(value, list):
        for child in value:
            yield from _source_candidates(child)


def _artifacts(observations: list[ToolObservation]) -> list[ArtifactReference]:
    artifacts: dict[str, ArtifactReference] = {}
    for observation in observations:
        for candidate in _artifact_candidates(observation.result):
            try:
                artifact = ArtifactReference.model_validate(candidate)
            except ValidationError:
                continue
            artifacts[str(artifact.artifact_id)] = artifact
    return list(artifacts.values())


def _artifact_candidates(value):
    if isinstance(value, dict):
        if {"artifact_id", "filename", "media_type", "download_url", "row_count", "column_count"}.issubset(value):
            yield value
        for child in value.values():
            yield from _artifact_candidates(child)
    elif isinstance(value, list):
        for child in value:
            yield from _artifact_candidates(child)


def _tool_stage(tool_name: str) -> str:
    if tool_name == "resource.list":
        return "Plan"
    if tool_name in {"dataset.inspect", "dataset.profile"}:
        return "Inspect data"
    if tool_name == "document.search":
        return "Retrieve policy"
    if tool_name.startswith("sales."):
        return "Analyze and export"
    if tool_name.startswith("workflow."):
        return "Rerun workflow"
    if tool_name.startswith("dataset.join"):
        return "Join"
    if tool_name.startswith("dataset."):
        return "Transform data"
    return "Execute tool"


def _execution_stages(goal, trace, observations, status, verification) -> list[ExecutionStage]:
    stages = [
        ExecutionStage(name="Goal", status="completed", explanation=goal),
        ExecutionStage(
            name="Plan",
            status="completed",
            explanation="Executed a bounded plan using only task-scoped typed tools and deterministic calculations.",
        ),
    ]
    for trace_step, observation in zip(trace, observations, strict=False):
        if trace_step.requested_tool == "resource.list":
            continue
        if observation.stages:
            stages.extend(observation.stages)
            continue
        stages.append(
            ExecutionStage(
                name=trace_step.stage or "Execute tool",
                status="completed" if trace_step.success else "failed",
                explanation=trace_step.observation,
                tool_name=trace_step.requested_tool,
                evidence_ids=trace_step.source_ids,
                artifact_ids=trace_step.artifact_ids,
                diagnostics=trace_step.metadata,
            )
        )
    if verification is not None:
        verification_status = "warning" if verification.status == "verified_with_warnings" else (
            "completed" if verification.status == "verified" else "failed"
        )
        stages.append(
            ExecutionStage(
                name="Verify",
                status=verification_status,
                explanation=f"Claim verification finished with status {verification.status.replace('_', ' ')}.",
                verification_result=verification.status,
            )
        )
    stages.append(
        ExecutionStage(
            name="Complete",
            status="completed" if status == "completed" else "failed",
            explanation="Task completed with traceable outputs." if status == "completed" else f"Task ended with status {status}.",
        )
    )
    return stages


def _saved_workflow(observations: list[ToolObservation]) -> WorkflowReference | None:
    for observation in reversed(observations):
        result = observation.result or {}
        candidate = result.get("saved_workflow")
        if isinstance(candidate, dict):
            try:
                return WorkflowReference.model_validate(candidate)
            except ValidationError:
                continue
    return None
