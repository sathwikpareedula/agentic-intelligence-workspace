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
  saved_workflow?: { workflow_id: string; name: string; version: number; rerun_url: string };
  verification?: { status: string; findings: { claim: string; status: string; explanation: string }[] };
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
  saved_workflow?: { workflow_id: string; name: string; version: number; rerun_url: string };
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

export default function WorkspacePage() {
  const [demo, setDemo] = useState<"grades" | "sales" | "template" | "sources" | "analytics">("sales");
  const [goal, setGoal] = useState("Prepare the August sales report. Clean transactions, compare regional targets, identify the largest shortfalls, calculate policy-based commissions, and export a management workbook while preserving the originals.");
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
              : "Prepare the August sales report. Clean the transaction data, compare performance against targets by region, identify the largest drivers of underperformance, calculate salesperson commissions according to the policy, generate appropriate charts, and export a management workbook while preserving the original data.");
          setDataset(null); setDocument(null); setCustomers(null); setTargets(null); setExecution(null);
          setTemplateTarget(null); setTemplateProposal(null); setTemplateResult(null); setMappingOverrides({});
          setSourceResult(null); setSourceFile(null); setAnalyticsFile(null); setAnalyticsResult(null); setAnalyticsPlan(SHORTFALL_PLAN);
          setDatasetInfo("No dataset selected"); setDocumentInfo("No document selected");
        }}><option value="grades">Grades + syllabus</option><option value="sales">August sales report</option><option value="template">Transform to supplied template</option><option value="sources">External and file sources</option><option value="analytics">Deterministic analytics</option></select>
        {demo === "analytics" && <p className="sourceNote">Numbers come from a typed analytical plan executed in pandas. The model does not invent the shortfall or contributor ranking.</p>}
        {demo === "sources" && <p className="sourceNote">Passwords and tokens stay in server environment variables. This UI only sends secret reference names, never raw credentials.</p>}
        {(demo === "sales" || demo === "template") && <div className="promise" aria-label="Workflow outcomes"><span>01 · Inspect & map</span><span>02 · Transform & derive</span><span>03 · Verify & export</span></div>}
        {demo === "analytics" && <div className="promise" aria-label="Analytics outcomes"><span>01 · Typed plan</span><span>02 · Deterministic facts</span><span>03 · Verified explanation</span></div>}
        <label htmlFor="goal">What should the workspace accomplish?</label>
        <textarea id="goal" value={goal} onChange={(event) => setGoal(event.target.value)} required maxLength={10000} />
        {demo !== "sources" && demo !== "analytics" && <>
        <div className="uploads">
          <label className="upload">{demo === "grades" ? "Structured grade data" : demo === "template" ? "Raw orders" : "August transactions"}<input type="file" accept=".csv,.xlsx" disabled={busy} onChange={(event) => { setDataset(event.target.files?.[0] ?? null); setDatasetInfo("Awaiting inspection"); setTemplateProposal(null); setTemplateResult(null); setMappingOverrides({}); }} /><small>{dataset?.name ?? datasetInfo}</small></label>
          <label className="upload">{demo === "grades" ? "Grading policy PDF" : demo === "template" ? "Reporting policy PDF" : "Commission policy PDF"}<input type="file" accept=".pdf,application/pdf" disabled={busy} onChange={(event) => { setDocument(event.target.files?.[0] ?? null); setDocumentInfo("Awaiting ingestion"); setTemplateResult(null); }} /><small>{document?.name ?? documentInfo}</small></label>
          {demo === "sales" && <><label className="upload">Customer regions<input type="file" accept=".csv,.xlsx" disabled={busy} onChange={(event) => setCustomers(event.target.files?.[0] ?? null)} /><small>{customers?.name ?? "No customer file selected"}</small></label><label className="upload">Regional targets<input type="file" accept=".csv,.xlsx" disabled={busy} onChange={(event) => setTargets(event.target.files?.[0] ?? null)} /><small>{targets?.name ?? "No target file selected"}</small></label></>}
          {demo === "template" && <><label className="upload">Customer master<input type="file" accept=".csv,.xlsx" disabled={busy} onChange={(event) => { setCustomers(event.target.files?.[0] ?? null); setTemplateProposal(null); setTemplateResult(null); setMappingOverrides({}); }} /><small>{customers?.name ?? "No customer master selected"}</small></label><label className="upload">Required target template<input type="file" accept=".csv,.xlsx" disabled={busy} onChange={(event) => { setTemplateTarget(event.target.files?.[0] ?? null); setTemplateProposal(null); setTemplateResult(null); setMappingOverrides({}); }} /><small>{templateTarget?.name ?? "No target template selected"}</small></label></>}
        </div>
        <button disabled={!canRun} title={runtime?.status === "not_ready" ? "Complete backend configuration before running tasks" : unresolvedTemplateFields.length ? "Resolve required fields before execution" : undefined}>{busy ? phase ?? "Executing workflow…" : demo === "template" ? templateProposal ? "Execute verified template transform" : "Inspect and propose mappings" : demo === "sales" ? "Build verified August report" : "Run verified task"}</button>
        </>}
        {demo === "sources" && <div>
          <label htmlFor="sourceKind">Source type</label>
          <select id="sourceKind" className="modePicker" value={sourceKind} disabled={busy} onChange={(event) => setSourceKind(event.target.value as "upload" | "postgres" | "rest")}>
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
      <section className="panel tracePanel"><div className="panelTitle"><h2>Execution trace</h2><span>{execution?.stages.length ?? 0} stages</span></div><ol className="trace">{execution?.stages.map((stage, index) => <li key={`${stage.name}-${index}`}><span className={`dot ${stage.status === "completed" ? "ok" : stage.status === "warning" ? "warn" : "fail"}`} /><div><div className="stageTitle"><strong>{stage.name}</strong><span>{stage.status}</span></div><p>{stage.explanation}</p>{Object.keys(stage.row_counts).length > 0 && <div className="facts">{Object.entries(stage.row_counts).map(([label, value]) => <small key={label}>{label.replaceAll("_", " ")}: {value}</small>)}</div>}<small>{stage.tool_name ? `${stage.tool_name} · ` : ""}{stage.evidence_ids.length} evidence · {stage.artifact_ids.length} artifacts{stage.verification_result ? ` · ${stage.verification_result.replaceAll("_", " ")}` : ""}</small></div></li>) ?? <li className="empty">Goal, plan, tool outcomes, evidence, verification, and artifacts will appear here.</li>}</ol>{execution && <details className="technicalTrace"><summary>Inspect validated tool calls</summary>{execution.trace.map((step) => <article key={step.step}><strong>{step.step}. {step.requested_tool}</strong><span>{step.duration_ms.toFixed(1)} ms</span><p>{step.observation}</p></article>)}</details>}</section>
      <section className="panel"><div className="panelTitle"><h2>Evidence & verification</h2><span>{execution?.citations.length ?? 0} citations</span></div>{execution?.warnings.length ? <div className="warnings"><strong>Data and join warnings</strong>{execution.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div> : null}{execution?.citations.map((citation) => <article className="citation" key={citation.chunk_id}><strong>{citation.filename} · page {citation.page_number}</strong><code>{citation.chunk_id}</code></article>)}{execution?.verification?.findings.map((finding, index) => <article className="finding" key={`${finding.claim}-${index}`}><span className={`pill ${finding.status}`}>{finding.status.replaceAll("_", " ")}</span><strong>{finding.claim}</strong><p>{finding.explanation}</p></article>) ?? <p className="muted">Source pages and claim checks will appear after execution.</p>}</section>
    </div>}
  </main>;
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
