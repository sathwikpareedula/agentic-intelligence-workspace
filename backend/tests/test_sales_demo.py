"""Known-ground-truth evaluation for the north-star August sales demo."""

from pathlib import Path
import base64
from io import BytesIO
from uuid import UUID

import pandas as pd
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.models.grades import PolicyEvidence
from app.models.retrieval import SourceReference
from app.services.sales_report import SalesReportError, build_august_sales_report
from app.agent.models import AnswerClaim, Complete, ToolCall
from app.agent.orchestrator import AgentOrchestrator
from app.agent.providers import FakeModelProvider
from app.agent.tools import ToolRegistry, sales_report_tool
from app.agent.verification import EvidenceVerifier
from app.models.workflows import WorkflowCreate, WorkflowStep
from app.services.workflows import InMemoryWorkflowRepository, WorkflowService
from app.services.artifacts import InMemoryArtifactRepository
from app.main import app
from app.config import get_settings
from app.dependencies import _demo_repository, _deterministic_provider


ROOT = Path(__file__).parents[2]


def _evidence(text="August commission policy: Salespeople earn a commission rate of 5% of completed net sales after discounts."):
    return [PolicyEvidence(text=text, source=SourceReference(document_id=UUID(int=1), filename="commission_policy.pdf", page_number=1, chunk_id=UUID(int=2)))]


def test_north_star_sales_report_known_outputs_and_provenance() -> None:
    transactions = pd.read_csv(ROOT / "sample_data" / "august_transactions.csv")
    original = transactions.copy(deep=True)
    result = build_august_sales_report(
        transactions,
        pd.read_csv(ROOT / "sample_data" / "sales_customers.csv"),
        pd.read_csv(ROOT / "sample_data" / "sales_targets.csv"),
        _evidence(),
    )

    pd.testing.assert_frame_equal(transactions, original)
    assert result.cleaned_transactions["transaction_id"].tolist() == ["T1001", "T1002", "T1003", "T1005"]
    regions = result.regional_performance.set_index("region")
    assert regions.loc["North", "net_sales"] == 1350
    assert regions.loc["North", "variance"] == -650
    assert regions.loc["South", "net_sales"] == 800
    assert regions.loc["South", "variance"] == -200
    assert regions.loc["West", "variance"] == -500
    commissions = result.commissions.set_index("salesperson")
    assert commissions.loc["Alice", "commission"] == 67.5
    assert commissions.loc["Bob", "commission"] == 50
    assert result.join_diagnostics.left_unmatched_rows == 1
    assert result.citations[0].filename == "commission_policy.pdf"
    assert result.artifact.content.startswith(b"PK")
    assert result.artifact.provenance["commission_rate"] == "5%"
    workbook = load_workbook(BytesIO(result.artifact.content), data_only=False)
    assert workbook.sheetnames == ["Cleaned Transactions", "Regional Performance", "Commissions", "Summary", "Provenance"]
    assert workbook["Cleaned Transactions"].max_row == 5
    assert workbook["Regional Performance"]["A2"].value == "North"
    assert workbook["Regional Performance"]["D2"].value == -650
    assert workbook["Commissions"]["C2"].value == 67.5
    assert len(workbook["Summary"]._charts) == 1


def test_sales_report_refuses_missing_or_conflicting_policy() -> None:
    frames = (
        pd.read_csv(ROOT / "sample_data" / "august_transactions.csv"),
        pd.read_csv(ROOT / "sample_data" / "sales_customers.csv"),
        pd.read_csv(ROOT / "sample_data" / "sales_targets.csv"),
    )
    for evidence, message in [([], "does not establish"), (_evidence() + _evidence("Commission rate is 7%."), "conflicting")]:
        try:
            build_august_sales_report(*frames, evidence)
        except SalesReportError as exc:
            assert message in str(exc)
        else:
            raise AssertionError("Invalid policy evidence must fail.")


def test_sales_report_tool_is_verified_traced_and_rerunnable() -> None:
    def resource(name):
        return {"filename": name, "content_base64": base64.b64encode((ROOT / "sample_data" / name).read_bytes()).decode()}

    evidence = [item.model_dump(mode="json") for item in _evidence()]
    arguments = {
        "transactions": resource("august_transactions.csv"),
        "customers": resource("sales_customers.csv"),
        "targets": resource("sales_targets.csv"),
        "policy_evidence": evidence,
    }
    provider = FakeModelProvider([
        ToolCall(tool="sales.august_report", arguments=arguments),
        Complete(
            answer="North underperformed target by 650 and Alice earned 67.5 in commission.",
            claims=[
                AnswerClaim(text="North underperformed by 650", kind="numeric", value=650),
                AnswerClaim(text="Alice commission is 67.5", kind="numeric", value=67.5),
                AnswerClaim(text="Commission rate is policy-grounded", kind="document", source_ids=[str(UUID(int=2))]),
            ],
        ),
    ])
    artifact_repository = InMemoryArtifactRepository()
    registry = ToolRegistry([sales_report_tool(artifact_repository)])
    execution = AgentOrchestrator(provider, registry, EvidenceVerifier()).execute("Prepare the August sales report")
    assert execution.status == "completed"
    assert execution.verification.status == "verified"
    assert execution.trace[0].artifact_ids
    assert execution.trace[0].source_ids == [str(UUID(int=2))]

    workflows = WorkflowService(InMemoryWorkflowRepository(), registry)
    workflow = workflows.create(WorkflowCreate(name="August sales", source_task_id=execution.task_id, steps=[WorkflowStep(tool="sales.august_report", arguments=arguments)]))
    rerun = workflows.rerun(workflow.workflow_id, {})
    assert rerun.status == "completed"
    assert rerun.observations[0].result["regional_performance"]["rows"][0]["region"] == "North"

    previous_repository = app.state.artifact_repository
    app.state.artifact_repository = artifact_repository
    try:
        download = TestClient(app).get(f"/artifacts/{execution.trace[0].artifact_ids[0]}")
    finally:
        app.state.artifact_repository = previous_repository
    assert download.status_code == 200
    assert download.content.startswith(b"PK")
    assert download.headers["content-disposition"] == 'attachment; filename="august_sales_management_report.xlsx"'


def test_august_sales_demo_runs_through_public_http_and_downloads_workbook(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "demo")
    get_settings.cache_clear()
    _demo_repository.cache_clear()
    _deterministic_provider.cache_clear()
    client = TestClient(app)
    files = {
        "transactions": ("august_transactions.csv", (ROOT / "sample_data" / "august_transactions.csv").read_bytes(), "text/csv"),
        "customers": ("sales_customers.csv", (ROOT / "sample_data" / "sales_customers.csv").read_bytes(), "text/csv"),
        "targets": ("sales_targets.csv", (ROOT / "sample_data" / "sales_targets.csv").read_bytes(), "text/csv"),
        "policy": ("commission_policy.pdf", (ROOT / "sample_data" / "commission_policy.pdf").read_bytes(), "application/pdf"),
    }
    try:
        response = client.post("/sales/reports/august", files=files)
    finally:
        get_settings.cache_clear()
        _demo_repository.cache_clear()
        _deterministic_provider.cache_clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert "North has the largest target shortfall at 650.00" in body["answer"]
    assert [step["requested_tool"] for step in body["trace"]] == ["document.search", "sales.august_report"]
    assert body["verification"]["status"] == "verified"
    assert body["citations"][0]["filename"] == "commission_policy.pdf"
    assert body["artifacts"][0]["download_url"].startswith("/artifacts/")

    download = client.get(body["artifacts"][0]["download_url"])
    assert download.status_code == 200
    workbook = load_workbook(BytesIO(download.content), data_only=False)
    assert workbook["Summary"]["B5"].value == 2350
    assert workbook["Summary"]["B6"].value == 117.5
