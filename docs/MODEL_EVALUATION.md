# Workspace Model Evaluation

This harness compares reasoning models on the decisions required by this product. It does not benchmark trivia, ask a model to calculate business results, or treat an offline fixture as model-quality evidence.

## What it evaluates

The versioned suite in `evals/model_cases.json` covers ten behaviors:

1. natural-language goal to typed plan;
2. correct deterministic tool selection;
3. valid structured arguments;
4. no invented resource identifiers;
5. ambiguity recognition;
6. missing-field clarification;
7. recovery after a controlled tool failure;
8. policy reasoning grounded in retrieved evidence;
9. refusal when evidence is insufficient; and
10. faithful explanation of deterministic `What Changed?` results without invented arithmetic or causes.

The runner simulates deterministic tools with fixed observations. Models select tools and explain results; they never perform the underlying calculations during evaluation.

## Offline contract evaluation

Run from `backend`:

```powershell
.\.venv\Scripts\python.exe -m app.evaluation.model_quality ..\evals\model_cases.json
```

This uses typed fixture decisions, requires no credential, and is the CI path. It verifies the runner, scenario contracts, scoring, failure detection, and report shape. A passing offline result is not evidence that any hosted model performs well.

## Opt-in hosted evaluation

Set a credential only in the process environment. `MODEL_EVAL_API_KEY` is preferred; `ORCHESTRATOR_API_KEY` and `OPENAI_API_KEY` are supported fallbacks.

```powershell
$env:MODEL_EVAL_API_KEY = "..."
.\.venv\Scripts\python.exe -m app.evaluation.model_quality ..\evals\model_cases.json `
  --mode live --provider openai `
  --model "MODEL_NAME" `
  --timeout-seconds 30 --max-retries 1 --max-output-tokens 1200 `
  --output ..\var\model-eval\hosted.json `
  --quiet --progress
```

The command does not require PostgreSQL. It uses the same strict OpenAI Responses adapter, timeout, retry, structured-output, and output-token boundaries as production orchestration. A custom base URL must be Responses-compatible; configuration does not imply compatibility.

Repeat `--model` to compare models in one report:

```powershell
.\.venv\Scripts\python.exe -m app.evaluation.model_quality ..\evals\model_cases.json `
  --mode live `
  --model "MODEL_A" `
  --model "MODEL_B"
```

No model is hard-coded as best. Each case records an explicit scenario name, task success, structured validity, tool sequence, invalid or hallucinated arguments, unnecessary calls, evidence faithfulness, uncertainty/refusal correctness, latency, provider token usage when returned, and a stable sanitized failure reason when the provider fails. Reports under `var/model-eval` are generated local evidence and are ignored by Git.

## Opt-in local Ollama evaluation

Install and start Ollama outside the application, then pull models explicitly. Application startup and offline tests never pull or run a model.

```powershell
ollama pull llama3.2:3b
ollama serve
cd backend
.\.venv\Scripts\python.exe -m app.evaluation.model_quality ..\evals\model_cases.json `
  --mode live --provider ollama --model llama3.2:3b `
  --timeout-seconds 60 --max-retries 1 `
  --max-output-tokens 512 --context-tokens 8192 `
  --output ..\var\ollama-eval\llama3.2-3b.json `
  --quiet --progress
```

The common first-round bound is 512 output tokens because the controlled strict decision envelopes are under 300 serialized characters; it leaves substantial allowance without permitting long generation. The 60-second timeout makes latency part of acceptance, while one retry distinguishes a transient local failure from a repeatable one. The 8,192-token context is explicit and bounded rather than inheriting Ollama's runtime default or advertised model maximum.

With `--output`, a single-model run atomically checkpoints after every completed case. The report and evaluation are marked `PARTIAL` until all cases are present, then `COMPLETE`. Resume the exact command after an interruption by adding `--resume`. A configuration fingerprint covers provider, exact model tag, temperature, output/context bounds, timeout, retries, suite version, case count, and case-file SHA-256. Resume fails rather than combining results when any value differs. An interrupted in-flight case is rerun; already checkpointed cases are skipped.

Use one report per model for resumable local runs. `--progress` prints only lines such as `case 3/10 passed: valid_structured_arguments`; `--quiet` suppresses the large final JSON on stdout. Reports under `var/ollama-eval` are local generated evidence and are ignored by Git. Summarize completed comparison evidence in reviewed documentation rather than committing transient logs or model caches.

### Local evidence collected on 2026-09-09

Provider support, runtime compatibility, hardware feasibility, and model quality are separate conclusions. A working adapter does not prove that a particular Ollama model can initialize schema-constrained generation, and a compatible model is not a quality winner until it completes the fixed product suite.

| Model | Provider/runtime compatibility | Hardware feasibility | Product-quality evidence |
| --- | --- | --- | --- |
| `llama3.2:3b` (approximately 2.0 GB) | The native adapter reached real local generation, but provider failures and timeouts occurred across the run. | It loaded for CPU inference at an observed footprint of approximately 2.5 GB; the completed evaluation used the fixed 8,192-token configuration. | All 10 cases completed; 0/10 passed, structured output validity was 0%, and median latency was approximately 120.01 seconds. It is operationally unsuitable on this CPU and configuration. |
| `gemma3:4b` (approximately 3.3 GB) | In this Ollama 0.20.0 installation, a controlled schema-format request returned HTTP 500 with `failed to load model vocabulary required for format`. Generation never began, so assistant JSON parsing and `ModelDecisionEnvelope` validation were never reached. This is an Ollama/Gemma structured-output runtime incompatibility in the tested installation. | The model loaded locally; the controlled failure was not a memory or timeout result. | The checkpoint says 0/10 because all cases ended in provider failure, but that is **not** a model-quality verdict. No generated decision reached the evaluator. |
| [`qwen3.5:9b`](https://ollama.com/library/qwen3.5:9b) (official artifact approximately 6.6 GB) | Not tested. | Not downloaded because only approximately 5.45 GiB physical RAM was available after unloading Gemma. The artifact alone exceeded that headroom before KV cache and runtime buffers, so CPU-only inference with the fixed 8,192-token context was not realistically feasible on this machine. | Not evaluated. |
| [`qwen3.5:4b`](https://ollama.com/library/qwen3.5:4b) (installed artifact 3.4 GB) | The one fixed-settings compatibility preflight loaded the model and reached active CPU execution, but returned no HTTP response within the 60-second timeout. Consequently no assistant content, JSON parse, or `ModelDecisionEnvelope` validation result was available. | Ollama reported a 5.9 GB loaded footprint, 100% CPU inference, and context 8192; available physical RAM fell from approximately 5.73 GiB to 1.11 GiB. | The 10-case benchmark was intentionally not launched because the preflight did not return a valid bounded decision. No model-quality score is claimed; it is operationally unsuitable for this workload on the tested CPU/runtime configuration. |

These results establish native provider execution and resumable evaluation, but they do not identify a recommended local default. Llama and Qwen were operationally unsuitable under the fixed CPU-only acceptance bounds, while Gemma could not initialize schema-constrained generation in the installed runtime. Qwen 3.5 4B remains the preferred *next candidate to evaluate* on suitable GPU-backed hardware because it fits the smaller artifact class; that is a test-priority decision, not a quality result or product default. A GPU-backed compatibility preflight and, only if it succeeds, the unchanged ten-case benchmark remain pending. Generated reports remain local and ignored: the reviewed conclusions above contain no prompts, response bodies, machine-specific paths, or secrets.

## Running the Ollama evaluation on a GPU machine

Install a current NVIDIA driver, confirm `nvidia-smi` works, and install Ollama plus this repository's backend dependencies. Choose an exact Ollama model tag based on the machine's available VRAM; the project does not select or download a default model.

In one terminal:

```powershell
$modelTag = "<exact-ollama-model-tag>"
ollama pull $modelTag
ollama serve
```

In a second terminal, from `backend`:

```powershell
nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used --format=csv
ollama --version
ollama ps

$modelTag = "<same-exact-ollama-model-tag>"
.\.venv\Scripts\python.exe -m app.evaluation.model_quality ..\evals\model_cases.json `
  --mode live --provider ollama --model $modelTag `
  --timeout-seconds 60 --max-retries 1 `
  --max-output-tokens 512 --context-tokens 8192 `
  --output ..\var\ollama-eval\gpu-candidate.json `
  --quiet --progress
```

Record the Git commit, exact model tag, Ollama version, `nvidia-smi` output, and `ollama ps` processor/context information with the generated report. The JSON report records scenario-level pass/fail results, structured-output validity, tool and grounding checks, latency, available token counts, provider/model identity, failure reasons, and a configuration fingerprint. Add `--resume` to the identical command after an interruption; it refuses a checkpoint whose model, settings, suite version, case count, or case-file hash differs.

Comparisons are valid only when the case file, suite version, model tag, temperature, output/context bounds, timeout, and retry count match. Keep generated reports under the ignored `var/ollama-eval` directory or archive them outside the repository; do not commit model weights or caches. A successful GPU run is evidence for that model, tag, hardware, runtime, and configuration only. It must not be presented as the product default or a winner without a reviewed comparison against the same fixed suite.

Approximate cost is omitted by default because prices change and may differ by endpoint. Supply both current operator-verified rates to calculate it:

```powershell
  --input-cost-per-million 1.25 --output-cost-per-million 10.00
```

The report labels those rates `operator_supplied`.

## Human model-quality judgment

Deterministic checks cannot decide whether an answer is clear or practically useful. Keep that assessment separate by supplying an optional JSON file:

```json
{
  "judgments": [
    {"case_id": "ambiguity_recognition", "score": 5, "notes": "Requests only the fields needed to continue."}
  ]
}
```

```powershell
  --judgments .\reviewed-model-judgments.json
```

Scores use a 1–5 rubric for semantic usefulness, clarity, and appropriate uncertainty. Partial reviews remain labeled partial. The harness never converts these judgments into a claim that a model is universally best.

## Security and interpretation boundaries

- API keys come only from environment variables and are not included in reports.
- Provider errors are reduced to stable error codes and sanitized reasons; response bodies and credential-bearing request details are not reported.
- Token counts and latency are non-sensitive aggregate metadata, not prompt or evidence content.
- Live calls are never automatic in tests or CI.
- Ollama endpoints are restricted to literal loopback URLs in V1; no API key or invented monetary rate is accepted for local evaluation.
- Local reports contain decision scores and aggregate runtime metadata, not prompt, observation, or response bodies.
- Controlled observations test model decisions, not database, retrieval, or deterministic calculation correctness; those have separate evaluation families.
