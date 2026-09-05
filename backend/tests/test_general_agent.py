"""General task-scoped orchestration tests over data, documents, and artifacts."""

import base64
from pathlib import Path

from app.agent.models import (
    AgentDatasetResource,
    AgentTaskResources,
    AnswerClaim,
    Complete,
    ToolCall,
)
from app.agent.orchestrator import AgentOrchestrator
from app.agent.providers import FakeModelProvider
from app.agent.tools import ToolRegistry, dataset_tools, general_task_tools
from app.agent.verification import EvidenceVerifier
from app.embeddings.deterministic import DeterministicEmbeddingProvider
from app.repositories.documents import InMemoryDocumentRepository
from app.services.artifacts import InMemoryArtifactRepository
from app.services.retrieval import RetrievalService
from app.models.workflows import WorkflowCreate, WorkflowStep
from app.services.workflows import InMemoryWorkflowRepository, WorkflowService


ROOT = Path(__file__).parents[2]


def _dataset(filename: str, content: bytes) -> AgentDatasetResource:
    return AgentDatasetResource(
        filename=filename,
        content_base64=base64.b64encode(content).decode("ascii"),
    )


def test_general_agent_selects_deterministic_aggregation_tool() -> None:
    resources = AgentTaskResources(
        datasets=[_dataset("sales.csv", b"region,amount\nNorth,100\nNorth,200\nSouth,50\n")]
    )
    artifacts = InMemoryArtifactRepository()
    registry = ToolRegistry(general_task_tools(None, resources, artifacts))
    provider = FakeModelProvider(
        [
            ToolCall(tool="resource.list", arguments={}),
            ToolCall(tool="dataset.inspect", arguments={"dataset": "sales.csv"}),
            ToolCall(
                tool="dataset.transform",
                arguments={
                    "dataset": "sales.csv",
                    "operations": [
                        {
                            "type": "group",
                            "group_by": ["region"],
                            "aggregations": [{"column": "amount", "function": "sum", "alias": "total"}],
                        }
                    ],
                },
            ),
            Complete(
                answer="North totals 300.",
                claims=[AnswerClaim(text="North totals 300.", kind="numeric", value=300)],
            ),
        ]
    )

    execution = AgentOrchestrator(provider, registry, EvidenceVerifier()).execute("Total sales by region")

    assert execution.status == "completed"
    assert [step.requested_tool for step in execution.trace] == [
        "resource.list",
        "dataset.inspect",
        "dataset.transform",
    ]
    assert execution.verification is not None
    assert execution.verification.status == "verified"


def test_general_agent_replans_invalid_dataset_arguments_with_failure_context() -> None:
    resources = AgentTaskResources(datasets=[_dataset("sales.csv", b"region,amount\nNorth,100\n")])
    registry = ToolRegistry(general_task_tools(None, resources, InMemoryArtifactRepository()))

    class ReplanningProvider:
        def decide(self, goal, observations):
            if not observations:
                return ToolCall(tool="dataset.inspect", arguments={"dataset": "missing.csv"})
            if len(observations) == 1:
                failure = observations[0]
                assert failure.tool_name == "dataset.inspect"
                assert failure.arguments == {"dataset": "missing.csv"}
                assert failure.error_code == "tool_error"
                assert failure.recoverable is True
                return ToolCall(tool="dataset.inspect", arguments={"dataset": "sales.csv"})
            return Complete(answer="Recovered after selecting the bound dataset.")

    execution = AgentOrchestrator(ReplanningProvider(), registry).execute("Inspect the sales data")

    assert execution.status == "completed"
    assert [step.success for step in execution.trace] == [False, True]


def test_general_agent_handles_mixed_structured_and_grounded_document_task() -> None:
    repository = InMemoryDocumentRepository()
    retrieval = RetrievalService(repository, DeterministicEmbeddingProvider(), 20 * 1024 * 1024)
    policy = (ROOT / "sample_data" / "commission_policy.pdf").read_bytes()
    ingested = retrieval.ingest_pdf("commission_policy.pdf", policy, 1200, 200)
    source_id = str(ingested.chunks[0].chunk_id)
    resources = AgentTaskResources(
        datasets=[
            _dataset("transactions.csv", b"customer_id,amount\nC1,100\nC2,50\n"),
            _dataset("customers.csv", b"customer_id,region\nC1,North\nC2,South\n"),
        ],
        document_ids=[ingested.document_id],
    )
    registry = ToolRegistry(general_task_tools(retrieval, resources, InMemoryArtifactRepository()))
    provider = FakeModelProvider(
        [
            ToolCall(
                tool="dataset.join",
                arguments={
                    "left_dataset": "transactions.csv",
                    "right_dataset": "customers.csv",
                    "join": {"left_on": ["customer_id"], "right_on": ["customer_id"], "how": "left"},
                    "operations": [
                        {
                            "type": "group",
                            "group_by": ["region"],
                            "aggregations": [{"column": "amount", "function": "sum", "alias": "total"}],
                        }
                    ],
                },
            ),
            ToolCall(
                tool="document.search",
                arguments={"query": "commission rate completed net sales", "top_k": 3},
            ),
            Complete(
                answer="North totals 100. The commission rule is grounded in the uploaded policy.",
                claims=[
                    AnswerClaim(text="North totals 100.", kind="numeric", value=100),
                    AnswerClaim(
                        text="The commission rule comes from the uploaded policy.",
                        kind="document",
                        source_ids=[source_id],
                    ),
                ],
            ),
        ]
    )

    execution = AgentOrchestrator(provider, registry, EvidenceVerifier()).execute(
        "Join sales to regions and apply the documented commission rule"
    )

    assert execution.status == "completed"
    assert [step.requested_tool for step in execution.trace] == ["dataset.join", "document.search"]
    assert execution.trace[0].success is True
    assert execution.trace[1].source_ids == [source_id]
    assert execution.verification is not None
    assert execution.verification.status == "verified"


def test_general_agent_creates_complete_artifact_without_model_computation() -> None:
    resources = AgentTaskResources(
        datasets=[_dataset("sales.csv", b"region,amount\nNorth,100\nNorth,200\nSouth,50\n")]
    )
    artifacts = InMemoryArtifactRepository()
    registry = ToolRegistry(general_task_tools(None, resources, artifacts))
    provider = FakeModelProvider(
        [
            ToolCall(
                tool="dataset.export",
                arguments={
                    "dataset": "sales.csv",
                    "format": "xlsx",
                    "operations": [
                        {
                            "type": "group",
                            "group_by": ["region"],
                            "aggregations": [{"column": "amount", "function": "sum", "alias": "total"}],
                        }
                    ],
                },
            ),
            Complete(answer="The grouped workbook is ready."),
        ]
    )

    execution = AgentOrchestrator(provider, registry).execute("Create a regional sales workbook")

    assert execution.status == "completed"
    assert len(execution.artifacts) == 1
    artifact = artifacts.get(execution.artifacts[0].artifact_id)
    assert artifact is not None
    assert artifact.row_count == 2
    assert artifact.content.startswith(b"PK")


def test_general_agent_can_run_only_a_bound_saved_workflow() -> None:
    artifacts = InMemoryArtifactRepository()
    workflow_service = WorkflowService(InMemoryWorkflowRepository(), ToolRegistry(dataset_tools()), artifacts)
    encoded = base64.b64encode(b"region,amount\nNorth,100\n").decode("ascii")
    workflow = workflow_service.create(
        WorkflowCreate(
            name="Inspect sales",
            steps=[WorkflowStep(
                tool="dataset.inspect",
                arguments={"filename": "sales.csv", "content_base64": encoded},
                expected_columns=["region", "amount"],
            )],
        )
    )
    resources = AgentTaskResources(workflow_ids=[workflow.workflow_id])
    registry = ToolRegistry(general_task_tools(None, resources, artifacts, workflow_service))
    provider = FakeModelProvider(
        [
            ToolCall(tool="workflow.run", arguments={"workflow_id": str(workflow.workflow_id)}),
            Complete(answer="The saved workflow completed."),
        ]
    )

    execution = AgentOrchestrator(provider, registry).execute("Run the saved inspection workflow")

    assert execution.status == "completed"
    assert execution.trace[0].requested_tool == "workflow.run"
    assert execution.trace[0].success is True
