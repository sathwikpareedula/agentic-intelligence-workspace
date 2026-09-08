"""Strict typed tool registry and adapters for existing deterministic services."""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.agent.models import AgentDatasetResource, AgentTaskResources, ExecutionStage, ToolObservation
from app.models.retrieval import RetrievalRequest
from app.models.grades import PolicyEvidence, RequiredFinalInput
from app.models.transformations import JoinSpec, Transformation, TransformRequest
from app.models.workflows import WorkflowCreate, WorkflowStep
from app.models.template_transforms import (
    FilePayload,
    SourcePayload,
    TransformExecutionRequest,
    TransformProposalRequest,
    TransformTemplatePlan,
)
from app.models.analytics import AnalyticsPlan, AnalyticsSqlRequest
from app.models.sources import PostgresImportRequest, PostgresSourceConfig, RestSourceConfig
from app.services.datasets import inspect_dataset, load_dataset, profile_dataset
from app.services.retrieval import RetrievalService
from app.services.grades import calculate_required_final
from app.services.artifacts import ArtifactRepository, generate_artifact
from app.services.sales_report import build_august_sales_report
from app.services.transformations import apply_transformations, dataframe_result, join_datasets
from app.services.template_transforms import execute_transform, propose_transform
from app.services.postgres_source import import_source as import_postgres, inspect_table, list_catalog, test_connection
from app.services.rest_source import import_rest
from app.services.analytics import execute_dataset_analytics, execute_sql_analytics

if TYPE_CHECKING:
    from app.services.workflows import WorkflowService

InputT = TypeVar("InputT", bound=BaseModel)


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


@dataclass(frozen=True)
class TypedTool(Generic[InputT]):
    name: str
    description: str
    input_model: type[InputT]
    handler: Callable[[InputT], ToolObservation]


class ToolRegistry:
    def __init__(self, tools: list[TypedTool[Any]] | None = None) -> None:
        self._tools: dict[str, TypedTool[Any]] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: TypedTool[Any]) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> TypedTool[Any] | None:
        return self._tools.get(name)

    @property
    def specifications(self) -> list[dict[str, Any]]:
        return [
            {"name": tool.name, "description": tool.description, "input_schema": tool.input_model.model_json_schema()}
            for tool in self._tools.values()
        ]


class DatasetInput(ToolInput):
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1, max_length=14_000_000)
    sheet: str | None = None

    def content(self) -> bytes:
        try:
            return base64.b64decode(self.content_base64, validate=True)
        except ValueError as exc:
            raise ValueError("content_base64 is not valid base64.") from exc


class TransformInput(DatasetInput):
    request: TransformRequest


class AnalyticsExecuteInput(DatasetInput):
    plan: AnalyticsPlan


class JoinInput(ToolInput):
    left: DatasetInput
    right: DatasetInput
    join: JoinSpec
    left_operations: list[dict[str, Any]] = Field(default_factory=list)
    right_operations: list[dict[str, Any]] = Field(default_factory=list)


class SalesReportInput(ToolInput):
    transactions: DatasetInput
    customers: DatasetInput
    targets: DatasetInput
    policy_evidence: list[PolicyEvidence] = Field(min_length=1, max_length=20)


class BoundDatasetInspectInput(ToolInput):
    pass


class BoundDocumentSearchInput(ToolInput):
    query: str = Field(min_length=1, max_length=8000)
    top_k: int = Field(default=5, ge=1, le=20)


class BoundRequiredFinalInput(ToolInput):
    evidence: list[PolicyEvidence] = Field(min_length=1, max_length=20)
    target_letter: str = Field(default="A", pattern=r"^[A-Za-z][+-]?$")


class BoundSalesReportInput(ToolInput):
    policy_evidence: list[PolicyEvidence] = Field(min_length=1, max_length=20)


class GeneralSalesReportInput(ToolInput):
    transactions_dataset: str = Field(min_length=1, max_length=255)
    customers_dataset: str = Field(min_length=1, max_length=255)
    targets_dataset: str = Field(min_length=1, max_length=255)
    policy_evidence: list[PolicyEvidence] = Field(min_length=1, max_length=20)


class ResourceListInput(ToolInput):
    pass


class BoundDatasetReferenceInput(ToolInput):
    dataset: str = Field(min_length=1, max_length=255)


class BoundDatasetTransformInput(BoundDatasetReferenceInput):
    operations: list[Transformation] = Field(default_factory=list, max_length=30)


class BoundAnalyticsInput(BoundDatasetReferenceInput):
    plan: AnalyticsPlan


class BoundDatasetJoinInput(ToolInput):
    left_dataset: str = Field(min_length=1, max_length=255)
    right_dataset: str = Field(min_length=1, max_length=255)
    left_operations: list[Transformation] = Field(default_factory=list, max_length=30)
    right_operations: list[Transformation] = Field(default_factory=list, max_length=30)
    join: JoinSpec
    operations: list[Transformation] = Field(default_factory=list, max_length=30)


class BoundDatasetExportInput(BoundDatasetTransformInput):
    format: Literal["csv", "xlsx"]


class BoundDatasetJoinExportInput(BoundDatasetJoinInput):
    format: Literal["csv", "xlsx"]


class GeneralDocumentSearchInput(BoundDocumentSearchInput):
    document_id: UUID | None = None


class BoundWorkflowRunInput(ToolInput):
    workflow_id: UUID
    step_overrides: dict[Annotated[int, Field(ge=1)], dict[str, Any]] = Field(default_factory=dict)


class BoundWorkflowHistoryInput(ToolInput):
    workflow_id: UUID
    limit: int = Field(default=20, ge=1, le=50)


class BoundWorkflowRunDetailInput(ToolInput):
    run_id: UUID


class BoundWorkflowCompareInput(ToolInput):
    previous_run_id: UUID
    current_run_id: UUID


class BoundTemplateSource(ToolInput):
    role: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    dataset: str = Field(min_length=1, max_length=255)


class BoundTemplateProposalInput(ToolInput):
    target_dataset: str = Field(min_length=1, max_length=255)
    sources: list[BoundTemplateSource] = Field(min_length=1, max_length=8)
    required_fields: list[str] | None = None
    explicit_mappings: dict[str, str] = Field(default_factory=dict)
    documented_aliases: dict[str, list[str]] = Field(default_factory=dict)
    header_row: int | None = Field(default=None, ge=1, le=100)


class BoundTemplateExecuteInput(ToolInput):
    target_dataset: str = Field(min_length=1, max_length=255)
    sources: list[BoundTemplateSource] = Field(min_length=1, max_length=8)
    plan: TransformTemplatePlan
    policy_evidence: list[PolicyEvidence] = Field(default_factory=list, max_length=20)


class BoundNamedSourceInput(ToolInput):
    source: str = Field(min_length=1, max_length=100)


class BoundPostgresImportInput(BoundNamedSourceInput):
    schema_name: str | None = Field(default=None, max_length=63, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    table: str | None = Field(default=None, max_length=63, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    select_sql: str | None = Field(default=None, max_length=4000)


class BoundAnalyticsSqlInput(BoundNamedSourceInput):
    select_sql: str = Field(min_length=12, max_length=4000)
    max_rows: int | None = Field(default=None, ge=1, le=100_000)


def dataset_tools() -> list[TypedTool[Any]]:
    def inspect(arguments: DatasetInput) -> ToolObservation:
        dataset = load_dataset(arguments.filename, arguments.content(), arguments.sheet)
        result = inspect_dataset(dataset).model_dump(mode="json")
        return ToolObservation(success=True, summary=f"Inspected {result['row_count']} rows and {result['column_count']} columns.", result=result)

    def profile(arguments: DatasetInput) -> ToolObservation:
        dataset = load_dataset(arguments.filename, arguments.content(), arguments.sheet)
        result = profile_dataset(dataset).model_dump(mode="json")
        return ToolObservation(success=True, summary=f"Profiled {result['inspection']['row_count']} rows.", result=result)

    def transform(arguments: TransformInput) -> ToolObservation:
        dataset = load_dataset(arguments.filename, arguments.content(), arguments.sheet)
        result = dataframe_result(apply_transformations(dataset.frame, arguments.request.operations)).model_dump(mode="json")
        return ToolObservation(success=True, summary=f"Transformation produced {result['row_count']} rows.", result=result)

    def analytics(arguments: AnalyticsExecuteInput) -> ToolObservation:
        dataset = load_dataset(arguments.filename, arguments.content(), arguments.sheet)
        executed = execute_dataset_analytics(dataset, arguments.plan)
        return _analytics_observation(executed)

    return [
        TypedTool("dataset.inspect", "Inspect a CSV/XLSX schema and quality counts.", DatasetInput, inspect),
        TypedTool("dataset.profile", "Profile deterministic numeric and categorical statistics.", DatasetInput, profile),
        TypedTool("dataset.transform", "Apply the closed set of validated dataframe operations.", TransformInput, transform),
        TypedTool("analytics.execute", "Execute a typed deterministic analytical plan over an uploaded dataset.", AnalyticsExecuteInput, analytics),
    ]


def source_tools(allow_private_rest: bool = False) -> list[TypedTool[Any]]:
    def postgres_test(arguments: PostgresSourceConfig) -> ToolObservation:
        result = test_connection(arguments)
        return ToolObservation(success=True, summary=f"Connected to external database {result['database']} in read-only mode.", result=result)

    def postgres_catalog(arguments: PostgresSourceConfig) -> ToolObservation:
        catalog = list_catalog(arguments)
        return ToolObservation(
            success=True,
            summary=f"Listed {len(catalog.tables)} tables across {len(catalog.schemas)} schemas.",
            result=catalog.model_dump(mode="json"),
        )

    def postgres_import(arguments: PostgresImportRequest) -> ToolObservation:
        imported = import_postgres(arguments)
        return _imported_observation(imported, "Imported a read-only PostgreSQL result as a workspace dataset.")

    def rest_import(arguments: RestSourceConfig) -> ToolObservation:
        imported = import_rest(arguments, allow_private=allow_private_rest)
        return _imported_observation(imported, "Imported a bounded REST JSON response as a workspace dataset.")

    def analytics_sql(arguments: AnalyticsSqlRequest) -> ToolObservation:
        executed = execute_sql_analytics(arguments)
        return _analytics_observation(executed)

    return [
        TypedTool("source.postgres.test", "Test a read-only external PostgreSQL source using a password secret reference.", PostgresSourceConfig, postgres_test),
        TypedTool("source.postgres.catalog", "List non-system schemas/tables from a read-only external PostgreSQL source.", PostgresSourceConfig, postgres_catalog),
        TypedTool("source.postgres.import", "Import a bounded table or SELECT from a read-only external PostgreSQL source.", PostgresImportRequest, postgres_import),
        TypedTool("source.rest.import", "GET JSON from an approved REST URL using secret header references, never raw tokens.", RestSourceConfig, rest_import),
        TypedTool("analytics.sql", "Run one validated read-only SELECT against an external PostgreSQL source using a password secret reference.", AnalyticsSqlRequest, analytics_sql),
    ]


def _analytics_observation(executed) -> ToolObservation:
    payload = executed.model_dump(mode="json")
    return ToolObservation(
        success=True,
        summary=executed.explanation,
        result=payload,
        warnings=executed.warnings,
    )


def _imported_observation(imported, summary: str) -> ToolObservation:
    return ToolObservation(
        success=True,
        summary=summary,
        result={
            "inspection": imported.inspection.model_dump(mode="json"),
            "provenance": imported.provenance.model_dump(mode="json"),
            "dataset": imported.dataset.model_dump(mode="json"),
        },
    )


def template_transform_tool(artifact_repository: ArtifactRepository) -> TypedTool[TransformExecutionRequest]:
    """Full-content workflow tool used only for validated deterministic recipe reruns."""

    def transform(arguments: TransformExecutionRequest) -> ToolObservation:
        executed = execute_transform(arguments)
        artifact_repository.save(executed.artifact)
        return ToolObservation(
            success=True,
            summary=f"Wrote and verified {executed.artifact.row_count} rows in the supplied template.",
            result={
                "status": executed.validation.status,
                "validation": executed.validation.model_dump(mode="json"),
                "provenance": [item.model_dump(mode="json") for item in executed.provenance],
                "artifact": {
                    "artifact_id": str(executed.artifact.artifact_id),
                    "filename": executed.artifact.filename,
                    "media_type": executed.artifact.media_type,
                    "row_count": executed.artifact.row_count,
                    "column_count": executed.artifact.column_count,
                    "download_url": f"/artifacts/{executed.artifact.artifact_id}",
                },
            },
            artifact_ids=[str(executed.artifact.artifact_id)],
            source_ids=[item for field in executed.provenance for item in field.policy_evidence_ids],
            warnings=executed.validation.warnings,
        )

    return TypedTool(
        "template.transform",
        "Execute a saved deterministic transform-to-template plan, validate drift and output, and create an artifact.",
        TransformExecutionRequest,
        transform,
    )


def general_task_tools(
    service: RetrievalService | None,
    resources: AgentTaskResources,
    artifact_repository: ArtifactRepository,
    workflow_service: WorkflowService | None = None,
    allow_private_rest: bool = False,
) -> list[TypedTool[Any]]:
    """Build a general, task-scoped registry that never exposes uploaded bodies to the model."""

    datasets = {resource.filename: resource for resource in resources.all_datasets()}
    document_ids = resources.all_document_ids()
    allowed_workflows = set(resources.workflow_ids)
    inspected_datasets: set[str] = set()
    retrieved_evidence: dict[str, PolicyEvidence] = {}

    def list_resources(_: ResourceListInput) -> ToolObservation:
        return ToolObservation(
            success=True,
            summary=(
                f"Listed {len(datasets)} datasets, {len(document_ids)} documents, "
                f"and {len(allowed_workflows)} workflows bound to this task."
            ),
            result={
                "datasets": list(datasets),
                "document_ids": [str(item) for item in document_ids],
                "workflow_ids": [str(item) for item in resources.workflow_ids],
                "postgres_sources": [item.name for item in resources.postgres_sources],
                "rest_sources": [item.name for item in resources.rest_sources],
            },
        )

    tools: list[TypedTool[Any]] = [
        TypedTool(
            "resource.list",
            "List the exact dataset filenames, document IDs, and workflow IDs authorized for this task. Call this before using a resource whose identifier is unknown.",
            ResourceListInput,
            list_resources,
        )
    ]

    if datasets:
        def inspect_bound(arguments: BoundDatasetReferenceInput) -> ToolObservation:
            dataset = _load_bound_dataset(datasets, arguments.dataset)
            inspected_datasets.add(arguments.dataset)
            result = inspect_dataset(dataset).model_dump(mode="json")
            return ToolObservation(
                success=True,
                summary=f"Inspected {result['row_count']} rows and {result['column_count']} columns in {arguments.dataset}.",
                result=result,
            )

        def profile_bound(arguments: BoundDatasetReferenceInput) -> ToolObservation:
            dataset = _load_bound_dataset(datasets, arguments.dataset)
            result = profile_dataset(dataset).model_dump(mode="json")
            return ToolObservation(
                success=True,
                summary=f"Profiled {result['inspection']['row_count']} rows in {arguments.dataset}.",
                result=result,
            )

        def transform_bound(arguments: BoundDatasetTransformInput) -> ToolObservation:
            dataset = _load_bound_dataset(datasets, arguments.dataset)
            frame = apply_transformations(dataset.frame, arguments.operations)
            return ToolObservation(
                success=True,
                summary=f"Deterministic transformation produced {len(frame)} rows and {len(frame.columns)} columns.",
                result=_bounded_dataframe_result(frame),
            )

        def analytics_bound(arguments: BoundAnalyticsInput) -> ToolObservation:
            if arguments.dataset not in inspected_datasets:
                raise ValueError("Inspect the bound dataset before running analytics.")
            dataset = _load_bound_dataset(datasets, arguments.dataset)
            executed = execute_dataset_analytics(dataset, arguments.plan)
            return _analytics_observation(executed)

        def join_bound(arguments: BoundDatasetJoinInput) -> ToolObservation:
            frame, diagnostics = _join_bound_datasets(datasets, arguments)
            return ToolObservation(
                success=True,
                summary=(
                    f"Deterministic {diagnostics.join_type} join produced {len(frame)} rows; "
                    f"{diagnostics.left_unmatched_rows} left and {diagnostics.right_unmatched_rows} right rows were unmatched."
                ),
                result={
                    "result": _bounded_dataframe_result(frame),
                    "diagnostics": diagnostics.model_dump(mode="json"),
                },
            )

        def export_bound(arguments: BoundDatasetExportInput) -> ToolObservation:
            dataset = _load_bound_dataset(datasets, arguments.dataset)
            frame = apply_transformations(dataset.frame, arguments.operations)
            artifact = generate_artifact(frame, dataset.filename, arguments.format)
            artifact_repository.save(artifact)
            return _artifact_observation(artifact, f"Exported {len(frame)} deterministic rows to {arguments.format.upper()}.")

        def join_export_bound(arguments: BoundDatasetJoinExportInput) -> ToolObservation:
            frame, diagnostics = _join_bound_datasets(datasets, arguments)
            artifact = generate_artifact(frame, "joined_dataset", arguments.format)
            artifact_repository.save(artifact)
            observation = _artifact_observation(
                artifact,
                f"Exported {len(frame)} deterministically joined rows to {arguments.format.upper()}.",
            )
            result = observation.result or {}
            result["join_diagnostics"] = diagnostics.model_dump(mode="json")
            return observation.model_copy(update={"result": result})

        def template_payload(name: str) -> FilePayload:
            resource = datasets.get(name)
            if resource is None:
                raise ValueError(f"Dataset '{name}' is not bound to this task.")
            return FilePayload(filename=resource.filename, content_base64=resource.content_base64, sheet=resource.sheet)

        def source_payloads(items: list[BoundTemplateSource]) -> list[SourcePayload]:
            if len({item.dataset for item in items}) != len(items):
                raise ValueError("Each transform source must reference a distinct bound dataset.")
            return [SourcePayload(**template_payload(item.dataset).model_dump(), role=item.role) for item in items]

        def propose_template(arguments: BoundTemplateProposalInput) -> ToolObservation:
            names = {arguments.target_dataset, *(item.dataset for item in arguments.sources)}
            if not names.issubset(inspected_datasets):
                raise ValueError("Inspect the target template and every source dataset before proposing mappings.")
            proposal = propose_transform(
                TransformProposalRequest(
                    target=template_payload(arguments.target_dataset),
                    sources=source_payloads(arguments.sources),
                    required_fields=arguments.required_fields,
                    explicit_mappings=arguments.explicit_mappings,
                    documented_aliases=arguments.documented_aliases,
                    header_row=arguments.header_row,
                )
            )
            return ToolObservation(
                success=True,
                summary=(
                    "Template mapping is ready for deterministic execution."
                    if proposal.status == "ready"
                    else f"Template mapping requires clarification for {len(proposal.clarifications)} target fields."
                ),
                result=proposal.model_dump(mode="json"),
                warnings=[item.reason for item in proposal.clarifications],
            )

        def execute_template(arguments: BoundTemplateExecuteInput) -> ToolObservation:
            names = {arguments.target_dataset, *(item.dataset for item in arguments.sources)}
            if not names.issubset(inspected_datasets):
                raise ValueError("Inspect the target template and every source dataset before execution.")
            has_policy_rule = any(rule.operation == "policy_multiply" for rule in arguments.plan.derivations)
            if has_policy_rule:
                if not retrieved_evidence or any(
                    retrieved_evidence.get(str(item.source.chunk_id)) != item for item in arguments.policy_evidence
                ):
                    raise ValueError("Policy evidence must exactly match evidence retrieved in this task.")
                evidence = list(retrieved_evidence.values())
            else:
                evidence = []
            request = TransformExecutionRequest(
                target=template_payload(arguments.target_dataset),
                sources=source_payloads(arguments.sources),
                plan=arguments.plan,
                policy_evidence=evidence,
            )
            executed = execute_transform(request)
            artifact_repository.save(executed.artifact)
            workflow = None
            if workflow_service is not None:
                confirmed_plan = arguments.plan.model_copy(
                    update={
                        "mappings": [
                            item.model_copy(
                                update={
                                    "status": "confirmed",
                                    "evidence": f"{item.evidence} Accepted by successful validated execution.",
                                }
                            )
                            if item.status == "proposed_high_confidence"
                            else item
                            for item in arguments.plan.mappings
                        ]
                    }
                )
                saved_request = request.model_copy(update={"plan": confirmed_plan})
                workflow = workflow_service.create(
                    WorkflowCreate(
                        name=f"Transform to {arguments.plan.target_filename}",
                        steps=[WorkflowStep(tool="template.transform", arguments=saved_request.model_dump(mode="json"))],
                    )
                )
            result = {
                "status": executed.validation.status,
                "validation": executed.validation.model_dump(mode="json"),
                "provenance": [item.model_dump(mode="json") for item in executed.provenance],
                "artifact": {
                    "artifact_id": str(executed.artifact.artifact_id),
                    "filename": executed.artifact.filename,
                    "media_type": executed.artifact.media_type,
                    "row_count": executed.artifact.row_count,
                    "column_count": executed.artifact.column_count,
                    "download_url": f"/artifacts/{executed.artifact.artifact_id}",
                },
            }
            if workflow is not None:
                result["saved_workflow"] = {
                    "workflow_id": str(workflow.workflow_id),
                    "name": workflow.name,
                    "version": workflow.version,
                    "rerun_url": f"/workflows/{workflow.workflow_id}/runs",
                }
            return ToolObservation(
                success=True,
                summary=f"Wrote and verified {executed.artifact.row_count} rows in the supplied template.",
                result=result,
                artifact_ids=[str(executed.artifact.artifact_id)],
                source_ids=[item for field in executed.provenance for item in field.policy_evidence_ids],
                warnings=executed.validation.warnings,
            )

        tools.extend(
            [
                TypedTool(
                    "dataset.inspect",
                    "Inspect one bound CSV/XLSX dataset before choosing columns or operations. Requires a filename returned by resource.list.",
                    BoundDatasetReferenceInput,
                    inspect_bound,
                ),
                TypedTool(
                    "dataset.profile",
                    "Compute deterministic numeric and categorical profiles for one bound dataset.",
                    BoundDatasetReferenceInput,
                    profile_bound,
                ),
                TypedTool(
                    "dataset.transform",
                    "Apply validated deterministic filters, sorting, selection, renaming, deduplication, missing-value handling, arithmetic derivation, and group aggregation. Use group operations for numeric summaries; do not calculate in the model.",
                    BoundDatasetTransformInput,
                    transform_bound,
                ),
                TypedTool(
                    "analytics.execute",
                    "Execute a typed deterministic analytical plan over one inspected bound dataset. The model cannot invent numbers or run Python.",
                    BoundAnalyticsInput,
                    analytics_bound,
                ),
                TypedTool(
                    "dataset.join",
                    "Deterministically transform and join two bound datasets, return bounded result rows, and report unmatched rows and row-multiplication diagnostics.",
                    BoundDatasetJoinInput,
                    join_bound,
                ),
                TypedTool(
                    "dataset.export",
                    "Apply deterministic operations to a bound dataset and create a complete downloadable CSV or XLSX artifact.",
                    BoundDatasetExportInput,
                    export_bound,
                ),
                TypedTool(
                    "dataset.join_export",
                    "Deterministically transform and join two bound datasets and create a complete downloadable CSV or XLSX artifact with join diagnostics.",
                    BoundDatasetJoinExportInput,
                    join_export_bound,
                ),
                TypedTool(
                    "template.propose",
                    "After inspecting all selected files, deterministically inspect the target template and propose evidence-ranked field mappings. Return clarification requirements instead of guessing.",
                    BoundTemplateProposalInput,
                    propose_template,
                ),
                TypedTool(
                    "template.execute",
                    "Execute a ready transform-to-template plan over bound files, fail closed on ambiguity or unsafe joins, validate the exact artifact, and save a reusable drift-checked workflow.",
                    BoundTemplateExecuteInput,
                    execute_template,
                ),
            ]
        )

    if document_ids:
        if service is None:
            raise ValueError("A retrieval service is required when documents are bound to a task.")

        def search_bound(arguments: GeneralDocumentSearchInput) -> ToolObservation:
            selected_ids = [arguments.document_id] if arguments.document_id is not None else document_ids
            if any(document_id not in document_ids for document_id in selected_ids):
                raise ValueError("The requested document is not bound to this task.")
            hits = []
            for document_id in selected_ids:
                response = service.search(arguments.query, arguments.top_k, document_id)
                hits.extend(response.hits)
            hits.sort(key=lambda hit: (-hit.score, str(hit.source.chunk_id)))
            ranked = [hit.model_copy(update={"rank": index}) for index, hit in enumerate(hits[:arguments.top_k], 1)]
            for hit in ranked:
                retrieved_evidence[str(hit.source.chunk_id)] = PolicyEvidence(text=hit.text, source=hit.source)
            return ToolObservation(
                success=True,
                summary=f"Retrieved {len(ranked)} grounded evidence chunks from bound documents.",
                result={"query": arguments.query, "hits": [hit.model_dump(mode="json") for hit in ranked]},
                source_ids=[str(hit.source.chunk_id) for hit in ranked],
            )

        tools.append(
            TypedTool(
                "document.search",
                "Search only the documents bound to this task and return text plus document/page/chunk provenance. Omit document_id to rank evidence across all bound documents.",
                GeneralDocumentSearchInput,
                search_bound,
            )
        )

        if len(datasets) >= 3:
            def general_sales_report(arguments: GeneralSalesReportInput) -> ToolObservation:
                names = {arguments.transactions_dataset, arguments.customers_dataset, arguments.targets_dataset}
                if len(names) != 3 or not names.issubset(inspected_datasets):
                    raise ValueError("Inspect three distinct bound datasets before preparing the sales report.")
                if not retrieved_evidence or any(
                    retrieved_evidence.get(str(item.source.chunk_id)) != item for item in arguments.policy_evidence
                ):
                    raise ValueError("Commission evidence must exactly match policy text and citations retrieved in this task.")
                # Use all observed evidence, so omitting a conflicting chunk cannot alter the rule.
                authoritative_evidence = list(retrieved_evidence.values())
                selected = {
                    "transactions": datasets.get(arguments.transactions_dataset),
                    "customers": datasets.get(arguments.customers_dataset),
                    "targets": datasets.get(arguments.targets_dataset),
                }
                missing = [name for name, resource in selected.items() if resource is None]
                if missing:
                    raise ValueError(f"Sales report resource role(s) are not bound: {', '.join(missing)}.")
                transaction_resource = selected["transactions"]
                customer_resource = selected["customers"]
                target_resource = selected["targets"]
                assert transaction_resource is not None and customer_resource is not None and target_resource is not None
                generated = build_august_sales_report(
                    _load_bound_dataset(datasets, arguments.transactions_dataset).frame,
                    _load_bound_dataset(datasets, arguments.customers_dataset).frame,
                    _load_bound_dataset(datasets, arguments.targets_dataset).frame,
                    authoritative_evidence,
                    source_names={
                        "transactions": arguments.transactions_dataset,
                        "customers": arguments.customers_dataset,
                        "targets": arguments.targets_dataset,
                    },
                )
                workflow = _save_sales_workflow(
                    workflow_service,
                    transaction_resource,
                    customer_resource,
                    target_resource,
                    authoritative_evidence,
                )
                return _sales_observation(generated, artifact_repository, workflow)

            tools.append(
                TypedTool(
                    "sales.north_star_report",
                    "Use only after inspecting the three selected datasets and retrieving policy evidence. Deterministically clean completed August transactions, diagnose customer/target joins, analyze target performance and underperformance drivers, calculate policy-grounded commissions, generate professional charts and a management workbook, and save a schema-checked recipe.",
                    GeneralSalesReportInput,
                    general_sales_report,
                )
            )

    if resources.postgres_sources:
        postgres_by_name = {item.name: item for item in resources.postgres_sources}

        def _bound_postgres(name: str) -> PostgresSourceConfig:
            source = postgres_by_name.get(name)
            if source is None:
                raise ValueError("PostgreSQL source is not bound to this task.")
            return PostgresSourceConfig(
                host=source.host,
                port=source.port,
                database=source.database,
                user=source.user,
                password_secret_ref=source.password_secret_ref,
                sslmode=source.sslmode if source.sslmode in {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"} else "prefer",
            )

        def postgres_catalog_bound(arguments: BoundNamedSourceInput) -> ToolObservation:
            catalog = list_catalog(_bound_postgres(arguments.source))
            return ToolObservation(
                success=True,
                summary=f"Listed {len(catalog.tables)} tables from bound PostgreSQL source {arguments.source}.",
                result=catalog.model_dump(mode="json"),
            )

        def postgres_import_bound(arguments: BoundPostgresImportInput) -> ToolObservation:
            from app.models.sources import PostgresTableRef

            table = None
            if arguments.schema_name and arguments.table:
                table = PostgresTableRef(schema=arguments.schema_name, table=arguments.table)
            imported = import_postgres(
                PostgresImportRequest(source=_bound_postgres(arguments.source), table=table, select_sql=arguments.select_sql)
            )
            return _imported_observation(imported, f"Imported a read-only result from bound PostgreSQL source {arguments.source}.")

        def analytics_sql_bound(arguments: BoundAnalyticsSqlInput) -> ToolObservation:
            executed = execute_sql_analytics(
                AnalyticsSqlRequest(source=_bound_postgres(arguments.source), select_sql=arguments.select_sql, max_rows=arguments.max_rows)
            )
            return _analytics_observation(executed)

        tools.extend(
            [
                TypedTool(
                    "source.postgres.catalog",
                    "List non-system schemas and tables from a PostgreSQL source bound to this task. The model cannot supply credentials.",
                    BoundNamedSourceInput,
                    postgres_catalog_bound,
                ),
                TypedTool(
                    "source.postgres.import",
                    "Import a bound PostgreSQL table or a single validated SELECT into a workspace dataset. Credentials stay server-side.",
                    BoundPostgresImportInput,
                    postgres_import_bound,
                ),
                TypedTool(
                    "analytics.sql",
                    "Run one validated read-only SELECT against a PostgreSQL source bound to this task. The model cannot supply credentials or write SQL.",
                    BoundAnalyticsSqlInput,
                    analytics_sql_bound,
                ),
            ]
        )

    if resources.rest_sources:
        rest_by_name = {item.name: item for item in resources.rest_sources}

        def rest_import_bound(arguments: BoundNamedSourceInput) -> ToolObservation:
            source = rest_by_name.get(arguments.source)
            if source is None:
                raise ValueError("REST source is not bound to this task.")
            imported = import_rest(
                RestSourceConfig(
                    url=source.url,
                    header_secret_refs=source.header_secret_refs,
                    query=source.query,
                    records_key=source.records_key,
                ),
                allow_private=allow_private_rest,
            )
            return _imported_observation(imported, f"Imported JSON from bound REST source {arguments.source}.")

        tools.append(
            TypedTool(
                "source.rest.import",
                "GET JSON from a REST source bound to this task. The model cannot invent URLs or supply raw tokens.",
                BoundNamedSourceInput,
                rest_import_bound,
            )
        )

    if allowed_workflows and workflow_service is not None:
        def require_bound_run(run_id: UUID):
            from app.services.workflows import WorkflowRunNotFoundError

            try:
                run = workflow_service.get_run(run_id)
            except WorkflowRunNotFoundError as exc:
                raise ValueError("The requested workflow run is not bound to this task.") from exc
            if run.workflow_id not in allowed_workflows:
                raise ValueError("The requested workflow run is not bound to this task.")
            return run

        def run_workflow(arguments: BoundWorkflowRunInput) -> ToolObservation:
            if arguments.workflow_id not in allowed_workflows:
                raise ValueError("The requested workflow is not bound to this task.")
            run = workflow_service.rerun(arguments.workflow_id, arguments.step_overrides)
            return ToolObservation(
                success=run.status == "completed",
                summary=(
                    f"Workflow {run.workflow_id} version {run.version} completed."
                    if run.status == "completed"
                    else f"Workflow failed at step {run.failed_step}: {run.error}"
                ),
                result=_workflow_run_summary(run, include_facts=True),
                error_code=None if run.status == "completed" else "workflow_failed",
                artifact_ids=[
                    artifact_id
                    for observation in run.observations
                    for artifact_id in observation.artifact_ids
                ],
                source_ids=[
                    source_id
                    for observation in run.observations
                    for source_id in observation.source_ids
                ],
            )

        tools.append(
            TypedTool(
                "workflow.run",
                "Rerun an authorized saved deterministic workflow with typed per-step overrides and schema-drift checks.",
                BoundWorkflowRunInput,
                run_workflow,
            )
        )

        def list_workflow_runs(arguments: BoundWorkflowHistoryInput) -> ToolObservation:
            if arguments.workflow_id not in allowed_workflows:
                raise ValueError("The requested workflow is not bound to this task.")
            runs = workflow_service.list_runs(arguments.workflow_id, arguments.limit, 0)
            return ToolObservation(
                success=True,
                summary=f"Listed {len(runs)} immutable runs for the bound workflow.",
                result={"runs": [_workflow_run_summary(run, include_facts=False) for run in runs]},
            )

        def get_workflow_run(arguments: BoundWorkflowRunDetailInput) -> ToolObservation:
            run = require_bound_run(arguments.run_id)
            return ToolObservation(
                success=True,
                summary=f"Loaded workflow run {run.run_id}.",
                result=_workflow_run_summary(run, include_facts=True),
            )

        def compare_workflow_runs(arguments: BoundWorkflowCompareInput) -> ToolObservation:
            require_bound_run(arguments.previous_run_id)
            require_bound_run(arguments.current_run_id)
            comparison = workflow_service.compare_runs(
                arguments.previous_run_id, arguments.current_run_id
            )
            return ToolObservation(
                success=True,
                summary="Compared two completed workflow runs using saved deterministic facts.",
                result=comparison.model_dump(mode="json"),
            )

        tools.extend(
            [
                TypedTool(
                    "workflow.list_runs",
                    "List immutable run history only for a workflow bound to this task.",
                    BoundWorkflowHistoryInput,
                    list_workflow_runs,
                ),
                TypedTool(
                    "workflow.get_run",
                    "Inspect safe metadata and deterministic facts for a run of a bound workflow.",
                    BoundWorkflowRunDetailInput,
                    get_workflow_run,
                ),
                TypedTool(
                    "workflow.compare_runs",
                    "Deterministically compare two completed runs belonging to workflows bound to this task.",
                    BoundWorkflowCompareInput,
                    compare_workflow_runs,
                ),
            ]
        )

    return tools


def _load_bound_dataset(resources: dict[str, AgentDatasetResource], filename: str):
    resource = resources.get(filename)
    if resource is None:
        raise ValueError(f"Dataset '{filename}' is not bound to this task.")
    return load_dataset(resource.filename, resource.content(), resource.sheet)


def _workflow_run_summary(run, *, include_facts: bool) -> dict[str, Any]:
    result = {
        "run_id": str(run.run_id),
        "workflow_id": str(run.workflow_id),
        "version": run.version,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat(),
        "failed_step": run.failed_step,
        "error": run.error,
        "lifecycle": [item.model_dump(mode="json") for item in run.lifecycle],
        "input_snapshots": [item.model_dump(mode="json") for item in run.input_snapshots],
        "verification": run.verification.model_dump(mode="json") if run.verification else None,
        "warnings": run.warnings,
        "artifacts": [item.model_dump(mode="json") for item in run.artifacts],
        "drift_findings": [item.model_dump(mode="json") for item in run.drift_findings],
        "step_summaries": [item.model_dump(mode="json") for item in run.step_summaries],
        "diagnostics": [item.model_dump(mode="json") for item in run.diagnostics],
    }
    if include_facts:
        result["facts"] = [item.model_dump(mode="json") for item in run.facts]
    return result


def _join_bound_datasets(resources: dict[str, AgentDatasetResource], arguments: BoundDatasetJoinInput):
    left = _load_bound_dataset(resources, arguments.left_dataset)
    right = _load_bound_dataset(resources, arguments.right_dataset)
    left_frame = apply_transformations(left.frame, arguments.left_operations)
    right_frame = apply_transformations(right.frame, arguments.right_operations)
    joined = join_datasets(left_frame, right_frame, arguments.join)
    return apply_transformations(joined.frame, arguments.operations), joined.diagnostics


def _bounded_dataframe_result(frame, max_rows: int = 200) -> dict[str, Any]:
    result = dataframe_result(frame.head(max_rows)).model_dump(mode="json")
    result["row_count"] = len(frame)
    result["rows_truncated"] = len(frame) > max_rows
    return result


def _artifact_observation(artifact, summary: str) -> ToolObservation:
    reference = {
        "artifact_id": str(artifact.artifact_id),
        "filename": artifact.filename,
        "media_type": artifact.media_type,
        "row_count": artifact.row_count,
        "column_count": artifact.column_count,
        "download_url": f"/artifacts/{artifact.artifact_id}",
    }
    return ToolObservation(
        success=True,
        summary=summary,
        result={"artifact": reference},
        artifact_ids=[str(artifact.artifact_id)],
    )


def retrieval_tool(service: RetrievalService) -> TypedTool[RetrievalRequest]:
    def search(arguments: RetrievalRequest) -> ToolObservation:
        response = service.search(arguments.query, arguments.top_k, arguments.document_id)
        result = response.model_dump(mode="json")
        sources = [str(hit.source.chunk_id) for hit in response.hits]
        return ToolObservation(
            success=True,
            summary=f"Retrieved {len(response.hits)} evidence chunks.",
            result=result,
            source_ids=sources,
        )

    return TypedTool("document.search", "Search ingested PDF evidence with page and chunk provenance.", RetrievalRequest, search)


def grade_tool() -> TypedTool[RequiredFinalInput]:
    def calculate(arguments: RequiredFinalInput) -> ToolObservation:
        dataset = load_dataset(arguments.filename, arguments.content(), arguments.sheet)
        calculated = calculate_required_final(dataset.frame, arguments.evidence, arguments.target_letter.upper())
        result = calculated.model_dump(mode="json")
        return ToolObservation(
            success=True,
            summary=calculated.message,
            result=result,
            source_ids=[str(source.chunk_id) for source in calculated.citations],
        )

    return TypedTool(
        "grades.required_final",
        "Calculate a required final score from category data and cited grading-policy evidence.",
        RequiredFinalInput,
        calculate,
    )


def grade_task_tools(
    service: RetrievalService,
    dataset_resource: AgentDatasetResource,
    document_id: UUID,
) -> list[TypedTool[Any]]:
    """Build task-scoped tools whose schemas never expose uploaded file bodies to a model."""

    def inspect_bound(_: BoundDatasetInspectInput) -> ToolObservation:
        dataset = load_dataset(dataset_resource.filename, dataset_resource.content(), dataset_resource.sheet)
        result = inspect_dataset(dataset).model_dump(mode="json")
        return ToolObservation(
            success=True,
            summary=f"Inspected {result['row_count']} rows and {result['column_count']} columns in {result['filename']}.",
            result=result,
        )

    def search_bound(arguments: BoundDocumentSearchInput) -> ToolObservation:
        response = service.search(arguments.query, arguments.top_k, document_id)
        result = response.model_dump(mode="json")
        return ToolObservation(
            success=True,
            summary=f"Retrieved {len(response.hits)} grading-policy evidence chunks.",
            result=result,
            source_ids=[str(hit.source.chunk_id) for hit in response.hits],
        )

    def calculate_bound(arguments: BoundRequiredFinalInput) -> ToolObservation:
        dataset = load_dataset(dataset_resource.filename, dataset_resource.content(), dataset_resource.sheet)
        calculated = calculate_required_final(dataset.frame, arguments.evidence, arguments.target_letter.upper())
        return ToolObservation(
            success=True,
            summary=calculated.message,
            result=calculated.model_dump(mode="json"),
            source_ids=[str(source.chunk_id) for source in calculated.citations],
        )

    return [
        TypedTool("dataset.inspect", "Inspect the task's uploaded grade dataset.", BoundDatasetInspectInput, inspect_bound),
        TypedTool(
            "document.search",
            "Search the task's ingested PDF for grading policy evidence with page and chunk provenance.",
            BoundDocumentSearchInput,
            search_bound,
        ),
        TypedTool(
            "grades.required_final",
            "Calculate the required final score deterministically from the bound dataset and cited policy evidence.",
            BoundRequiredFinalInput,
            calculate_bound,
        ),
    ]


def sales_report_tool(artifact_repository: ArtifactRepository | None = None) -> TypedTool[SalesReportInput]:
    def report(arguments: SalesReportInput) -> ToolObservation:
        transactions = load_dataset(arguments.transactions.filename, arguments.transactions.content(), arguments.transactions.sheet)
        customers = load_dataset(arguments.customers.filename, arguments.customers.content(), arguments.customers.sheet)
        targets = load_dataset(arguments.targets.filename, arguments.targets.content(), arguments.targets.sheet)
        generated = build_august_sales_report(
            transactions.frame,
            customers.frame,
            targets.frame,
            arguments.policy_evidence,
            source_names={
                "transactions": arguments.transactions.filename,
                "customers": arguments.customers.filename,
                "targets": arguments.targets.filename,
            },
        )
        return _sales_observation(generated, artifact_repository)

    return TypedTool(
        "sales.august_report",
        "Clean August transactions, compare regional targets, calculate cited commissions, and create a management workbook.",
        SalesReportInput,
        report,
    )


def sales_task_tools(
    service: RetrievalService,
    transactions_resource: AgentDatasetResource,
    customers_resource: AgentDatasetResource,
    targets_resource: AgentDatasetResource,
    document_id: UUID,
    artifact_repository: ArtifactRepository,
    workflow_service: WorkflowService | None = None,
) -> list[TypedTool[Any]]:
    """Build task-scoped sales tools without exposing uploaded file bodies to a model."""

    def search_bound(arguments: BoundDocumentSearchInput) -> ToolObservation:
        response = service.search(arguments.query, arguments.top_k, document_id)
        return ToolObservation(
            success=True,
            summary=f"Retrieved {len(response.hits)} commission-policy evidence chunks.",
            result=response.model_dump(mode="json"),
            source_ids=[str(hit.source.chunk_id) for hit in response.hits],
        )

    def report_bound(arguments: BoundSalesReportInput) -> ToolObservation:
        transactions = load_dataset(transactions_resource.filename, transactions_resource.content(), transactions_resource.sheet)
        customers = load_dataset(customers_resource.filename, customers_resource.content(), customers_resource.sheet)
        targets = load_dataset(targets_resource.filename, targets_resource.content(), targets_resource.sheet)
        generated = build_august_sales_report(
            transactions.frame,
            customers.frame,
            targets.frame,
            arguments.policy_evidence,
            source_names={
                "transactions": transactions_resource.filename,
                "customers": customers_resource.filename,
                "targets": targets_resource.filename,
            },
        )
        workflow = _save_sales_workflow(
            workflow_service,
            transactions_resource,
            customers_resource,
            targets_resource,
            arguments.policy_evidence,
        )
        return _sales_observation(generated, artifact_repository, workflow)

    return [
        TypedTool(
            "document.search",
            "Search the bound commission-policy PDF with page and chunk provenance.",
            BoundDocumentSearchInput,
            search_bound,
        ),
        TypedTool(
            "sales.august_report",
            "Deterministically clean and join the bound sales files, calculate targets and commissions, and create a workbook.",
            BoundSalesReportInput,
            report_bound,
        ),
    ]


def _sales_observation(generated, artifact_repository: ArtifactRepository | None, workflow=None) -> ToolObservation:
    if artifact_repository is not None:
        artifact_repository.save(generated.artifact)
    result = {
            "commission_rate": generated.commission_rate,
            "regional_performance": dataframe_result(generated.regional_performance).model_dump(mode="json"),
            "commissions": dataframe_result(generated.commissions).model_dump(mode="json"),
            "join_diagnostics": generated.join_diagnostics.model_dump(mode="json"),
            "target_join_diagnostics": generated.target_join_diagnostics,
            "data_quality": generated.data_quality,
            "warnings": generated.warnings,
            "verification_facts": generated.verification_facts,
            "trace_metadata": {
                "input_rows": generated.data_quality.get("original_transaction_rows", 0),
                "cleaned_rows": generated.data_quality.get("cleaned_rows", 0),
                "customer_unmatched_rows": generated.join_diagnostics.left_unmatched_rows,
                "regions_missing_targets": generated.target_join_diagnostics["regions_missing_targets"],
            },
            "artifact": {
                "artifact_id": str(generated.artifact.artifact_id),
                "filename": generated.artifact.filename,
                "media_type": generated.artifact.media_type,
                "row_count": generated.artifact.row_count,
                "column_count": generated.artifact.column_count,
                "download_url": f"/artifacts/{generated.artifact.artifact_id}",
            },
        }
    if workflow is not None:
        result["saved_workflow"] = {
            "workflow_id": str(workflow.workflow_id),
            "name": workflow.name,
            "version": workflow.version,
            "rerun_url": f"/workflows/{workflow.workflow_id}/runs",
        }
    source_ids = [str(source.chunk_id) for source in generated.citations]
    stages = [
        ExecutionStage(
            name="Clean",
            status="warning" if any(value for key, value in generated.data_quality.items() if key.endswith(("excluded", "removed", "zero")) and isinstance(value, int)) else "completed",
            explanation=(
                f"Created a new cleaned table with {len(generated.cleaned_transactions)} rows from "
                f"{generated.data_quality.get('original_transaction_rows', 0)} source rows; originals were not modified."
            ),
            tool_name="sales.north_star_report",
            row_counts={
                "source": int(generated.data_quality.get("original_transaction_rows", 0)),
                "cleaned": len(generated.cleaned_transactions),
            },
            diagnostics=generated.data_quality,
        ),
        ExecutionStage(
            name="Join",
            status="warning" if generated.warnings else "completed",
            explanation="Joined transactions to customer regions and regional targets with explicit loss and multiplication diagnostics.",
            tool_name="sales.north_star_report",
            row_counts={
                "customer_join_output": generated.join_diagnostics.output_rows,
                "regional_rows": len(generated.regional_performance),
            },
            diagnostics={
                "customers": generated.join_diagnostics.model_dump(mode="json"),
                "targets": generated.target_join_diagnostics,
            },
        ),
        ExecutionStage(
            name="Analyze",
            status="completed",
            explanation=f"Calculated deterministic regional actuals, targets, variances, and underperformance for {len(generated.regional_performance)} regions.",
            tool_name="sales.north_star_report",
            row_counts={"regions": len(generated.regional_performance)},
        ),
        ExecutionStage(
            name="Calculate commissions",
            status="completed",
            explanation=f"Applied the cited {generated.commission_rate * 100:g}% policy rate to completed August net sales for {len(generated.commissions)} salespeople.",
            tool_name="sales.north_star_report",
            row_counts={"salespeople": len(generated.commissions)},
            evidence_ids=source_ids,
        ),
        ExecutionStage(
            name="Generate charts and workbook",
            status="completed",
            explanation="Generated an auditable six-sheet management workbook with three decision-useful charts.",
            tool_name="sales.north_star_report",
            artifact_ids=[str(generated.artifact.artifact_id)],
        ),
    ]
    if workflow is not None:
        stages.append(
            ExecutionStage(
                name="Save workflow",
                status="completed",
                explanation=f"Saved schema-checked deterministic recipe '{workflow.name}' version {workflow.version}.",
                tool_name="sales.north_star_report",
            )
        )
    return ToolObservation(
        success=True,
        summary=f"Prepared August report for {len(generated.regional_performance)} regions and {len(generated.commissions)} salespeople.",
        result=result,
        artifact_ids=[str(generated.artifact.artifact_id)],
        source_ids=source_ids,
        stages=stages,
        warnings=generated.warnings,
    )


def _save_sales_workflow(
    workflow_service: WorkflowService | None,
    transactions_resource,
    customers_resource,
    targets_resource,
    policy_evidence: list[PolicyEvidence],
):
    if workflow_service is None:
        return None
    resources = {
        "transactions": transactions_resource.model_dump(mode="json"),
        "customers": customers_resource.model_dump(mode="json"),
        "targets": targets_resource.model_dump(mode="json"),
    }
    expected_schemas = {}
    for name, resource in resources.items():
        validated = DatasetInput.model_validate(resource)
        expected_schemas[name] = inspect_dataset(
            load_dataset(validated.filename, validated.content(), validated.sheet)
        ).columns
    return workflow_service.create(
        WorkflowCreate(
            name="August sales management report",
            steps=[
                WorkflowStep(
                    tool="sales.august_report",
                    arguments={**resources, "policy_evidence": [item.model_dump(mode="json") for item in policy_evidence]},
                    expected_schemas=expected_schemas,
                )
            ],
        )
    )
