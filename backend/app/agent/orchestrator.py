"""Bounded observe/replan loop for one orchestrating model."""

from datetime import datetime, timezone
from time import perf_counter

from pydantic import ValidationError

from app.agent.models import AgentExecution, ArtifactReference, Complete, ToolObservation, TraceStep
from app.models.retrieval import SourceReference
from app.agent.providers import ModelProvider, ModelProviderError
from app.agent.tools import ToolRegistry
from app.agent.verification import EvidenceVerifier


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
                return self._finish(goal, started_at, trace, observations, "completed", answer=decision.answer, verification=verification)

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
            artifacts=_artifacts(observations),
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
