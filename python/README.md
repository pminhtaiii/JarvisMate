# LifeMate Python baseline

Implementation handoff for [feature 001](../specs/001-python-sample-pipeline/spec.md).
**Source and tests are authored; installation, tests, real-runtime checks and model
inference have not been run by the author, at the user's request.** The pinned optional
dependency combination also awaits validation on the receiving machine. This is not
a measured baseline, a validation score, or a submission-ready container.

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
| `cli.py` | Preflight, sequential model reuse, stop-on-first-failure orchestration |

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
real-data test skips unless explicitly enabled. No test pass is claimed in this handoff.

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

## Integration entry point (separate from `run`)

`python -m lifemate.integration` ([spec](../specs/002-docker-integration/spec.md),
[ADR 011](../docs/adr/011-configurable-docker-integration.md)) is configured by strict
TOML ([example](../configs/integration.example.toml)) and runs audio -> per-clip ASR
once -> native Qwen tool calling (`qwen-native-v1`) -> one ToolEnv per sample, inside a
supervised persistent worker. `run` keeps its defaults for comparison.

| Module | Responsibility |
|---|---|
| `configuration.py` | TOML v1 schema, CLI overrides, metadata-only snapshot/template/parameter/data preflight, run identity |
| `adapters/qwen_native.py` | Native render/parse, optional structured skill guidance, EOS/limit classification, LMFE constraint, template check, local planner |
| `worker.py` | Spawned worker: models loaded once, framed IPC, durable per-attempt staging |
| `supervisor.py` | Reservation before dispatch, full-attempt deadline, termination/quarantine, bounded recovery |
| `integration.py` | CLI, batch coordination, manifest/provenance, exact-coverage publication |
| `diagnostics.py` | Offline Train-reference empty/clarification report and paired transcript/audio attribution |

```powershell
$env:PYTHONPATH = 'python/src;python/tests'
python -m unittest discover -s python/tests -p 'test_integration*.py'
python -m unittest python/tests/test_qwen_native.py python/tests/test_asr_once.py
python -m lifemate.integration --config /abs/config/integration.toml --check-config
```

Status: controlled checks only (see the
[recorded evidence](../specs/002-docker-integration/quickstart.md#recorded-evidence)).
The Docker image, GPU runs, real checkpoints and latency are pending on the GPU server
via `scripts/integration/server-acceptance.sh`.

Integration supports a soft stop (default 28 seconds) inside the supervisor's hard
budget (at most 30 seconds), starting before dispatch and including ASR. Set
`execution.soft_timeout_seconds` with `0 < soft_timeout_seconds < timeout_seconds <= 30`.
Only safe boundaries with an initialized ToolEnv can return `partial`; output always
comes from its official log/hash getters. `completed`, `needs_info`, `partial`,
`timeout` and `failed` remain distinct in the journal and reports. Accepted partials
permit complete coverage publication; `manifest.report.partial` counts them, and
coverage does not imply correctness. See the [runtime contract](../specs/002-docker-integration/contracts/runtime.md)
for acceptance ordering, generation/tool blocking and crash limitations.

Exhausting the native agent's 16 decision steps also returns an authoritative
`partial`, with `stop_reason="step_limit"`; a soft stop uses `"soft_deadline"`.
No extra planner turn or tool call is made to finish. Finish or valid clarification
at step 16 retains `completed` or `needs_info`; hard expiry and execution/state errors
retain timeout/failure handling. Metrics and traces carry the stop reason, and
manifest/diagnostics reports separate counts under `partial_stop_reasons`.
Explicit soft budgets (including 26 seconds) are respected; omitting the setting uses 28.

Optional `execution.reuse_kv_cache = false` preserves full-prefill decisions by
default. Setting it to `true` enables per-sample exact-token prefix reuse for the
pinned Qwen3 stack. See [KV reuse and paired smoke16 benchmark](../docs/kv-cache.md)
for cache safety, measured metrics, CPU evidence and UIT Slurm commands. H200 speed
and output equivalence must be measured before promotion; no speedup is assumed.

Setting optional `execution.enable_skill_retrieval = true` enables the offline,
deterministic CPU Skill Library for the native integration path; the default is false.
It retrieves once after ASR using
the request, conversation history and this sample's eligible tool names. Matching
guidance appears in a structured `skill_guidance` field; all native eligible tool
schemas remain available and the planner still chooses each call. With the flag off,
the effective config omits the false default, preserving the previous prompt and
configuration fingerprint. Full run identity still includes current code provenance,
so it changes with this source revision. Enabled runs also bind the library version
and SHA-256 into run identity, so a resume with different skill metadata is rejected.
Guidance is trimmed once, before
planning, to fit the initial prompt plus output reservation, then stays fixed across
planner steps. It reduces the context left for later tool observations, which can
still reach the existing `CONTEXT_LIMIT`; context, step, soft-timeout and hard-timeout
limits are not raised. The library currently exposes only E-evidence branches to
runtime retrieval; S branches remain gated and H branches are never retrieved. This
is controlled behavior, not an accuracy or latency result.

For a branch with `required_data_missing` readers, each reader list is an OR choice;
`optional_detail_missing` readers never gate the action path. If a required reader is
unavailable, retrieval keeps the branch only when that reader's declared
`input_alternatives`, the required action fields, or both have explicit concrete values
in the request or relevant user history (for example `email_id=MAIL-123`,
`subscription_id=SUB-123` or `booking_id: BK-123`), or `sys.ask_missing_info` is
eligible. Bare numbers, guessed IDs and fuzzy matches do not count. When required
action fields are explicit, guarded readers are omitted from guidance;
always-before-action dependencies remain mandatory. The missing-info tool does not
make an unavailable app action eligible.

For a three-sample UIT smoke, use a separate checkout of the new branch and the
existing inference interpreter. Set `PY` to that interpreter and `BASE_CONFIG` to
the existing TOML (read only). This makes fresh config, selection and output paths,
preserving all model/ASR/decoding settings. Run only when a GPU is available for this
smoke; these commands do not schedule a Slurm job or modify a running job.

```bash
# From the new branch's separate checkout; replace these two deployment paths.
PY=/absolute/existing-inference-env/bin/python
BASE_CONFIG=/absolute/existing-config/integration.toml
export PYTHONPATH="$PWD/python/src"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
SMOKE_ROOT=$(mktemp -d "$HOME/lifemate-smoke3.XXXXXXXX")
"$PY" - "$BASE_CONFIG" "$SMOKE_ROOT" <<'PY'
import itertools, json, sys
from pathlib import Path
from lifemate.configuration import load_config, selected_ids

config = load_config(Path(sys.argv[1]))
root = Path(sys.argv[2])
assert config.mode == "audio", "Use the existing audio inference config"
ids = list(selected_ids(config))[:3]
if config.select_all:
    visible = config.data_root / config.split / f"{config.split}.jsonl"
    with visible.open(encoding="utf-8") as stream:
        ids = [json.loads(line)["id"] for line in itertools.islice((s for s in stream if s.strip()), 3)]
assert len(ids) == 3, "Need exactly three selected samples"
(root / "selection.txt").write_text("\n".join(ids) + "\n", encoding="utf-8")
value = config.record()  # Validated absolute paths retain the original inputs.
value.pop("schema_version")
value["execution"].update(timeout_seconds=30, soft_timeout_seconds=28)
value["data"].update(select_all=False, sample_ids_file=str(root / "selection.txt"))
value["output"]["root"] = str(root / "run")
def toml(v):
    return str(v).lower() if isinstance(v, bool) else json.dumps(v)
text = "schema_version = 1\n" + "".join(
    f"\n[{section}]\n" + "".join(f"{k} = {toml(v)}\n" for k, v in table.items())
    for section, table in value.items())
(root / "smoke3.toml").write_text(text, encoding="utf-8")
print("Selected:", ids, "Artifacts:", root)
PY
"$PY" -m lifemate.integration --config "$SMOKE_ROOT/smoke3.toml" --check-config &&
"$PY" -m lifemate.integration --config "$SMOKE_ROOT/smoke3.toml"
```

Inspect the manifest's status counts and each sample's trace/outcome. An ordinary
three-sample model smoke may contain no partials; controlled tests establish soft
boundary behavior. This command has not been run on UIT as part of this change.

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
[validation.md](../specs/001-python-sample-pipeline/validation.md). The
[task ledger](../specs/001-python-sample-pipeline/tasks.md) distinguishes delivered
implementation from unexecuted acceptance gates. Follow the [roadmap](../context/roadmap.md) for Train
Validation/error analysis.

## Planner SFT baseline

`python -m lifemate.sft {preflight,prepare,train,export,diagnose} --config <toml>` runs one
fixed NF4 plus LoRA recipe on a GPU host ([ADR 012](../docs/adr/012-native-planner-sft-baseline.md)).
Install `.[inference,training]` there, never in the Docker image. Start from
`configs/planner-sft.example.toml`, and follow the
[quickstart](../specs/003-planner-sft-baseline/quickstart.md), which records what has and has not been run.
