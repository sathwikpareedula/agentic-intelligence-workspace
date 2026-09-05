"""Controlled offline evaluation of generalized bounded-agent contracts."""

import argparse
import base64
import json
from pathlib import Path

from app.agent.models import AgentDatasetResource, AgentTaskResources, AnswerClaim, Complete, ToolCall
from app.agent.orchestrator import AgentOrchestrator
from app.agent.providers import FakeModelProvider
from app.agent.tools import ToolRegistry, general_task_tools
from app.agent.verification import EvidenceVerifier
from app.services.artifacts import InMemoryArtifactRepository


def _dataset(filename: str, content: bytes) -> AgentDatasetResource:
    return AgentDatasetResource(filename=filename, content_base64=base64.b64encode(content).decode("ascii"))


def evaluate_agent_cases(path: Path) -> dict:
    expected = json.loads(path.read_text(encoding="utf-8"))
    resources = AgentTaskResources(
        datasets=[
            _dataset("sales.csv", b"region,amount\nNorth,100\nNorth,200\nSouth,50\n"),
            _dataset("targets.csv", b"region,target\nNorth,400\nSouth,75\n"),
        ]
    )
    artifacts = InMemoryArtifactRepository()
    registry = ToolRegistry(general_task_tools(None, resources, artifacts))
    cases = []

    aggregate = AgentOrchestrator(
        FakeModelProvider(
            [
                ToolCall(
                    tool="dataset.transform",
                    arguments={
                        "dataset": "sales.csv",
                        "operations": [{
                            "type": "group",
                            "group_by": ["region"],
                            "aggregations": [{"column": "amount", "function": "sum", "alias": "total"}],
                        }],
                    },
                ),
                Complete(
                    answer="North totals 300.",
                    claims=[AnswerClaim(text="North totals 300.", kind="numeric", value=300)],
                ),
            ]
        ),
        registry,
        EvidenceVerifier(),
    ).execute("Total sales by region")
    cases.append(_case(
        "deterministic_aggregation",
        aggregate.status == "completed"
        and aggregate.trace[0].requested_tool == expected["aggregation_tool"]
        and aggregate.verification is not None
        and aggregate.verification.status == "verified",
        {"tool": aggregate.trace[0].requested_tool, "verification": aggregate.verification.status if aggregate.verification else None},
    ))

    joined = AgentOrchestrator(
        FakeModelProvider(
            [
                ToolCall(
                    tool="dataset.join",
                    arguments={
                        "left_dataset": "sales.csv",
                        "right_dataset": "targets.csv",
                        "join": {"left_on": ["region"], "right_on": ["region"], "how": "left"},
                        "operations": [{
                            "type": "group",
                            "group_by": ["region", "target"],
                            "aggregations": [{"column": "amount", "function": "sum", "alias": "total"}],
                        }],
                    },
                ),
                Complete(answer="Joined totals and targets."),
            ]
        ),
        registry,
    ).execute("Join sales and targets")
    cases.append(_case(
        "join_selection",
        joined.status == "completed" and joined.trace[0].requested_tool == expected["join_tool"],
        {"tool": joined.trace[0].requested_tool, "status": joined.status},
    ))

    replanned = AgentOrchestrator(
        FakeModelProvider(
            [
                ToolCall(tool="dataset.inspect", arguments={"dataset": "missing.csv"}),
                ToolCall(tool="dataset.inspect", arguments={"dataset": "sales.csv"}),
                Complete(answer="Recovered."),
            ]
        ),
        registry,
    ).execute("Inspect sales")
    cases.append(_case(
        "recoverable_replanning",
        [step.success for step in replanned.trace] == [False, True],
        {"successes": [step.success for step in replanned.trace]},
    ))

    limited = AgentOrchestrator(
        FakeModelProvider([ToolCall(tool="resource.list", arguments={}) for _ in range(4)]),
        registry,
    ).execute("Loop", max_iterations=expected["iteration_limit"])
    cases.append(_case(
        "iteration_limit",
        limited.status == "iteration_limit" and len(limited.trace) == expected["iteration_limit"],
        {"status": limited.status, "steps": len(limited.trace)},
    ))

    insufficient = AgentOrchestrator(
        FakeModelProvider(
            [Complete(
                answer="The available resources do not establish the policy.",
                claims=[AnswerClaim(text="Uncited policy claim", kind="document")],
            )]
        ),
        registry,
        EvidenceVerifier(),
    ).execute("State the policy")
    cases.append(_case(
        "insufficient_evidence",
        insufficient.verification is not None
        and insufficient.verification.status == expected["insufficient_evidence_status"],
        {"verification": insufficient.verification.status if insufficient.verification else None},
    ))

    passed = sum(case["passed"] for case in cases)
    return {
        "case_count": len(cases),
        "passed_count": passed,
        "failed_count": len(cases) - passed,
        "case_pass_rate": passed / len(cases) if cases else 0.0,
        "cases": cases,
        "scope": "Controlled scripted-provider orchestration; no hosted model, embeddings, or live database.",
    }


def _case(name: str, passed: bool, observed: dict) -> dict:
    return {"name": name, "passed": bool(passed), "observed": observed}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run controlled generalized-agent evaluations.")
    parser.add_argument("path", type=Path, help="Path to agent evaluation expectations JSON.")
    args = parser.parse_args()
    result = evaluate_agent_cases(args.path)
    print(json.dumps(result, indent=2))
    if result["failed_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
