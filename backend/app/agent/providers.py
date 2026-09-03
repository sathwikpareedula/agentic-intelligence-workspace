"""Provider boundary for an orchestrating model and deterministic test provider."""

from collections.abc import Iterable
from typing import Protocol

from app.agent.models import ModelDecision, ToolObservation


class ModelProvider(Protocol):
    def decide(self, goal: str, observations: list[ToolObservation]) -> ModelDecision: ...


class FakeModelProvider:
    """Returns a fixed sequence of decisions for offline deterministic tests."""

    def __init__(self, decisions: Iterable[ModelDecision]) -> None:
        self._decisions = iter(decisions)

    def decide(self, goal: str, observations: list[ToolObservation]) -> ModelDecision:
        try:
            return next(self._decisions)
        except StopIteration as exc:
            raise RuntimeError("Fake model exhausted its scripted decisions.") from exc
