"""Strict typed tool registry and adapters for existing deterministic services."""

import base64
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.agent.models import ToolObservation
from app.models.retrieval import RetrievalRequest
from app.models.grades import PolicyEvidence, RequiredFinalInput
from app.models.transformations import JoinSpec, TransformRequest
from app.services.datasets import inspect_dataset, load_dataset, profile_dataset
from app.services.retrieval import RetrievalService
from app.services.grades import calculate_required_final
from app.services.sales_report import build_august_sales_report
from app.services.transformations import apply_transformations, dataframe_result, join_datasets

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
    content_base64: str = Field(min_length=1)
    sheet: str | None = None

    def content(self) -> bytes:
        try:
            return base64.b64decode(self.content_base64, validate=True)
        except ValueError as exc:
            raise ValueError("content_base64 is not valid base64.") from exc


class TransformInput(DatasetInput):
    request: TransformRequest


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

    return [
        TypedTool("dataset.inspect", "Inspect a CSV/XLSX schema and quality counts.", DatasetInput, inspect),
        TypedTool("dataset.profile", "Profile deterministic numeric and categorical statistics.", DatasetInput, profile),
        TypedTool("dataset.transform", "Apply the closed set of validated dataframe operations.", TransformInput, transform),
    ]


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


def sales_report_tool() -> TypedTool[SalesReportInput]:
    def report(arguments: SalesReportInput) -> ToolObservation:
        transactions = load_dataset(arguments.transactions.filename, arguments.transactions.content(), arguments.transactions.sheet)
        customers = load_dataset(arguments.customers.filename, arguments.customers.content(), arguments.customers.sheet)
        targets = load_dataset(arguments.targets.filename, arguments.targets.content(), arguments.targets.sheet)
        generated = build_august_sales_report(transactions.frame, customers.frame, targets.frame, arguments.policy_evidence)
        result = {
            "commission_rate": generated.commission_rate,
            "regional_performance": dataframe_result(generated.regional_performance).model_dump(mode="json"),
            "commissions": dataframe_result(generated.commissions).model_dump(mode="json"),
            "join_diagnostics": generated.join_diagnostics.model_dump(mode="json"),
            "artifact": {
                "artifact_id": str(generated.artifact.artifact_id),
                "filename": generated.artifact.filename,
                "media_type": generated.artifact.media_type,
                "row_count": generated.artifact.row_count,
                "column_count": generated.artifact.column_count,
            },
        }
        return ToolObservation(
            success=True,
            summary=f"Prepared August report for {len(generated.regional_performance)} regions and {len(generated.commissions)} salespeople.",
            result=result,
            artifact_ids=[str(generated.artifact.artifact_id)],
            source_ids=[str(source.chunk_id) for source in generated.citations],
        )

    return TypedTool(
        "sales.august_report",
        "Clean August transactions, compare regional targets, calculate cited commissions, and create a management workbook.",
        SalesReportInput,
        report,
    )
