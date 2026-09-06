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
  const [demo, setDemo] = useState<"grades" | "sales">("sales");
  const [goal, setGoal] = useState("Prepare the August sales report. Clean transactions, compare regional targets, identify the largest shortfalls, calculate policy-based commissions, and export a management workbook while preserving the originals.");
  const [dataset, setDataset] = useState<File | null>(null);
  const [document, setDocument] = useState<File | null>(null);
  const [customers, setCustomers] = useState<File | null>(null);
  const [targets, setTargets] = useState<File | null>(null);
  const [datasetInfo, setDatasetInfo] = useState("No dataset selected");
  const [documentInfo, setDocumentInfo] = useState("No document selected");
  const [execution, setExecution] = useState<Execution | null>(null);
  const [runtime, setRuntime] = useState<Runtime | null>(null);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    if (busy || !dataset || !document || (demo === "sales" && (!customers || !targets)) || !goal.trim() || runtime?.status !== "ready") return;
    setBusy(true);
    setError(null);
    setExecution(null);
    try {
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

  const hasInputs = Boolean(dataset && document && (demo === "grades" || (customers && targets)));
  const canRun = Boolean(hasInputs && goal.trim() && runtime?.status === "ready" && !busy);
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
          const next = event.target.value as "grades" | "sales";
          setDemo(next);
          setGoal(next === "grades"
            ? "According to the grading policy, what score do I need on my final to finish with an A?"
            : "Prepare the August sales report. Clean the transaction data, compare performance against targets by region, identify the largest drivers of underperformance, calculate salesperson commissions according to the policy, generate appropriate charts, and export a management workbook while preserving the original data.");
          setDataset(null); setDocument(null); setCustomers(null); setTargets(null); setExecution(null);
          setDatasetInfo("No dataset selected"); setDocumentInfo("No document selected");
        }}><option value="grades">Grades + syllabus</option><option value="sales">August sales report</option></select>
        {demo === "sales" && <div className="promise" aria-label="North-star workflow outcomes"><span>01 · Inspect & clean</span><span>02 · Retrieve & calculate</span><span>03 · Verify & export</span></div>}
        <label htmlFor="goal">What should the workspace accomplish?</label>
        <textarea id="goal" value={goal} onChange={(event) => setGoal(event.target.value)} required maxLength={10000} />
        <div className="uploads">
          <label className="upload">{demo === "grades" ? "Structured grade data" : "August transactions"}<input type="file" accept=".csv,.xlsx" disabled={busy} onChange={(event) => { setDataset(event.target.files?.[0] ?? null); setDatasetInfo("Awaiting inspection"); }} /><small>{dataset?.name ?? datasetInfo}</small></label>
          <label className="upload">{demo === "grades" ? "Grading policy PDF" : "Commission policy PDF"}<input type="file" accept=".pdf,application/pdf" disabled={busy} onChange={(event) => { setDocument(event.target.files?.[0] ?? null); setDocumentInfo("Awaiting ingestion"); }} /><small>{document?.name ?? documentInfo}</small></label>
          {demo === "sales" && <><label className="upload">Customer regions<input type="file" accept=".csv,.xlsx" disabled={busy} onChange={(event) => setCustomers(event.target.files?.[0] ?? null)} /><small>{customers?.name ?? "No customer file selected"}</small></label><label className="upload">Regional targets<input type="file" accept=".csv,.xlsx" disabled={busy} onChange={(event) => setTargets(event.target.files?.[0] ?? null)} /><small>{targets?.name ?? "No target file selected"}</small></label></>}
        </div>
        <button disabled={!canRun} title={runtime?.status === "not_ready" ? "Complete backend configuration before running tasks" : undefined}>{busy ? phase ?? "Executing workflow…" : demo === "sales" ? "Build verified August report" : "Run verified task"}</button>
        {busy && <p className="progress" role="status" aria-live="polite"><span />{phase ?? "Executing bounded workflow"}. Source uploads remain unchanged.</p>}
        {!hasInputs ? <p className="hint">Select all required sample inputs to enable the task.</p> : null}
        {error && <p className="error" role="alert">{error}</p>}
      </section>
    </form>
    <div className="results">
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
    </div>
  </main>;
}
