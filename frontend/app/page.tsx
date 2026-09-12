"use client";

import { FormEvent, useEffect, useState } from "react";

type Runtime = {
  status: "ready" | "not_ready";
  mode: "production" | "demo";
  storage: "postgresql" | "in_memory";
  embedding_provider: string;
  orchestrator_provider: string;
  orchestrator_status: "demo" | "configured" | "unavailable";
  orchestrator_model: string;
  limitations: string[];
};
type Citation = { document_id: string; filename: string; page_number: number; chunk_id: string };
type Artifact = { artifact_id: string; filename: string; media_type: string; download_url: string; row_count: number; column_count: number };
type TraceStep = { step: number; requested_tool: string; success: boolean; observation: string; duration_ms: number; source_ids: string[]; artifact_ids: string[]; stage?: string; warnings: string[] };
type ExecutionStage = { name: string; status: "completed" | "warning" | "failed"; explanation: string; tool_name?: string; row_counts: Record<string, number>; diagnostics: Record<string, unknown>; evidence_ids: string[]; artifact_ids: string[]; verification_result?: string };
type Execution = {
  task_id: string;
  status: string;
  answer?: string;
  failure_reason?: string;
  trace: TraceStep[];
  citations: Citation[];
  evidence: { text: string; source: Citation }[];
  artifacts: Artifact[];
  stages: ExecutionStage[];
  warnings: string[];
  saved_workflow?: SavedWorkflow;
  verification?: { status: string; findings: { claim: string; status: string; explanation: string }[] };
  provider_usage?: { provider: string; model: string; provider_calls: number; latency_ms: number; input_tokens?: number | null; output_tokens?: number | null; total_tokens?: number | null; approximate_cost_usd?: number | null; cost_basis?: "operator_configured" | null } | null;
};
type DocumentResult = { document_id: string; filename: string; page_count: number; chunk_count: number };
type TemplateMapping = { target_field: string; source_role?: string; source_field?: string; mapping_type: string; confidence: number; evidence: string; status: string };
type TemplatePlan = {
  source_roles: string[];
  target_filename: string;
  target_headers: string[];
  mappings: TemplateMapping[];
  joins: unknown[];
  derivations: { target_field: string; operation: string; inputs: { source_role: string; source_field: string; transformation?: string }[]; policy_query?: string; separator?: string; constant?: number }[];
  [key: string]: unknown;
};
type TemplateProposal = {
  status: "ready" | "clarification_required";
  template: { target_sheet?: string; headers: string[]; sheets: { name: string }[]; fingerprint: string };
  sources: { role: string; inspection: { filename: string; row_count: number; columns: string[] }; candidate_keys: string[][] }[];
  plan: TemplatePlan;
  clarifications: { code: string; target_field: string; candidate_options: string[]; reason: string }[];
};
type TemplateResult = {
  status: "completed" | "completed_with_warnings" | "clarification_required" | "failed_validation";
  validation?: { status: string; checks: { name: string; passed: boolean; detail: string }[]; errors: string[]; warnings: string[]; input_row_count: number; output_row_count: number };
  provenance: { target_field: string; source_fields: string[]; transformation: string; policy_evidence_ids: string[]; validation: string }[];
  clarifications: { target_field: string; reason: string }[];
  artifact?: Artifact;
  saved_workflow?: SavedWorkflow;
};
type AnalyticsResult = {
  status: string;
  explanation: string;
  facts: { key: string; metric: string; value: number | null; label: string; calculation: string; grouping: Record<string, string> }[];
  verification_facts: Record<string, number>;
  columns: string[];
  rows: Record<string, string | number | boolean | null>[];
  row_count: number;
  plan: Record<string, unknown>;
  visualization: { kind: "metric" | "bar" | "line" | "table"; title: string; x_field?: string; y_fields: string[]; rationale: string; max_points: number };
};
type SavedWorkflow = { workflow_id: string; name: string; version: number; rerun_url: string };
type WorkflowRun = {
  run_id: string;
  workflow_id: string;
  version: number;
  definition_fingerprint?: string | null;
  status: "completed" | "failed";
  started_at: string;
  completed_at: string;
  error?: string;
  lifecycle: { state: string; occurred_at: string }[];
  input_snapshots: { input_key: string; identity: string; row_count?: number; fingerprint: string; schema_fingerprint?: string; missing_value_count?: number; duplicate_row_count?: number; missing_by_column: Record<string, number>; categories: Record<string, { unique_count: number; values: string[]; values_complete: boolean }> }[];
  facts: { fact_id: string; label: string; metric: string; value: number; unit?: string; grouping: Record<string, string | number | boolean | null> }[];
  artifacts: { artifact_id: string; filename?: string; download_url?: string; row_count?: number }[];
  warnings: string[];
  drift_findings: { kind: string; status: string; explanation: string }[];
  verification?: { status: string; fact_count: number; warning_count: number };
  step_summaries: { step: number; tool_name: string; status: string; summary: string; warning_count: number; artifact_count: number; source_count: number }[];
  diagnostics: { diagnostic_id: string; kind: string; label: string; value: number; unit: string }[];
};
type RunComparison = {
  previous_run_id: string;
  current_run_id: string;
  metrics: { fact_id: string; label: string; metric: string; unit?: string | null; grouping: Record<string, string | number | boolean | null>; status: string; previous?: { value: number } | null; current?: { value: number } | null; absolute_change?: number | null; percent_change?: number | null; percent_change_reason?: string | null }[];
  row_counts: { input_key: string; identity_previous?: string | null; identity_current?: string | null; previous?: number | null; current?: number | null; absolute_change?: number | null; percent_change?: number | null; percent_change_reason?: string | null }[];
  snapshots: { input_key: string; status: string; explanation: string; added_columns: string[]; removed_columns: string[]; type_changes: Record<string, { previous: string; current: string }> }[];
  warnings: { warning: string; previous_count: number; current_count: number; change: number }[];
  verification_previous?: { status: string };
  verification_current?: { status: string };
  artifact_count_previous: number;
  artifact_count_current: number;
  quality: { quality_id: string; section: "volume" | "quality" | "category" | "join"; label: string; unit: string; previous?: number | null; current?: number | null; absolute_change?: number | null; percent_change?: number | null; percent_change_reason?: string | null; previous_run_id: string; current_run_id: string }[];
  categories: { input_key: string; column: string; previous_unique_count: number; current_unique_count: number; added: string[]; removed: string[]; values_complete: boolean; previous_run_id: string; current_run_id: string }[];
  steps: { step: number; tool_name: string; previous_status?: string | null; current_status?: string | null; warning_change: number; artifact_change: number }[];
  observed_only: true;
};
const SHORTFALL_PLAN = {
  analysis: "target_variance",
  filters: [],
  group_by: ["region"],
  metrics: [],
  value_column: "net_sales",
  second_column: "target",
  contributor_column: "salesperson",
  expected_columns: ["region", "salesperson", "net_sales", "target", "month"],
  rank_method: "dense",
  ascending: false,
  limit: 100,
  nulls: "exclude",
};

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiJson<T>(response: Response): Promise<T> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    const detail = body && typeof body === "object" && "detail" in body ? (body as { detail: unknown }).detail : null;
    const message = typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? detail.map((item) => typeof item === "object" && item && "msg" in item ? String(item.msg) : "Invalid input").join("; ")
        : `Request failed with status ${response.status}`;
    const requestId = response.headers.get("x-request-id");
    throw new Error(requestId ? `${message} (request ${requestId})` : message);
  }
  return body as T;
}

async function fileToBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  const batchSize = 0x8000;
  for (let index = 0; index < bytes.length; index += batchSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + batchSize));
  }
  return btoa(binary);
}

function AnalyticsVisualization({ result }: { result: AnalyticsResult }) {
  const spec = result.visualization;
  const yField = spec.y_fields[0];
  const points = yField ? result.rows.slice(0, spec.max_points).flatMap((row) => {
    const value = row[yField];
    return typeof value === "number" && Number.isFinite(value)
      ? [{ label: String(spec.x_field ? row[spec.x_field] ?? "Unknown" : yField), value }]
      : [];
  }) : [];
  const maximum = Math.max(1, ...points.map((point) => Math.abs(point.value)));
  const minimum = Math.min(...points.map((point) => point.value));
  const peak = Math.max(...points.map((point) => point.value));
  const range = peak - minimum;

  return <section className="panel analyticsVisual">
    <div className="panelTitle"><h2>{spec.title}</h2><span>{spec.kind}</span></div>
    <p className="muted">{spec.rationale}</p>
    {spec.kind === "bar" && points.length > 0 ? <div className="barChart" role="img" aria-label={`${spec.title}; ${yField}`}>
      {points.map((point, index) => <div className="barRow" key={`${point.label}-${index}`}><span>{point.label}</span><i className={point.value < 0 ? "negative" : undefined} style={{ width: `${Math.max(2, Math.abs(point.value) / maximum * 100)}%` }} /><strong>{point.value}</strong></div>)}
    </div> : spec.kind === "line" && points.length > 1 ? <div className="trendChart">
      <svg role="img" aria-label={`${spec.title}; ${yField}`} viewBox="0 0 100 40" preserveAspectRatio="none"><polyline points={points.map((point, index) => `${index * 100 / (points.length - 1)},${range === 0 ? 20 : 36 - (point.value - minimum) / range * 32}`).join(" ")} /></svg>
      <div className="trendLabels">{points.map((point, index) => <span key={`${point.label}-${index}`}>{point.label}: {point.value}</span>)}</div>
    </div> : <div className="metricPreview">{spec.y_fields.map((field) => <span key={field}><strong>{field.replaceAll("_", " ")}</strong><small>{String(result.rows[0]?.[field] ?? "Shown in result table")}</small></span>)}</div>}
  </section>;
}

export default function WorkspacePage() {
  const [demo, setDemo] = useState<"grades" | "sales" | "template" | "sources" | "analytics">("sales");
  const [goal, setGoal] = useState("Prepare the monthly sales report. Clean transactions, compare regional targets, identify the largest shortfalls, calculate policy-based commissions, and export a management workbook while preserving the originals.");
  const [dataset, setDataset] = useState<File | null>(null);
  const [document, setDocument] = useState<File | null>(null);
  const [customers, setCustomers] = useState<File | null>(null);
  const [targets, setTargets] = useState<File | null>(null);
  const [templateTarget, setTemplateTarget] = useState<File | null>(null);
  const [templateProposal, setTemplateProposal] = useState<TemplateProposal | null>(null);
  const [templateResult, setTemplateResult] = useState<TemplateResult | null>(null);
  const [mappingOverrides, setMappingOverrides] = useState<Record<string, string>>({});
  const [datasetInfo, setDatasetInfo] = useState("No dataset selected");
  const [documentInfo, setDocumentInfo] = useState("No document selected");
  const [execution, setExecution] = useState<Execution | null>(null);
  const [runtime, setRuntime] = useState<Runtime | null>(null);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sourceKind, setSourceKind] = useState<"upload" | "postgres" | "rest">("upload");
  const [sourceFile, setSourceFile] = useState<File | null>(null);
  const [sourceResult, setSourceResult] = useState<Record<string, unknown> | null>(null);
  const [analyticsFile, setAnalyticsFile] = useState<File | null>(null);
  const [analyticsResult, setAnalyticsResult] = useState<AnalyticsResult | null>(null);
  const [analyticsPlan, setAnalyticsPlan] = useState<Record<string, unknown>>(SHORTFALL_PLAN);
  const [pgHost, setPgHost] = useState("127.0.0.1");
  const [pgPort, setPgPort] = useState("5432");
  const [pgDatabase, setPgDatabase] = useState("");
  const [pgUser, setPgUser] = useState("");
  const [pgSecretRef, setPgSecretRef] = useState("EXTERNAL_PG_PASSWORD");
  const [pgSchema, setPgSchema] = useState("external_demo");
  const [pgTable, setPgTable] = useState("orders");
  const [restUrl, setRestUrl] = useState("");
  const [restSecretRef, setRestSecretRef] = useState("REST_BEARER_TOKEN");
  const [workflowRuns, setWorkflowRuns] = useState<WorkflowRun[]>([]);
  const [runComparison, setRunComparison] = useState<RunComparison | null>(null);
  const [previousRunId, setPreviousRunId] = useState("");
  const [currentRunId, setCurrentRunId] = useState("");
  const [runHistoryError, setRunHistoryError] = useState<string | null>(null);
  const [runBusy, setRunBusy] = useState(false);
  const activeWorkflow = execution?.saved_workflow ?? templateResult?.saved_workflow ?? null;

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API}/runtime`, { cache: "no-store", signal: controller.signal })
      .then((response) => apiJson<Runtime>(response))
      .then(setRuntime)
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setRuntimeError(caught instanceof Error ? caught.message : "Backend diagnostics are unavailable.");
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!activeWorkflow) {
      setWorkflowRuns([]);
      setRunComparison(null);
      setPreviousRunId("");
      setCurrentRunId("");
      return;
    }
    const controller = new AbortController();
    fetch(`${API}/workflows/${activeWorkflow.workflow_id}/runs?limit=20`, { cache: "no-store", signal: controller.signal })
      .then((response) => apiJson<{ runs: WorkflowRun[] }>(response))
      .then((result) => {
        setWorkflowRuns(result.runs);
        setPreviousRunId(result.runs[1]?.run_id ?? "");
        setCurrentRunId(result.runs[0]?.run_id ?? "");
        setRunComparison(null);
        setRunHistoryError(null);
      })
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setRunHistoryError(caught instanceof Error ? caught.message : "Run history is unavailable.");
      });
    return () => controller.abort();
  }, [activeWorkflow?.workflow_id]);

  async function uploadDataset(file: File) {
    setPhase("Inspecting structured data");
    const body = new FormData();
    body.append("file", file);
    const result = await apiJson<{ filename: string; row_count: number; column_count: number }>(
      await fetch(`${API}/datasets/inspect`, { method: "POST", body }),
    );
    setDatasetInfo(`${result.filename} · ${result.row_count} rows · ${result.column_count} columns`);
  }

  async function uploadDocument(file: File): Promise<DocumentResult> {
    setPhase("Ingesting and indexing policy evidence");
    const body = new FormData();
    body.append("file", file);
    const result = await apiJson<DocumentResult>(await fetch(`${API}/documents`, { method: "POST", body }));
    setDocumentInfo(`${result.filename} · ${result.page_count} pages · ${result.chunk_count} evidence chunks`);
    return result;
  }

  async function runTask(event: FormEvent) {
    event.preventDefault();
    if (demo === "sources" || demo === "analytics") return;
    if (busy || !dataset || !document || (demo === "sales" && (!customers || !targets)) || (demo === "template" && (!customers || !templateTarget)) || !goal.trim() || runtime?.status !== "ready") return;
    setBusy(true);
    setError(null);
    setExecution(null);
    try {
      if (demo === "template" && customers && templateTarget) {
        const files = new FormData();
        files.append("target", templateTarget);
        files.append("sources", dataset);
        files.append("sources", customers);
        files.append("source_roles", JSON.stringify(["orders", "customers"]));
        if (!templateProposal) {
          setPhase("Inspecting template and proposing field mappings");
          if (Object.keys(mappingOverrides).length) files.append("explicit_mappings", JSON.stringify(mappingOverrides));
          const proposal = await apiJson<TemplateProposal>(await fetch(`${API}/template-transforms/proposals`, { method: "POST", body: files }));
          setTemplateProposal(proposal);
          setTemplateResult(null);
          return;
        }
        setPhase("Cleaning, joining, deriving, writing, and reopening the template");
        files.append("policy", document);
        files.append("plan", JSON.stringify(canonicalTemplatePlan(templateProposal)));
        const result = await apiJson<TemplateResult>(await fetch(`${API}/template-transforms/executions`, { method: "POST", body: files }));
        setTemplateResult(result);
        return;
      }
      if (demo === "sales" && customers && targets) {
        setPhase("Cleaning, joining, verifying, and building workbook");
        const body = new FormData();
        body.append("transactions", dataset);
        body.append("customers", customers);
        body.append("targets", targets);
        body.append("policy", document);
        body.append("goal", goal.trim());
        const result = await apiJson<Execution>(await fetch(`${API}/sales/reports/august`, { method: "POST", body }));
        setExecution(result);
        setDatasetInfo(`${dataset.name} · processed by bounded sales workflow`);
        setDocumentInfo(`${document.name} · cited commission policy`);
        return;
      }
      const [_, ingested, encodedDataset] = await Promise.all([
        uploadDataset(dataset),
        uploadDocument(document),
        fileToBase64(dataset),
      ]);
      setPhase(runtime.mode === "demo" ? "Running deterministic demo workflow" : "Running model-orchestrated workflow");
      const result = await apiJson<Execution>(
        await fetch(`${API}/agent/tasks`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            goal: goal.trim(),
            resources: {
              dataset: { filename: dataset.name, content_base64: encodedDataset },
              document_id: ingested.document_id,
            },
          }),
        }),
      );
      setExecution(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unexpected task error");
    } finally {
      setBusy(false);
      setPhase(null);
    }
  }

  async function confirmTemplateMappings() {
    if (busy || !dataset || !customers || !templateTarget || unresolvedTemplateFields.some((item) => !mappingOverrides[item.target_field]?.trim())) return;
    setBusy(true);
    setError(null);
    setTemplateResult(null);
    setPhase("Validating confirmed field mappings");
    const files = new FormData();
    files.append("target", templateTarget);
    files.append("sources", dataset);
    files.append("sources", customers);
    files.append("source_roles", JSON.stringify(["orders", "customers"]));
    files.append("explicit_mappings", JSON.stringify(mappingOverrides));
    try {
      const proposal = await apiJson<TemplateProposal>(await fetch(`${API}/template-transforms/proposals`, { method: "POST", body: files }));
      setTemplateProposal(proposal);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unexpected mapping validation error");
    } finally {
      setBusy(false);
      setPhase(null);
    }
  }

  async function importBoundSource() {
    setBusy(true);
    setError(null);
    setSourceResult(null);
    setPhase("Importing bounded source");
    try {
      if (sourceKind === "upload") {
        if (!sourceFile) throw new Error("Select a JSON, Parquet, or TXT file.");
        const body = new FormData();
        body.append("file", sourceFile);
        const path = sourceFile.name.toLowerCase().endsWith(".txt") ? "/documents" : "/datasets/inspect";
        const result = await apiJson<Record<string, unknown>>(await fetch(`${API}${path}`, { method: "POST", body }));
        setSourceResult(result);
        return;
      }
      if (sourceKind === "postgres") {
        const result = await apiJson<Record<string, unknown>>(await fetch(`${API}/sources/postgres/import`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            source: {
              host: pgHost,
              port: Number(pgPort),
              database: pgDatabase,
              user: pgUser,
              password_secret_ref: pgSecretRef,
            },
            table: { schema: pgSchema, table: pgTable },
          }),
        }));
        setSourceResult(result);
        return;
      }
      const result = await apiJson<Record<string, unknown>>(await fetch(`${API}/sources/rest/import`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          source: {
            url: restUrl,
            header_secret_refs: restSecretRef.trim() ? { Authorization: restSecretRef.trim() } : {},
          },
        }),
      }));
      setSourceResult(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Source import failed");
    } finally {
      setBusy(false);
      setPhase(null);
    }
  }

  async function runAnalytics() {
    if (!analyticsFile || runtime?.status !== "ready") return;
    setBusy(true);
    setError(null);
    setAnalyticsResult(null);
    setPhase("Validating and executing the typed analytical plan");
    try {
      const validated = await apiJson<Record<string, unknown>>(await fetch(`${API}/analytics/validate`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(analyticsPlan),
      }));
      setAnalyticsPlan(validated);
      const body = new FormData();
      body.append("file", analyticsFile);
      body.append("request", JSON.stringify(validated));
      const result = await apiJson<AnalyticsResult>(await fetch(`${API}/analytics/execute`, { method: "POST", body }));
      setAnalyticsResult(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Analytics execution failed");
    } finally {
      setBusy(false);
      setPhase(null);
    }
  }

  async function loadWorkflowRuns(workflowId: string): Promise<WorkflowRun[]> {
    const result = await apiJson<{ runs: WorkflowRun[] }>(
      await fetch(`${API}/workflows/${workflowId}/runs?limit=20`, { cache: "no-store" }),
    );
    setWorkflowRuns(result.runs);
    setPreviousRunId(result.runs[1]?.run_id ?? "");
    setCurrentRunId(result.runs[0]?.run_id ?? "");
    return result.runs;
  }

  async function currentStepOverrides(): Promise<Record<string, Record<string, unknown>>> {
    if (demo === "sales" && dataset && customers && targets) {
      const [transactionsContent, customersContent, targetsContent] = await Promise.all([
        fileToBase64(dataset), fileToBase64(customers), fileToBase64(targets),
      ]);
      return {
        "1": {
          transactions: { filename: dataset.name, content_base64: transactionsContent },
          customers: { filename: customers.name, content_base64: customersContent },
          targets: { filename: targets.name, content_base64: targetsContent },
        },
      };
    }
    if (demo === "template" && dataset && customers && templateTarget && templateProposal) {
      const [ordersContent, customersContent, targetContent] = await Promise.all([
        fileToBase64(dataset), fileToBase64(customers), fileToBase64(templateTarget),
      ]);
      const roles = templateProposal.sources.map((source) => source.role);
      return {
        "1": {
          sources: [
            { role: roles[0] ?? "orders", filename: dataset.name, content_base64: ordersContent },
            { role: roles[1] ?? "customers", filename: customers.name, content_base64: customersContent },
          ],
          target: { filename: templateTarget.name, content_base64: targetContent },
        },
      };
    }
    return {};
  }

  async function runSavedWorkflow() {
    if (!activeWorkflow || runBusy) return;
    setRunBusy(true);
    setRunHistoryError(null);
    setRunComparison(null);
    try {
      const stepOverrides = await currentStepOverrides();
      await apiJson<WorkflowRun>(await fetch(`${API}/workflows/${activeWorkflow.workflow_id}/runs`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ step_overrides: stepOverrides }),
      }));
      await loadWorkflowRuns(activeWorkflow.workflow_id);
    } catch (caught) {
      setRunHistoryError(caught instanceof Error ? caught.message : "Workflow rerun failed.");
    } finally {
      setRunBusy(false);
    }
  }

  async function compareSelectedRuns() {
    if (!previousRunId || !currentRunId || previousRunId === currentRunId || runBusy) return;
    setRunBusy(true);
    setRunHistoryError(null);
    try {
      const result = await apiJson<RunComparison>(await fetch(`${API}/workflow-runs/compare`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          previous_run_id: previousRunId,
          current_run_id: currentRunId,
        }),
      }));
      setRunComparison(result);
    } catch (caught) {
      setRunHistoryError(caught instanceof Error ? caught.message : "Run comparison failed.");
    } finally {
      setRunBusy(false);
    }
  }

  const selectedTemplatePlan = canonicalTemplatePlan(templateProposal);
  const derivedTargets = new Set(selectedTemplatePlan?.derivations.map((item) => item.target_field) ?? []);
  const unresolvedTemplateFields = templateProposal?.clarifications.filter((item) => !derivedTargets.has(item.target_field)) ?? [];
  const mappingOverridesComplete = unresolvedTemplateFields.every((item) => Boolean(mappingOverrides[item.target_field]?.trim()));
  const hasInputs = Boolean(dataset && document && (
    demo === "grades" || (demo === "sales" && customers && targets) || (demo === "template" && customers && templateTarget)
  ));
  const canRun = Boolean(demo !== "sources" && demo !== "analytics" && hasInputs && goal.trim() && runtime?.status === "ready" && !busy && (demo !== "template" || !templateProposal || unresolvedTemplateFields.length === 0));
  const runtimeLabel = runtime
    ? runtime.orchestrator_status === "demo"
      ? "Demo provider"
      : runtime.orchestrator_status === "configured"
        ? "Real provider configured"
        : "Provider unavailable"
    : runtimeError ? "Backend unavailable" : "Checking backend";
  const latestRun = workflowRuns[0];
  const comparisonPrevious = workflowRuns.find((run) => run.run_id === runComparison?.previous_run_id);
  const comparisonCurrent = workflowRuns.find((run) => run.run_id === runComparison?.current_run_id);
  const changedMetrics = runComparison?.metrics.filter((item) => item.status === "changed" && item.previous && item.current) ?? [];

  return <main>
    <header>
      <div><p className="eyebrow">TRUSTWORTHY DATA + KNOWLEDGE</p><h1>Agentic Intelligence Workspace</h1><p className="lede">Turn a goal, data, and source documents into a traceable result you can inspect and reproduce.</p></div>
      <span className={`status ${runtime?.status ?? "checking"}`}>{runtimeLabel}</span>
    </header>
    {(runtimeError || runtime?.status === "not_ready" || runtime?.mode === "demo") && <aside className={`runtimeNotice ${runtime?.status === "not_ready" || runtimeError ? "blocked" : "demo"}`}>
      <strong>{runtimeError ? "Backend connection failed" : runtime?.mode === "demo" ? "Local demonstration boundaries" : "Production configuration incomplete"}</strong>
      {runtimeError && <p>{runtimeError}</p>}
      {runtime && <p>{runtime.storage} storage · {runtime.embedding_provider} embeddings · {runtime.orchestrator_provider} orchestration</p>}
      {runtime?.limitations.length ? <ul>{runtime.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul> : null}
    </aside>}
    <form onSubmit={runTask}>
      <section className="composer">
        <label htmlFor="demo">Demonstration workflow</label>
        <select id="demo" className="modePicker" value={demo} disabled={busy} onChange={(event) => {
          const next = event.target.value as "grades" | "sales" | "template" | "sources" | "analytics";
          setDemo(next);
          setGoal(next === "grades"
            ? "According to the grading policy, what score do I need on my final to finish with an A?"
            : next === "template"
              ? "Prepare this month's submission in the supplied template. Preserve its structure, derive net sales, apply the documented commission policy, verify the output, and save a reusable workflow."
              : next === "sources"
                ? "Import a bounded JSON, Parquet, PostgreSQL, or REST source into the existing dataset tools without storing secrets in the browser."
                : next === "analytics"
                  ? "Which region is furthest below target, what is the shortfall, and which salesperson contributed the most net sales?"
              : "Prepare the monthly sales report. Clean the transaction data, compare performance against targets by region, identify the largest drivers of underperformance, calculate salesperson commissions according to the policy, generate appropriate charts, and export a management workbook while preserving the original data.");
          setDataset(null); setDocument(null); setCustomers(null); setTargets(null); setExecution(null);
          setTemplateTarget(null); setTemplateProposal(null); setTemplateResult(null); setMappingOverrides({});
          setSourceResult(null); setSourceFile(null); setAnalyticsFile(null); setAnalyticsResult(null); setAnalyticsPlan(SHORTFALL_PLAN);
          setDatasetInfo("No dataset selected"); setDocumentInfo("No document selected");
        }}><option value="grades">Grades + syllabus</option><option value="sales">Reusable monthly sales workflow</option><option value="template">Transform to supplied template</option><option value="sources">External and file sources</option><option value="analytics">Deterministic analytics</option></select>
        {demo === "analytics" && <p className="sourceNote">Numbers come from a typed analytical plan executed in pandas. The model does not invent the shortfall or contributor ranking.</p>}
        {demo === "sources" && <p className="sourceNote">Passwords and tokens stay in server environment variables. This UI only sends secret reference names, never raw credentials.</p>}
        {(demo === "sales" || demo === "template") && <div className="promise" aria-label="Workflow outcomes"><span>01 · Inspect & map</span><span>02 · Transform & derive</span><span>03 · Verify & export</span></div>}
        {demo === "analytics" && <div className="promise" aria-label="Analytics outcomes"><span>01 · Typed plan</span><span>02 · Deterministic facts</span><span>03 · Verified explanation</span></div>}
        <label htmlFor="goal">What should the workspace accomplish?</label>
        <textarea id="goal" value={goal} onChange={(event) => setGoal(event.target.value)} required maxLength={10000} />
        {demo !== "sources" && demo !== "analytics" && <>
        <div className="uploads">
          <label className="upload">{demo === "grades" ? "Structured grade data" : demo === "template" ? "Raw orders" : "Monthly transactions"}<input type="file" accept=".csv,.xlsx" disabled={busy} onChange={(event) => { setDataset(event.target.files?.[0] ?? null); setDatasetInfo("Awaiting inspection"); setTemplateProposal(null); setTemplateResult(null); setMappingOverrides({}); }} /><small>{dataset?.name ?? datasetInfo}</small></label>
          <label className="upload">{demo === "grades" ? "Grading policy PDF" : demo === "template" ? "Reporting policy PDF" : "Commission policy PDF"}<input type="file" accept=".pdf,application/pdf" disabled={busy} onChange={(event) => { setDocument(event.target.files?.[0] ?? null); setDocumentInfo("Awaiting ingestion"); setTemplateResult(null); }} /><small>{document?.name ?? documentInfo}</small></label>
          {demo === "sales" && <><label className="upload">Customer regions<input type="file" accept=".csv,.xlsx" disabled={busy} onChange={(event) => setCustomers(event.target.files?.[0] ?? null)} /><small>{customers?.name ?? "No customer file selected"}</small></label><label className="upload">Regional targets<input type="file" accept=".csv,.xlsx" disabled={busy} onChange={(event) => setTargets(event.target.files?.[0] ?? null)} /><small>{targets?.name ?? "No target file selected"}</small></label></>}
          {demo === "template" && <><label className="upload">Customer master<input type="file" accept=".csv,.xlsx" disabled={busy} onChange={(event) => { setCustomers(event.target.files?.[0] ?? null); setTemplateProposal(null); setTemplateResult(null); setMappingOverrides({}); }} /><small>{customers?.name ?? "No customer master selected"}</small></label><label className="upload">Required target template<input type="file" accept=".csv,.xlsx" disabled={busy} onChange={(event) => { setTemplateTarget(event.target.files?.[0] ?? null); setTemplateProposal(null); setTemplateResult(null); setMappingOverrides({}); }} /><small>{templateTarget?.name ?? "No target template selected"}</small></label></>}
        </div>
        <button disabled={!canRun} title={runtime?.status === "not_ready" ? "Complete backend configuration before running tasks" : unresolvedTemplateFields.length ? "Resolve required fields before execution" : undefined}>{busy ? phase ?? "Executing workflow…" : demo === "template" ? templateProposal ? "Execute verified template transform" : "Inspect and propose mappings" : demo === "sales" ? "Build verified monthly report" : "Run verified task"}</button>
        </>}
        {demo === "sources" && <div>
          <label htmlFor="sourceKind">Source type</label>
          <select id="sourceKind" className="modePicker" value={sourceKind} disabled={busy} onChange={(event) => { setSourceKind(event.target.value as "upload" | "postgres" | "rest"); setSourceResult(null); setError(null); setPhase(null); }}>
            <option value="upload">Upload JSON / Parquet / TXT</option>
            <option value="postgres">PostgreSQL (secret reference)</option>
            <option value="rest">REST JSON (secret reference)</option>
          </select>
          {sourceKind === "upload" && <label className="upload">Structured or text file<input type="file" accept=".json,.parquet,.pq,.txt" disabled={busy} onChange={(event) => setSourceFile(event.target.files?.[0] ?? null)} /><small>{sourceFile?.name ?? "No file selected"}</small></label>}
          {sourceKind === "postgres" && <div className="sourceGrid">
            <label>Host<input value={pgHost} onChange={(event) => setPgHost(event.target.value)} /></label>
            <label>Port<input value={pgPort} onChange={(event) => setPgPort(event.target.value)} /></label>
            <label>Database<input value={pgDatabase} onChange={(event) => setPgDatabase(event.target.value)} /></label>
            <label>User<input value={pgUser} onChange={(event) => setPgUser(event.target.value)} /></label>
            <label>Password secret ref<input value={pgSecretRef} onChange={(event) => setPgSecretRef(event.target.value)} autoComplete="off" /></label>
            <label>Schema<input value={pgSchema} onChange={(event) => setPgSchema(event.target.value)} /></label>
            <label>Table<input value={pgTable} onChange={(event) => setPgTable(event.target.value)} /></label>
          </div>}
          {sourceKind === "rest" && <div className="sourceGrid">
            <label>HTTPS URL<input value={restUrl} onChange={(event) => setRestUrl(event.target.value)} /></label>
            <label>Authorization secret ref<input value={restSecretRef} onChange={(event) => setRestSecretRef(event.target.value)} autoComplete="off" /></label>
          </div>}
          <button type="button" disabled={busy || runtime?.status !== "ready"} onClick={importBoundSource}>{busy ? phase ?? "Importing…" : "Import source"}</button>
        </div>}
        {demo === "analytics" && <div>
          <label className="upload">Analytics dataset (use sample_data/analytics_sales.csv)<input type="file" accept=".csv,.xlsx,.json,.parquet,.pq" disabled={busy} onChange={(event) => setAnalyticsFile(event.target.files?.[0] ?? null)} /><small>{analyticsFile?.name ?? "No dataset selected"}</small></label>
          <pre className="sourceNote">{JSON.stringify(analyticsPlan, null, 2)}</pre>
          <button type="button" disabled={busy || !analyticsFile || runtime?.status !== "ready"} onClick={runAnalytics}>{busy ? phase ?? "Running analytics…" : "Run typed analytical plan"}</button>
        </div>}
        {busy && <p className="progress" role="status" aria-live="polite"><span />{phase ?? "Executing bounded workflow"}. Source uploads remain unchanged.</p>}
        {demo !== "sources" && demo !== "analytics" && !hasInputs ? <p className="hint">Select all required sample inputs to enable the task.</p> : null}
        {error && <p className="error" role="alert">{error}</p>}
      </section>
    </form>
    {demo === "analytics" ? <div className="results">
      <section className="panel answer"><div className="panelTitle"><h2>Deterministic explanation</h2><span className={`pill ${analyticsResult ? "verified" : "idle"}`}>{analyticsResult ? "verified facts" : "Awaiting run"}</span></div>
        {analyticsResult ? <p>{analyticsResult.explanation}</p> : <p>Upload analytics_sales.csv to compute the largest regional shortfall and top salesperson contribution from structured facts.</p>}
      </section>
      <section className="panel"><div className="panelTitle"><h2>Numeric facts</h2><span>{analyticsResult?.facts.length ?? 0}</span></div>
        {analyticsResult?.facts.map((fact) => <p key={fact.key}><strong>{fact.label}: {fact.value ?? "n/a"}</strong><small className="sourceNote">{fact.key} · {fact.calculation}</small></p>)}
      </section>
      <section className="panel"><div className="panelTitle"><h2>Result table</h2><span>{analyticsResult?.row_count ?? 0} rows</span></div>
        {analyticsResult ? <pre className="sourceNote">{JSON.stringify(analyticsResult.rows, null, 2)}</pre> : <p className="muted">Aggregations stay inspectable and rerunnable.</p>}
      </section>
      {analyticsResult && <AnalyticsVisualization result={analyticsResult} />}
    </div> : demo === "sources" ? <div className="results">
      <section className="panel answer"><div className="panelTitle"><h2>Imported source</h2><span className={`pill ${sourceResult ? "verified" : "idle"}`}>{sourceResult ? "imported" : "Awaiting import"}</span></div>
        {sourceResult ? <pre className="sourceNote">{JSON.stringify(sourceResult, null, 2)}</pre> : <p>JSON and Parquet become inspectable datasets. TXT is chunked through the existing retrieval pipeline. PostgreSQL and REST imports require server-side secret references.</p>}
      </section>
    </div> : demo === "template" ? <div className="results">
      <section className="panel answer"><div className="panelTitle"><h2>Field mapping plan</h2><span className={`pill ${templateResult?.status ?? templateProposal?.status ?? "idle"}`}>{templateResult?.status?.replaceAll("_", " ") ?? templateProposal?.status?.replaceAll("_", " ") ?? "Awaiting inspection"}</span></div>
        {templateProposal ? <><p className="templateSummary">Target: {templateProposal.plan.target_filename} · {templateProposal.plan.target_headers.length} columns · {templateProposal.template.sheets.length || 1} sheet(s)</p>{isCanonicalFixtureProposal(templateProposal) && <p className="fixtureNote">Canonical demo rules detected: customer join, net-sales calculation, and evidence-bound commission derivation are applied only to the shipped sample schemas.</p>}<div className="mappingTable" role="table" aria-label="Proposed field mappings">{templateProposal.plan.mappings.map((mapping) => <div className="mappingRow" role="row" key={mapping.target_field}><strong>{mapping.target_field}</strong><span>{derivedTargets.has(mapping.target_field) ? "Deterministic derivation" : mapping.mapping_type === "template_formula" ? "Trusted template formula" : mapping.source_role && mapping.source_field ? `${mapping.source_role}.${mapping.source_field}` : "Unresolved"}</span><span className={`pill ${derivedTargets.has(mapping.target_field) ? "verified" : mapping.status}`}>{derivedTargets.has(mapping.target_field) ? "derived" : mapping.status.replaceAll("_", " ")}</span><small>{Math.round(mapping.confidence * 100)}% · {mapping.evidence}</small></div>)}</div></> : <p>Upload the raw orders, customer master, reporting policy, and target workbook to inspect schemas and propose mappings.</p>}
        {unresolvedTemplateFields.length > 0 && <div className="warnings clarification"><strong>Clarification required</strong><p>Confirm each source as <code>role.field</code>. Nothing executes until every required field is resolved.</p><div className="clarificationGrid">{unresolvedTemplateFields.map((item) => <label key={item.target_field}><span>{item.target_field}</span><input value={mappingOverrides[item.target_field] ?? ""} placeholder={item.candidate_options[0] ?? "role.field"} disabled={busy} onChange={(event) => setMappingOverrides((current) => ({ ...current, [item.target_field]: event.target.value }))} /><small>{item.reason}{item.candidate_options.length ? ` Options: ${item.candidate_options.join(", ")}` : ""}</small></label>)}</div><button type="button" className="confirmMappings" disabled={busy || !mappingOverridesComplete} onClick={confirmTemplateMappings}>Validate confirmed mappings</button></div>}
      </section>
      <section className="panel"><div className="panelTitle"><h2>Validation</h2><span>{templateResult?.validation?.checks.filter((item) => item.passed).length ?? 0} checks passed</span></div>{templateResult?.validation ? <><p>{templateResult.validation.input_row_count} input rows → {templateResult.validation.output_row_count} output rows</p>{templateResult.validation.errors.map((item) => <p className="error" key={item}>{item}</p>)}{templateResult.validation.warnings.map((item) => <p className="warningText" key={item}>{item}</p>)}<ul className="checkList">{templateResult.validation.checks.map((item) => <li key={item.name} className={item.passed ? "passed" : "failed"}>{item.passed ? "✓" : "×"} {item.detail}</li>)}</ul></> : <p className="muted">Schema, required values, joins, workbook reopen, sheet preservation, and formulas are checked before completion.</p>}</section>
      <section className="panel"><div className="panelTitle"><h2>Artifact & provenance</h2><span>{templateResult?.provenance.length ?? 0} fields traced</span></div>{templateResult?.artifact && <a className="artifactLink" href={`${API}${templateResult.artifact.download_url}`}>Download completed template<small>{templateResult.artifact.filename} · {templateResult.artifact.row_count} rows</small></a>}{templateResult?.saved_workflow && <div className="workflowCard"><span>Reusable workflow saved</span><strong>{templateResult.saved_workflow.name}</strong><small>Version {templateResult.saved_workflow.version} · source and template drift checked</small></div>}<div className="provenanceList">{templateResult?.provenance.map((item) => <p key={item.target_field}><strong>{item.target_field}</strong><span>{item.source_fields.join(" + ") || "Template"} → {item.transformation}{item.policy_evidence_ids.length ? ` · ${item.policy_evidence_ids.length} policy citation(s)` : ""}</span></p>)}</div>{!templateResult && <p className="muted">Successful execution will expose the exact output, field lineage, validation, and saved workflow here.</p>}</section>
    </div> : <div className="results">
      {execution && execution.evidence.length > 0 && <section className="panel policyEvidence">
        <h2>Retrieved policy passages</h2>
        {execution.evidence.map((item) => <blockquote key={item.source.chunk_id}>
          <p>{item.text}</p>
          <cite>{item.source.filename} · page {item.source.page_number}</cite>
        </blockquote>)}
      </section>}
      <section className="panel answer"><div className="panelTitle"><h2>Management answer</h2><span className={`pill ${execution?.verification?.status ?? "idle"}`}>{execution?.verification?.status?.replaceAll("_", " ") ?? "Awaiting task"}</span></div><p>{execution?.answer ?? "Your grounded answer will appear here after deterministic tools finish."}</p><div className="deliverables">{execution?.artifacts.map((artifact) => <a className="artifactLink" href={`${API}${artifact.download_url}`} key={artifact.artifact_id}>Download management workbook<small>{artifact.filename} · {artifact.row_count} regional rows</small></a>)}{execution?.saved_workflow && <div className="workflowCard"><span>Reusable recipe saved</span><strong>{execution.saved_workflow.name}</strong><small>Version {execution.saved_workflow.version} · schema drift checked on rerun</small></div>}</div>{execution?.failure_reason && <p className="error">{execution.failure_reason}</p>}</section>
      <section className="panel tracePanel"><div className="panelTitle"><h2>Execution trace</h2><span>{execution?.stages.length ?? 0} stages</span></div>{execution?.provider_usage && <div className="providerUsage"><strong>{execution.provider_usage.provider} · {execution.provider_usage.model}</strong><span>{execution.provider_usage.provider_calls} calls · {execution.provider_usage.total_tokens ?? "token count unavailable"} tokens · {execution.provider_usage.latency_ms.toFixed(1)} ms{execution.provider_usage.approximate_cost_usd != null ? ` · $${execution.provider_usage.approximate_cost_usd.toFixed(6)} estimated` : ""}</span></div>}<ol className="trace">{execution?.stages.map((stage, index) => <li key={`${stage.name}-${index}`}><span className={`dot ${stage.status === "completed" ? "ok" : stage.status === "warning" ? "warn" : "fail"}`} /><div><div className="stageTitle"><strong>{stage.name}</strong><span>{stage.status}</span></div><p>{stage.explanation}</p>{Object.keys(stage.row_counts).length > 0 && <div className="facts">{Object.entries(stage.row_counts).map(([label, value]) => <small key={label}>{label.replaceAll("_", " ")}: {value}</small>)}</div>}<small>{stage.tool_name ? `${stage.tool_name} · ` : ""}{stage.evidence_ids.length} evidence · {stage.artifact_ids.length} artifacts{stage.verification_result ? ` · ${stage.verification_result.replaceAll("_", " ")}` : ""}</small></div></li>) ?? <li className="empty">Goal, plan, tool outcomes, evidence, verification, and artifacts will appear here.</li>}</ol>{execution && <details className="technicalTrace"><summary>Inspect validated tool calls</summary>{execution.trace.map((step) => <article key={step.step}><strong>{step.step}. {step.requested_tool}</strong><span>{step.duration_ms.toFixed(1)} ms</span><p>{step.observation}</p></article>)}</details>}</section>
      <section className="panel"><div className="panelTitle"><h2>Evidence & verification</h2><span>{execution?.citations.length ?? 0} citations</span></div>{execution?.warnings.length ? <div className="warnings"><strong>Data and join warnings</strong>{execution.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div> : null}{execution?.citations.map((citation) => <article className="citation" key={citation.chunk_id}><strong>{citation.filename} · page {citation.page_number}</strong><code>{citation.chunk_id}</code></article>)}{execution?.verification?.findings.map((finding, index) => <article className="finding" key={`${finding.claim}-${index}`}><span className={`pill ${finding.status}`}>{finding.status.replaceAll("_", " ")}</span><strong>{finding.claim}</strong><p>{finding.explanation}</p></article>) ?? <p className="muted">Source pages and claim checks will appear after execution.</p>}</section>
    </div>}
    {activeWorkflow && <section className="panel workflowRunsPanel">
      <div className="panelTitle"><div><span className="eyebrow">REUSABLE WORKFLOW</span><h2>{activeWorkflow.name}</h2></div><span className={`pill ${latestRun?.verification?.status ?? latestRun?.status ?? "idle"}`}>{latestRun?.verification?.status?.replaceAll("_", " ") ?? (latestRun?.status ?? "No runs yet")}</span></div>
      <div className="workflowOverview" aria-label="Workflow overview">
        <article><span>Definition</span><strong>Version {activeWorkflow.version}</strong><small title={latestRun?.definition_fingerprint ?? undefined}>{latestRun?.definition_fingerprint ? `sha256 ${latestRun.definition_fingerprint.slice(0, 12)}…` : "Recorded on first run"}</small></article>
        <article><span>Run history</span><strong>{workflowRuns.length}</strong><small>Immutable executions</small></article>
        <article><span>Latest inputs</span><strong>{latestRun?.input_snapshots.reduce((sum, item) => sum + (item.row_count ?? 0), 0) ?? 0} rows</strong><small>{latestRun?.input_snapshots.length ?? 0} source snapshots</small></article>
        <article><span>Latest trust state</span><strong>{latestRun?.verification?.status?.replaceAll("_", " ") ?? "Not run"}</strong><small>{latestRun?.warnings.length ?? 0} warnings · {latestRun?.artifacts.length ?? 0} artifacts</small></article>
      </div>
      <div className="workflowActions">
        <div><strong>Run the same definition on permitted new-period inputs</strong><p>Source identity and schema are checked before deterministic tools execute. Blocked and failed attempts remain inspectable.</p></div>
        <button type="button" disabled={runBusy} onClick={runSavedWorkflow}>{runBusy ? "Working…" : workflowRuns.length ? "Run Again with Current Inputs" : "Create First Run"}</button>
        <button type="button" className="secondaryButton" disabled={runBusy || !previousRunId || !currentRunId || previousRunId === currentRunId} onClick={compareSelectedRuns}>Compare Runs</button>
      </div>
      {runHistoryError && <p className="error" role="alert">{runHistoryError}</p>}
      <div className="runWorkspace">
        <div><h3>Run history</h3>{workflowRuns.length ? <ol className="runHistory">{workflowRuns.map((run, index) => <li id={`run-${run.run_id}`} key={run.run_id}>
          <div><strong>Run #{workflowRuns.length - index}</strong><span>{new Date(run.started_at).toLocaleString()}</span></div>
          <span className={`pill ${run.verification?.status ?? run.status}`}>{run.verification?.status?.replaceAll("_", " ") ?? run.status}</span>
          <p>{run.input_snapshots.map((item) => `${item.identity}${item.row_count === undefined ? "" : ` · ${item.row_count} rows`}`).join("; ") || "No dataset snapshot"}</p>
          <small>{run.warnings.length} warnings · {run.facts.length} deterministic facts · {run.artifacts.length} artifacts</small>
          <div className="runLifecycle" aria-label={`Run ${workflowRuns.length - index} lifecycle`}>{run.lifecycle.map((event) => <span className={event.state} key={`${run.run_id}-${event.state}-${event.occurred_at}`}>{event.state.replaceAll("_", " ")}</span>)}</div>
          {run.error && <p className="error">{run.error}</p>}
          {run.drift_findings.map((finding) => <p className="warningText" key={`${run.run_id}-${finding.kind}`}>{finding.kind} drift: {finding.explanation}</p>)}
          {run.artifacts.map((artifact) => artifact.download_url && <a key={artifact.artifact_id} href={`${API}${artifact.download_url}`}>Download {artifact.filename ?? "artifact"}</a>)}
        </li>)}</ol> : <p className="muted">Run the saved workflow to create its first immutable history entry.</p>}</div>
        <div><h3>What changed?</h3>
          {workflowRuns.filter((run) => run.status === "completed").length >= 2 && <div className="compareControls">
            <label>Previous run<select value={previousRunId} onChange={(event) => { setPreviousRunId(event.target.value); setRunComparison(null); }}>{workflowRuns.filter((run) => run.status === "completed").map((run, index) => <option value={run.run_id} key={run.run_id}>Run #{workflowRuns.length - index} · {new Date(run.started_at).toLocaleDateString()}</option>)}</select></label>
            <span aria-hidden="true">→</span>
            <label>Current run<select value={currentRunId} onChange={(event) => { setCurrentRunId(event.target.value); setRunComparison(null); }}>{workflowRuns.filter((run) => run.status === "completed").map((run, index) => <option value={run.run_id} key={run.run_id}>Run #{workflowRuns.length - index} · {new Date(run.started_at).toLocaleDateString()}</option>)}</select></label>
            <button type="button" className="secondaryButton" disabled={runBusy || !previousRunId || !currentRunId || previousRunId === currentRunId} onClick={compareSelectedRuns}>Show observed changes</button>
          </div>}
          {runComparison ? <div className="changeList">
          <p className="observedLabel">Observed change · deterministic, not causal interpretation</p>
          <div className="comparisonProvenance"><a href={`#run-${runComparison.previous_run_id}`}>Previous · {comparisonPrevious ? new Date(comparisonPrevious.started_at).toLocaleString() : runComparison.previous_run_id}</a><span>compared with</span><a href={`#run-${runComparison.current_run_id}`}>Current · {comparisonCurrent ? new Date(comparisonCurrent.started_at).toLocaleString() : runComparison.current_run_id}</a></div>
          {changedMetrics.length > 0 && <div className="deltaCards" aria-label="Key deterministic changes">{changedMetrics.slice(0, 4).map((item) => <article key={`delta-${item.fact_id}`}>
            <span>{item.label}</span><strong>{item.percent_change == null ? (item.absolute_change == null ? "Unavailable" : formatSigned(item.absolute_change)) : `${formatSigned(item.percent_change)}%`}</strong>
            <div className="comparisonBars" aria-label={`${item.label}: ${formatRunValue(item.previous?.value ?? 0, item.unit)} before, ${formatRunValue(item.current?.value ?? 0, item.unit)} current`}><i style={{ width: `${comparisonBarWidth(item.previous?.value, item.previous?.value, item.current?.value)}%` }} /><i style={{ width: `${comparisonBarWidth(item.current?.value, item.previous?.value, item.current?.value)}%` }} /></div>
            <small>{formatRunValue(item.previous?.value ?? 0, item.unit)} → {formatRunValue(item.current?.value ?? 0, item.unit)}</small>
          </article>)}</div>}
          <h4>Business metrics</h4>
          {runComparison.metrics.filter((item) => item.status !== "unchanged").map((item) => <article key={item.fact_id}>
            <div><strong>{item.label}</strong><span className={`changeStatus ${item.status}`}>{item.status}</span></div>
            <p>{item.previous ? formatRunValue(item.previous.value, item.unit) : "Unavailable"} → {item.current ? formatRunValue(item.current.value, item.unit) : "Unavailable"}</p>
            <small>{item.absolute_change == null ? item.percent_change_reason : `${formatSigned(item.absolute_change)}${item.percent_change == null ? ` · ${item.percent_change_reason}` : ` · ${formatSigned(item.percent_change)}%`}`}</small>
          </article>)}
          {runComparison.row_counts.map((item) => <article key={item.input_key}><div><strong>Rows · {item.identity_current ?? item.identity_previous}</strong></div><p>{item.previous ?? "Unavailable"} → {item.current ?? "Unavailable"}</p><small>{item.absolute_change == null ? item.percent_change_reason : formatSigned(item.absolute_change)}</small></article>)}
          <h4>Data quality</h4>
          {runComparison.quality.filter((item) => item.section !== "join" && item.section !== "category" && item.absolute_change !== 0).map((item) => <article key={item.quality_id}><div><strong>{item.label}</strong><span>{item.absolute_change == null ? "unavailable" : formatSigned(item.absolute_change)}</span></div><p>{item.previous ?? "Unavailable"} → {item.current ?? "Unavailable"}</p></article>)}
          {runComparison.categories.filter((item) => item.added.length || item.removed.length || item.previous_unique_count !== item.current_unique_count).map((item) => <article key={`${item.input_key}-${item.column}`}><div><strong>Categories · {item.column}</strong><span>{item.previous_unique_count} → {item.current_unique_count}</span></div>{item.values_complete ? <p>{item.added.length ? `Added: ${item.added.join(", ")}. ` : ""}{item.removed.length ? `Removed: ${item.removed.join(", ")}.` : ""}</p> : <p>Category values exceeded the safe snapshot bound; only unique counts are compared.</p>}</article>)}
          {runComparison.quality.some((item) => item.section === "join" && item.absolute_change !== 0) && <h4>Join quality</h4>}
          {runComparison.quality.filter((item) => item.section === "join" && item.absolute_change !== 0).map((item) => <article key={item.quality_id}><div><strong>{item.label}</strong><span>{item.absolute_change == null ? "unavailable" : formatSigned(item.absolute_change)}</span></div><p>{item.previous ?? "Unavailable"} → {item.current ?? "Unavailable"}</p></article>)}
          <h4>Schema and sources</h4>
          {runComparison.snapshots.map((item) => <article key={item.input_key}><div><strong>Source / schema</strong><span className={`changeStatus ${item.status}`}>{item.status.replaceAll("_", " ")}</span></div><p>{item.explanation}</p>{item.added_columns.length > 0 && <small>Added columns: {item.added_columns.join(", ")}</small>}{item.removed_columns.length > 0 && <small>Removed columns: {item.removed_columns.join(", ")}</small>}{Object.entries(item.type_changes).map(([column, types]) => <small key={column}>{column}: {types.previous} → {types.current}</small>)}</article>)}
          <h4>Trust and execution</h4>
          {runComparison.warnings.map((item) => <article key={item.warning}><div><strong>Warning</strong><span>{formatSigned(item.change)}</span></div><p>{item.warning}</p></article>)}
          <article><div><strong>Verification</strong></div><p>{runComparison.verification_previous?.status?.replaceAll("_", " ") ?? "not recorded"} → {runComparison.verification_current?.status?.replaceAll("_", " ") ?? "not recorded"}</p></article>
          <article><div><strong>Artifacts</strong></div><p>{runComparison.artifact_count_previous} → {runComparison.artifact_count_current}</p></article>
          {runComparison.steps.map((item) => <article key={item.step}><div><strong>{item.step}. {item.tool_name}</strong><span>{item.previous_status ?? "unavailable"} → {item.current_status ?? "unavailable"}</span></div><small>Warnings {formatSigned(item.warning_change)} · artifacts {formatSigned(item.artifact_change)}</small></article>)}
        </div> : <p className="muted">Select two completed runs to compare their saved facts and source snapshots. Undefined percentages remain undefined.</p>}</div>
      </div>
    </section>}
  </main>;
}

function formatRunValue(value: number, unit?: string | null): string {
  const formatted = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
  return unit === "percent" ? `${formatted}%` : formatted;
}

function formatSigned(value: number): string {
  const formatted = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(Math.abs(value));
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${formatted}`;
}

function comparisonBarWidth(value?: number, previous?: number, current?: number): number {
  if (value === undefined) return 0;
  const scale = Math.max(Math.abs(previous ?? 0), Math.abs(current ?? 0), 1);
  return Math.max(3, Math.round((Math.abs(value) / scale) * 100));
}

function canonicalTemplatePlan(proposal: TemplateProposal | null): TemplatePlan | null {
  if (!proposal) return null;
  if (!isCanonicalFixtureProposal(proposal)) return proposal.plan;
  return {
    ...proposal.plan,
    joins: [{ right_role: "customers", left_on: ["orders.customer_id"], right_on: ["cust_id"], how: "left", block_many_to_many: true, block_row_multiplication: true, max_unmatched_left_percentage: 0 }],
    derivations: [
      { target_field: "Net Sales", operation: "subtract", inputs: [{ source_role: "orders", source_field: "gross_sales", transformation: "normalize_currency" }, { source_role: "orders", source_field: "returns", transformation: "none" }], separator: " " },
      { target_field: "Commission", operation: "policy_multiply", inputs: [{ source_role: "target", source_field: "Net Sales", transformation: "none" }], separator: " ", policy_query: "commission policy rate" },
    ],
    unique_fields: ["Order ID"],
  };
}

function isCanonicalFixtureProposal(proposal: TemplateProposal): boolean {
  const expectedHeaders = ["Order ID", "Customer Name", "Region", "Net Sales", "Commission", "Total"];
  const expectedSources: Record<string, { filename: string; columns: string[] }> = {
    orders: { filename: "raw_orders.xlsx", columns: ["order_id", "customer_id", "gross_sales", "returns", "eligible_sales"] },
    customers: { filename: "customer_master.csv", columns: ["cust_id", "customer_name", "territory"] },
  };
  if (proposal.plan.target_filename !== "required_template.xlsx" || JSON.stringify(proposal.plan.target_headers) !== JSON.stringify(expectedHeaders)) return false;
  if (proposal.plan.source_roles.length !== 2 || proposal.sources.length !== 2) return false;
  return proposal.sources.every((source) => {
    const expected = expectedSources[source.role];
    return Boolean(expected && source.inspection.filename === expected.filename && JSON.stringify(source.inspection.columns) === JSON.stringify(expected.columns));
  });
}
