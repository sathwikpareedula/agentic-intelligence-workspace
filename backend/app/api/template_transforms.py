"""HTTP flow for deterministic transform-to-template planning and execution."""

from __future__ import annotations

import base64
from dataclasses import replace
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.dependencies import build_retrieval_service, get_artifact_repository, get_workflow_service
from app.embeddings.base import EmbeddingError
from app.models.grades import PolicyEvidence
from app.models.template_transforms import (
    FilePayload,
    OutputValidation,
    SavedWorkflowReference,
    SourcePayload,
    TemplateArtifactReference,
    TransformExecutionRequest,
    TransformExecutionResponse,
    TransformProposal,
    TransformProposalRequest,
    TransformTemplatePlan,
)
from app.models.workflows import WorkflowCreate, WorkflowStep
from app.repositories.documents import RepositoryError
from app.services.datasets import DatasetError, DatasetTooLargeError, MAX_UPLOAD_BYTES
from app.services.pdf_documents import PdfDocumentError, PdfTooLargeError
from app.services.template_transforms import (
    ClarificationRequiredError,
    TemplateInspectionError,
    TransformValidationError,
    execute_transform,
    propose_transform,
)

router = APIRouter(prefix="/template-transforms", tags=["template-transforms"])


async def _read_upload(file: UploadFile, limit: int) -> tuple[str, bytes]:
    content = await file.read(limit + 1)
    filename = Path(file.filename or "").name
    await file.close()
    if len(content) > limit:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=f"File exceeds the {limit // (1024 * 1024)} MiB limit.")
    return filename, content


def _json_object(raw: str | None, label: str) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, f"{label} must be valid JSON.") from exc
    if not isinstance(value, dict):
        raise HTTPException(422, f"{label} must be a JSON object.")
    return value


def _json_list(raw: str | None, label: str) -> list | None:
    if raw is None or raw == "":
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, f"{label} must be valid JSON.") from exc
    if not isinstance(value, list):
        raise HTTPException(422, f"{label} must be a JSON array.")
    return value


def _source_payloads(
    uploads: list[tuple[str, bytes]], roles: list[str] | None, sheets: list[str | None] | None = None
) -> list[SourcePayload]:
    if roles is None:
        roles = [f"source{index}" for index in range(1, len(uploads) + 1)]
    if len(roles) != len(uploads):
        raise HTTPException(422, "source_roles must contain one role for every source file.")
    if sheets is None:
        sheets = [None] * len(uploads)
    if len(sheets) != len(uploads):
        raise HTTPException(422, "source_sheets must contain one sheet name or null for every source file.")
    try:
        return [
            SourcePayload(filename=filename, content_base64=base64.b64encode(content).decode("ascii"), role=role, sheet=sheet)
            for (filename, content), role, sheet in zip(uploads, roles, sheets, strict=True)
        ]
    except ValidationError as exc:
        raise HTTPException(422, exc.errors()) from exc


@router.post("/proposals", response_model=TransformProposal)
async def create_proposal(
    target: UploadFile = File(...),
    sources: list[UploadFile] = File(...),
    source_roles: str | None = Form(default=None),
    source_sheets: str | None = Form(default=None),
    required_fields: str | None = Form(default=None),
    explicit_mappings: str | None = Form(default=None),
    documented_aliases: str | None = Form(default=None),
    target_sheet: str | None = Form(default=None),
    header_row: int | None = Form(default=None, ge=1, le=100),
) -> TransformProposal:
    if not 1 <= len(sources) <= 8:
        raise HTTPException(422, "Upload between one and eight source files.")
    target_upload = await _read_upload(target, MAX_UPLOAD_BYTES)
    source_uploads = [await _read_upload(file, MAX_UPLOAD_BYTES) for file in sources]
    try:
        payload = TransformProposalRequest(
            target=FilePayload(
                filename=target_upload[0],
                content_base64=base64.b64encode(target_upload[1]).decode("ascii"),
                sheet=target_sheet,
            ),
            sources=_source_payloads(
                source_uploads,
                _json_list(source_roles, "source_roles"),
                _json_list(source_sheets, "source_sheets"),
            ),
            required_fields=_json_list(required_fields, "required_fields"),
            explicit_mappings=_json_object(explicit_mappings, "explicit_mappings"),
            documented_aliases=_json_object(documented_aliases, "documented_aliases"),
            header_row=header_row,
        )
        return await run_in_threadpool(propose_transform, payload)
    except DatasetTooLargeError as exc:
        raise HTTPException(413, str(exc)) from exc
    except (DatasetError, TemplateInspectionError, ValidationError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/executions", response_model=TransformExecutionResponse)
async def execute_proposal(
    request: Request,
    target: UploadFile = File(...),
    sources: list[UploadFile] = File(...),
    plan: str = Form(...),
    source_roles: str | None = Form(default=None),
    source_sheets: str | None = Form(default=None),
    policy: UploadFile | None = File(default=None),
    settings: Settings = Depends(get_settings),
) -> TransformExecutionResponse:
    target_upload = await _read_upload(target, MAX_UPLOAD_BYTES)
    source_uploads = [await _read_upload(file, MAX_UPLOAD_BYTES) for file in sources]
    try:
        parsed_plan = TransformTemplatePlan.model_validate_json(plan)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors()) from exc
    target_payload = FilePayload(
        filename=target_upload[0],
        content_base64=base64.b64encode(target_upload[1]).decode("ascii"),
        sheet=parsed_plan.target_sheet,
    )
    source_payloads = _source_payloads(
        source_uploads,
        _json_list(source_roles, "source_roles"),
        _json_list(source_sheets, "source_sheets"),
    )
    policy_queries = [item.policy_query for item in parsed_plan.derivations if item.operation == "policy_multiply"]
    try:
        evidence = await _policy_evidence(policy, policy_queries, settings)
        execution_request = TransformExecutionRequest(
            target=target_payload,
            sources=source_payloads,
            plan=parsed_plan,
            policy_evidence=evidence,
        )
        executed = await run_in_threadpool(execute_transform, execution_request)
    except ClarificationRequiredError as exc:
        return TransformExecutionResponse(status="clarification_required", plan=parsed_plan, clarifications=exc.clarifications)
    except TransformValidationError as exc:
        return TransformExecutionResponse(
            status="failed_validation",
            plan=parsed_plan,
            validation=OutputValidation(
                status="failed_validation",
                checks=[],
                errors=[str(exc)],
                warnings=[],
                input_row_count=0,
                output_row_count=0,
                join_diagnostics=[],
            ),
        )
    except PdfTooLargeError as exc:
        raise HTTPException(413, str(exc)) from exc
    except (DatasetError, TemplateInspectionError, PdfDocumentError, ValidationError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except EmbeddingError as exc:
        raise HTTPException(502, str(exc)) from exc
    except RepositoryError as exc:
        raise HTTPException(503, str(exc)) from exc

    confirmed_plan = parsed_plan.model_copy(
        update={
            "mappings": [
                item.model_copy(update={"status": "confirmed", "evidence": f"{item.evidence} Accepted by successful validated execution."})
                if item.status == "proposed_high_confidence" else item
                for item in parsed_plan.mappings
            ]
        }
    )
    saved_request = execution_request.model_copy(update={"plan": confirmed_plan})
    workflow_service = getattr(request.app.state, "workflow_service", None) or get_workflow_service(settings)
    artifact_repository = getattr(request.app.state, "artifact_repository", None) or get_artifact_repository(settings)
    try:
        workflow = workflow_service.create(
            WorkflowCreate(
                name=f"Transform to {parsed_plan.target_filename}",
                steps=[WorkflowStep(tool="template.transform", arguments=saved_request.model_dump(mode="json"))],
            )
        )
        artifact = replace(
            executed.artifact,
            producing_workflow_id=workflow.workflow_id,
            verification_status=executed.validation.status,
        )
        artifact_repository.save(artifact)
    except RepositoryError as exc:
        raise HTTPException(503, str(exc)) from exc

    return TransformExecutionResponse(
        status=executed.validation.status,
        plan=confirmed_plan,
        validation=executed.validation,
        provenance=executed.provenance,
        artifact=TemplateArtifactReference(
            artifact_id=artifact.artifact_id,
            filename=artifact.filename,
            media_type=artifact.media_type,
            row_count=artifact.row_count,
            column_count=artifact.column_count,
            download_url=f"/artifacts/{artifact.artifact_id}",
        ),
        saved_workflow=SavedWorkflowReference(
            workflow_id=workflow.workflow_id,
            name=workflow.name,
            version=workflow.version,
            rerun_url=f"/workflows/{workflow.workflow_id}/runs",
        ),
    )


async def _policy_evidence(policy: UploadFile | None, queries: list[str | None], settings: Settings) -> list[PolicyEvidence]:
    if not queries:
        if policy is not None:
            await policy.close()
        return []
    if policy is None:
        raise TransformValidationError("A policy PDF is required for policy-grounded derivations.")
    filename, content = await _read_upload(policy, settings.pdf_max_upload_bytes)
    service = build_retrieval_service(settings)
    ingested = await run_in_threadpool(service.ingest_pdf, filename, content, settings.chunk_size, settings.chunk_overlap)
    found: dict[str, PolicyEvidence] = {}
    for query in queries:
        response = await run_in_threadpool(service.search, query or "policy rate", 5, ingested.document_id)
        for hit in response.hits:
            found[str(hit.source.chunk_id)] = PolicyEvidence(text=hit.text, source=hit.source)
    return list(found.values())
