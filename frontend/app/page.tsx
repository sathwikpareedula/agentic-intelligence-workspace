"use client";

import { FormEvent, useState } from "react";

type TraceStep = { step: number; requested_tool: string; success: boolean; observation: string; duration_ms: number; source_ids: string[]; artifact_ids: string[] };
type Execution = { task_id: string; status: string; answer?: string; failure_reason?: string; trace: TraceStep[]; verification?: { status: string; findings: { claim: string; status: string; explanation: string }[] } };

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function WorkspacePage() {
  const [goal, setGoal] = useState("According to the grading policy, what score do I need on my final to finish with an A?");
  const [dataset, setDataset] = useState<File | null>(null);
  const [document, setDocument] = useState<File | null>(null);
  const [datasetInfo, setDatasetInfo] = useState<string>("No dataset inspected");
  const [documentInfo, setDocumentInfo] = useState<string>("No document ingested");
  const [execution, setExecution] = useState<Execution | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function uploadDataset() {
    if (!dataset) return;
    const body = new FormData(); body.append("file", dataset);
    const response = await fetch(`${API}/datasets/inspect`, { method: "POST", body });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail ?? "Dataset inspection failed");
    setDatasetInfo(`${result.filename} · ${result.row_count} rows · ${result.column_count} columns`);
  }

  async function uploadDocument() {
    if (!document) return;
    const body = new FormData(); body.append("file", document);
    const response = await fetch(`${API}/documents`, { method: "POST", body });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail ?? "Document ingestion failed");
    setDocumentInfo(`${result.filename} · ${result.page_count} pages · ${result.chunk_count} evidence chunks`);
  }

  async function runTask(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(null); setExecution(null);
    try {
      await Promise.all([uploadDataset(), uploadDocument()]);
      const response = await fetch(`${API}/agent/tasks`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ goal }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? "Task execution failed");
      setExecution(result);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Unexpected error"); }
    finally { setBusy(false); }
  }

  return <main>
    <header><div><p className="eyebrow">TRUSTWORTHY DATA + KNOWLEDGE</p><h1>Agentic Intelligence Workspace</h1><p className="lede">Turn a goal, data, and source documents into a traceable result you can inspect and rerun.</p></div><span className="status">Local workspace</span></header>
    <form onSubmit={runTask}>
      <section className="composer">
        <label htmlFor="goal">What should the workspace accomplish?</label>
        <textarea id="goal" value={goal} onChange={(event) => setGoal(event.target.value)} required />
        <div className="uploads">
          <label className="upload">Structured data<input type="file" accept=".csv,.xlsx" onChange={(event) => setDataset(event.target.files?.[0] ?? null)} /><small>{dataset?.name ?? datasetInfo}</small></label>
          <label className="upload">Source document<input type="file" accept=".pdf" onChange={(event) => setDocument(event.target.files?.[0] ?? null)} /><small>{document?.name ?? documentInfo}</small></label>
        </div>
        <button disabled={busy}>{busy ? "Executing verified workflow…" : "Run task"}</button>
        {error && <p className="error" role="alert">{error}</p>}
      </section>
    </form>
    <div className="results">
      <section className="panel answer"><div className="panelTitle"><h2>Answer</h2><span className={`pill ${execution?.verification?.status ?? "idle"}`}>{execution?.verification?.status ?? "Awaiting task"}</span></div><p>{execution?.answer ?? "Your grounded answer will appear here after deterministic tools finish."}</p>{execution?.failure_reason && <p className="error">{execution.failure_reason}</p>}</section>
      <section className="panel"><div className="panelTitle"><h2>Execution trace</h2><span>{execution?.trace.length ?? 0} steps</span></div><ol className="trace">{execution?.trace.map((step) => <li key={step.step}><span className={step.success ? "dot ok" : "dot fail"} /><div><strong>{step.requested_tool}</strong><p>{step.observation}</p><small>{step.duration_ms.toFixed(1)} ms · {step.source_ids.length} sources · {step.artifact_ids.length} artifacts</small></div></li>) ?? <li className="empty">Tool calls, results, evidence, and timing remain visible here.</li>}</ol></section>
      <section className="panel"><div className="panelTitle"><h2>Evidence & verification</h2></div>{execution?.verification?.findings.map((finding, index) => <article className="finding" key={index}><span className={`pill ${finding.status}`}>{finding.status}</span><strong>{finding.claim}</strong><p>{finding.explanation}</p></article>) ?? <p className="muted">Citations and claim checks will appear after execution.</p>}</section>
    </div>
  </main>;
}
