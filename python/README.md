# LifeMate Python baseline

Implementation handoff for [feature 001](../specs/001-python-sample-pipeline/spec.md),
extended by [feature 002](../specs/002-measurement-prompt-experiments/spec.md) (timing,
offline reports, opt-in prompt profiles). **Package installation, real-runtime checks
and model inference have not been run by the author, at the user's request.** The
controlled unittest suite was run directly against `python/src` (no package install) on
2026-10-30; see [feature 002 validation](../specs/002-measurement-prompt-experiments/validation.md)
for the exact command and outcome. The pinned optional dependency combination still
awaits validation on the receiving machine. This is not a measured baseline, a
validation score, or a submission-ready container.

## Architecture

```text
CLI -> dataset/runtime preflight -> load models once
  -> for each selected sample, in dataset order:
       trace/deadline -> transcript or current/history ASR -> one ToolEnv
       -> Qwen action -> shape/eligibility check -> env.call -> observation -> Qwen
       -> finish / successful waiting_for_user -> authoritative call log + hash
       -> terminal trace -> flushed partial prediction -> manifest progress
  -> validate exact selection coverage -> publish predictions.jsonl
```

Python owns complete sample execution. No TypeScript transport, HTTP service, training,
custom scorer, full-container supervisor, or Docker submission is added here.

| Module | Responsibility |
|---|---|
| `contracts.py` | Configuration/bounds, protocols, failure codes and outcomes |
| `jsonio.py`, `dataset.py` | Strict visible JSON, input whitelist, contained selected assets, ordered user-turn preparation |
| `runtime.py` | Trusted split package import, matching catalogs, implementation coverage, one-open factory |
| `prompting.py`, `agent.py` | Versioned Vietnamese structured ReAct prompt, strict action grammar, bounded dispatch |
| `adapters/planner.py` | Local Qwen3 tokenizer/model, greedy actions, token and time budgets |
| `adapters/asr.py` | Local Whisper/PhoWhisper Vietnamese transcription from PCM WAV, no text fallback |
| `artifacts.py` | Durable exact predictions, bounded/redacted debug traces, manifest/publication lifecycle |
| `cli.py` | Preflight, sequential model reuse, stop-on-first-failure orchestration, `report`/`compare-runs`/`audit-examples` |
| `metrics.py` | Injectable monotonic clock, nested spans, per-generation token/role telemetry |
| `reporting.py` | Offline manifest reader (spans/generations from `measurements`, never `traces/*.jsonl`), nearest-rank distributions, single-factor comparison |
| `prompt_profiles.py`, `example_audit.py` | Baseline/precise-v1 profile identity, fit-only bundle/partition validation |

## Install on the receiving machine

Use Python 3.11+; inference pins are intended for a compatible Python/PyTorch host.
The root Node/pnpm project remains independent. Run commands from the repo root.

PowerShell:

```powershell
python -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -e ./python
& ./.venv/Scripts/python.exe -m unittest discover -s python/tests -p 'test_*.py'
```

Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e ./python
.venv/bin/python -m unittest discover -s python/tests -p 'test_*.py'
```

Ordinary tests use standard-library controlled adapters and synthetic visible records;
they need no GPU, downloaded weights, or competition environment contents. Controlled
responses are test-only injection points, not a production CLI backend. The separate
real-data test (`test_real_samples.py`) skips unless its `LIFEMATE_REAL_*` environment
variables are set; it was not run here. The controlled suite (213 tests across
`test_metrics.py`, `test_reporting.py`, `test_prompt_profiles.py`, `test_agent.py`,
`test_artifacts.py`, `test_cli.py`, `test_checkpoint.py`, `test_dataset.py`,
`test_runtime.py`, `test_selection.py`, `test_audio.py`, `test_inference.py`) was run
directly against `python/src` with `PYTHONPATH` set, Python 3.13.1 on
Windows-11-10.0.26200, revision `baa4f4b`, and passed; see
[feature 002 validation](../specs/002-measurement-prompt-experiments/validation.md) for
the exact command and per-file results. This is a controlled-check pass only, not a
package-install, model, or real-runtime result.

## Measurement, reports and prompt profiles

`lifemate run` always records nested spans (environment/planner/tool/ASR boundaries,
per-generation token/role telemetry where the adapter supports it) and the full CLI
attempt time in the manifest/trace; legacy elapsed fields stay populated unchanged.
Three additional offline commands, and three `run` options, implement
[feature 002](../specs/002-measurement-prompt-experiments/spec.md):

- `lifemate report --run-dir DIR [--evaluation-file PATH]` reads a run's `manifest.json`
  only — each sample's nested spans/generations, not the separate `traces/*.jsonl`
  files — (no models, no ToolEnv) and writes `report.json`/`report.md` beside it: coverage,
  missing/failed/imported counts, nearest-rank stage/latency distributions, weighted
  token rates, and `not_evaluated` correctness unless a separate evaluation file is given.
- `lifemate compare-runs --baseline-run DIR --candidate-run DIR --factor
  {harness,instructions,few-shot} --output-dir DIR [--baseline-evaluation PATH]
  [--candidate-evaluation PATH]` validates the two runs share every identity field
  except the named factor, pairs sample IDs, and classifies the single-factor delta;
  it refuses to write into either source run.
- `lifemate audit-examples --bundle PATH --partition-manifest PATH --train-jsonl PATH
  --catalog PATH --output PATH` verifies a few-shot bundle's source prefixes/targets
  against the frozen fit partition only, before inference ever sees it.
- `run` adds `--prompt-profile {baseline,precise-v1}` (default `baseline`, exact
  legacy rendering unchanged), and `--few-shot-bundle PATH --partition-manifest PATH
  --few-shot-token-budget N` to attach an already-audited, fit-only demonstration
  bundle under an enforced token budget.

These commands are offline/deterministic and were exercised by the controlled suite
above (fixtures only); no real run, report, or comparison has been produced from actual
model output. See [contracts/measurement.md](../specs/002-measurement-prompt-experiments/contracts/measurement.md),
[contracts/prompts.md](../specs/002-measurement-prompt-experiments/contracts/prompts.md), and
[contracts/experiments.md](../specs/002-measurement-prompt-experiments/contracts/experiments.md)
for exact schemas, bounds, and acceptance classifications.

For real inference, install `./python[inference]` during environment preparation.
Pins are PyTorch `2.9.0`, Transformers `4.57.1`, NumPy `2.3.4`. Select the matching
PyTorch wheel/driver for the receiving GPU and record the actual resolved packages.
Prepare complete local snapshots separately, before offline execution:

- Planner candidate: `Qwen/Qwen3-4B-Instruct-2507`.
- ASR candidates in separate runs: `openai/whisper-small`, `vinai/PhoWhisper-small`.

Verify licenses/release eligibility. Record immutable publisher revisions and weight
checksums with the handoff experiment; model config hashes in the manifest do not
by themselves fingerprint every weight file. Missing local assets/dependencies or
an unavailable requested device fail; the runner never substitutes a remote service.

## Data layout and preflight

The data root directly contains `train/` and/or `public_test/`. Each selected split
requires its JSONL, matching catalog at the official split path, and environment paths.
Audio mode additionally requires every selected current/history-user WAV. Transcript
mode is Train-only and does not require WAVs. Audio paths must still be safe.

```text
DATA_ROOT/
  train/train.jsonl
  train/train_tools_catalog.json
  train/audio/<id>/<id>.wav
  train/audio/<id>/<id>_u1.wav
  train/train_environment/<id>/state.json
```

Use `tools/train` for Train and `tools/test` for public_test, or an official
`<split>/zaic_tools` package. The loader checks catalog equality and selected tool
coverage, not just app prefixes. Missing catalogs must not trigger the organizer's
permissive missing-catalog fallback.

In the original workspace, from `JarvisMate/`, the complete data root is
`../train+public_test/train+public_test`; change it for the receiving host. The four
smoke IDs are `train_1748`, `train_1749`, `train_1750`, `train_1751`. Do not infer all
IDs from numeric suffixes. `--id` may repeat for different IDs; `--all` is explicit.
All selection output follows dataset order, irrespective of command-line ID order.

```powershell
$dataRoot = (Resolve-Path '../train+public_test/train+public_test').Path
& ./.venv/Scripts/python.exe -m lifemate check-data --data-root $dataRoot --runtime-dir tools/train --split train --input-mode transcript --id train_1748
& ./.venv/Scripts/python.exe -m lifemate check-data --data-root $dataRoot --runtime-dir tools/train --split train --input-mode audio --id train_1748 --id train_1749 --id train_1750 --id train_1751
```

`check-data` imports trusted runtime source but loads no weights or ToolEnv. It checks
hidden-state **existence only**. Neither pipeline nor tests copy/parse organizer state
files. If an older upload has `train_enviroment`, the correctly spelled path is missing:
prepare the contained alias described in the [original quickstart](../specs/001-python-sample-pipeline/quickstart.md)
only when needed; never replace a correct layout or copy hidden files.

## Optional real-runtime smoke (no model)

This is execution against the actual supplied simulator; run it only on the receiving
machine after model-free tests/preflight. It uses a controlled planner and one allowed
read call; it does not establish model accuracy.

```powershell
$env:LIFEMATE_REAL_DATA_ROOT = $dataRoot
$env:LIFEMATE_REAL_SAMPLE_ID = 'train_1748'
$env:LIFEMATE_RUNTIME_DIR = (Resolve-Path 'tools/train').Path
& ./.venv/Scripts/python.exe -m unittest discover -s python/tests -p 'test_real_samples.py'
Remove-Item Env:LIFEMATE_REAL_DATA_ROOT,Env:LIFEMATE_REAL_SAMPLE_ID,Env:LIFEMATE_RUNTIME_DIR
```

## Real-model checkpoints

Use fresh run directories. Model initialization is timed separately; per-sample timing
starts before user-turn preparation, including ASR and tool/result collection.
The default is 16 planner decisions and 30 seconds. An explicit longer development
deadline is recorded and does not establish competition compliance.

```powershell
& ./.venv/Scripts/python.exe -m pip install -e './python[inference]'
& ./.venv/Scripts/python.exe -m lifemate run --data-root $dataRoot --runtime-dir tools/train --split train --input-mode transcript --id train_1748 --planner-model .agent-work/models/qwen3-4b-instruct-2507 --device cuda --trace-payloads --sample-timeout-seconds 120 --run-dir .agent-work/lifemate-runs/train-1748-text
```

Then repeat the transcript run with all four explicit `--id` arguments and a new
run directory. For audio comparison, use the same planner/IDs:

```powershell
& ./.venv/Scripts/python.exe -m lifemate run --data-root $dataRoot --runtime-dir tools/train --split train --input-mode audio --id train_1748 --id train_1749 --id train_1750 --id train_1751 --planner-model .agent-work/models/qwen3-4b-instruct-2507 --asr-model .agent-work/models/phowhisper-small --device cuda --trace-payloads --sample-timeout-seconds 120 --run-dir .agent-work/lifemate-runs/four-train-phowhisper
```

Run Whisper-small separately by changing only the ASR path and fresh run directory.
ASR supports nonempty mono 16-kHz 16-bit PCM WAVs up to 30 seconds, transcribing
historical users before the current user; it never falls back to supplied transcripts.
Both adapters load local files only, disable remote code, seed deterministically and
use greedy decoding. The planner enforces prompt plus output reservation <=16,384
tokens. Record actual repeatability rather than assuming deterministic settings suffice.

Planner <5B, selected ASR <1B (this baseline adapter's conservative guard), and total
deployed parameters <6B are enforced from loaded model counts. The actual competition
constraints apply to the whole deployed system. Loading occurs before these measured
counts are available; provision adequate memory for the intended small checkpoints.

## Outputs, errors and review

```text
<run-dir>/
  manifest.json
  predictions.partial.jsonl   # completed rows retained if a later sample fails
  predictions.jsonl           # published after complete selected coverage
  traces/<sample-id>.jsonl
```

Require the manifest to say `completed` as well as the final prediction file. Never
overwrite/resume a run or automatically recreate an environment. A failed run has no
successful placeholder for its failed sample. Exact authoritative arguments/hash
are preserved in prediction rows; trace truncation/redaction does not change them.

Routine stdout is one JSON command summary; diagnostics are on stderr. Prediction
rows contain exactly `id`, `tool_calls`, `state_hash`. Trace metadata is always enabled;
`--trace-payloads` explicitly enables sanitized dataset-debug text/actions/results.
Metadata-only traces are insufficient for detailed baseline acceptance. Event/total
trace limits are 64 KiB / 8 MiB, reserving space for failure metadata.

Malformed/unavailable model actions receive correction feedback without env calls.
Well-formed allowed calls with schema-invalid arguments reach `env.call` and remain
in the submission log. `ok:false`, `done:false`, and empty searches are observations,
not automatic execution failures. A successful `sys.ask_missing_info` stops only when
`waiting_for_user` is exactly true. Uncertain exceptions are never automatically retried.

Exit codes: `0` selected work complete; `2` argument/input/preflight error;
`1` model/execution/artifact failure. A fresh directory is required after failure.
Synchronous native/GPU/tool calls cannot be forcibly interrupted by this CLI;
deadline overruns are detected on return, and generation has stopping criteria.
A final container still needs process supervision, organizer failure-output policy,
offline/replay validation, A30 timing and full-split coverage checks.

Record receiving-machine commands, outcomes, package/model identities and evidence in
[validation.md](../specs/001-python-sample-pipeline/validation.md) for the baseline and
[validation.md](../specs/002-measurement-prompt-experiments/validation.md) for
measurement/prompt-profile acceptance. The task ledgers
([001](../specs/001-python-sample-pipeline/tasks.md),
[002](../specs/002-measurement-prompt-experiments/tasks.md)) distinguish delivered
implementation from unexecuted acceptance gates. Follow the [roadmap](../context/roadmap.md) for Train
Validation/error analysis; conditional SFT remains design-only.
