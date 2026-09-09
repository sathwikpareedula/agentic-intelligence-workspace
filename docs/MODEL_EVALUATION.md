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

## Opt-in live evaluation

Set a credential only in the process environment. `MODEL_EVAL_API_KEY` is preferred; `ORCHESTRATOR_API_KEY` and `OPENAI_API_KEY` are supported fallbacks.

```powershell
$env:MODEL_EVAL_API_KEY = "..."
.\.venv\Scripts\python.exe -m app.evaluation.model_quality ..\evals\model_cases.json `
  --mode live `
  --model "MODEL_NAME" `
  --output ..\var\model-eval.json
```

The command does not require PostgreSQL. It uses the same strict OpenAI Responses adapter, timeout, retry, structured-output, and output-token boundaries as production orchestration. Optional flags are `--base-url`, `--timeout-seconds`, `--max-retries`, and `--max-output-tokens`. A custom base URL must be Responses-compatible; configuration does not imply compatibility.

Repeat `--model` to compare models in one report:

```powershell
.\.venv\Scripts\python.exe -m app.evaluation.model_quality ..\evals\model_cases.json `
  --mode live `
  --model "MODEL_A" `
  --model "MODEL_B"
```

No model is hard-coded as best. Each result records task success, structured validity, tool sequence, invalid or hallucinated arguments, unnecessary calls, evidence faithfulness, uncertainty/refusal correctness, latency, and provider token usage when returned.

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
- Provider errors are reduced to stable error codes; response bodies and credential-bearing request details are not reported.
- Token counts and latency are non-sensitive aggregate metadata, not prompt or evidence content.
- Live calls are never automatic in tests or CI.
- Controlled observations test model decisions, not database, retrieval, or deterministic calculation correctness; those have separate evaluation families.
