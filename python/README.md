# LifeMate Python baseline

Pretrained ASR comparison has a separate CLI under
[`asr/pretrained/`](../asr/pretrained/README.md), including Windows CPU setup,
explicit model preparation, seed-42 grouped manifests and benchmark commands.
It does not change the baseline CLI below.

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
       -> Qwen action -> shape/eligibility -> normalize/ID evidence -> env.validate
       -> env.call -> observation -> Qwen
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
| `arguments.py`, `numbers.py`, `temporal.py` | Schema-directed Vietnamese numbers/time, visible ID evidence, no transcript mutation |
| `prompting.py`, `agent.py` | Versioned Vietnamese structured ReAct prompt, strict action grammar, bounded dispatch |
| `adapters/planner.py` | Local Qwen3 tokenizer/model, greedy actions, token and time budgets |
| `adapters/asr.py` | Local Whisper/PhoWhisper Vietnamese transcription from PCM WAV, no text fallback |
| `artifacts.py` | Durable exact predictions, bounded/redacted debug traces, manifest/publication lifecycle |
| `cli.py` | Preflight, sequential model reuse, stop-on-first-failure orchestration |

## Deterministic arguments (2026-10-31)

The runner preserves ASR/history text. Numeric and temporal tool fields alone accept
Vietnamese expressions, normalized before organizer `env.validate`; rejection returns
bounded planner feedback with zero `env.call`. Every actual dispatched call, including
any subsequent runtime rejection, remains in the authoritative log. The proposal
grammar allows numeric strings; tool catalog schemas remain unchanged.

- Numbers: Vietnamese hundreds/tens, nghìn/ngàn/triệu/tỷ, phẩy, negative values,
  scale + rưỡi. Money `amount` uses Vietnamese dot grouping and may end in đồng/VND;
  single separators in other numeric fields are interpreted using field type.
  Explicit durations convert to fields ending in minutes/seconds/hours; temperature
  accepts độ/độ C. Fractional values in integer fields are rejected, never rounded.
- Dates: full dd/mm/yyyy -> YYYY-MM-DD; hôm nay/mai/kia/hôm qua; explicit weekday
  tới (strictly next occurrence) or tuần sau (next Monday-based week).
- Datetimes: explicit date + HH:mm[:ss] or spoken clock with day period; e.g.
  `ba giờ chiều mai`. `sau ... phút/giờ/ngày` uses sample time, never system time.
  New datetimes have seconds and timezone offset. Valid aware ISO literals and
  HH:mm[:ss] precision are preserved. Date-only input never invents a clock.
- Timezone uses IANA ZoneInfo. Without a database on Windows, modern Vietnam and
  UTC have explicit fixed-offset fallbacks; unsupported zones, DST folds/gaps,
  incomplete dates, ambiguous spoken hours and unknown grammar reject the proposal.
- Strings such as phone/account identifiers, names, message content, enums and x-ref
  values are not numerically rewritten. x-ref values require a structured visible ID
  from context, successful history results or successful results of the referenced app.
  This checks evidence, not semantic entity selection or continued existence.

On rejection the planner may correct its proposal or ask for missing required info.
Rules do not infer a missing currency/unit, recover leading zeros from a numeric phone
value, or claim complete Vietnamese-language coverage. Prompt v6 and the argument-policy
version are recorded in provenance. Synthetic checks are separate from model evaluation.

### Extended rules and dated output (2026-11-01)

`vi-arguments-v2` / prompt `lifemate-react-v6` adds synthetic-tested coverage:

- Spoken decimal scale coefficients: `một phẩy năm triệu` -> 1500000.
- Explicit compound durations/halves: `một giờ ba mươi phút` -> 90 minutes;
  `sau nửa tiếng` -> sample time + 30 minutes. Units must descend without duplicates.
- Spoken clocks with optional phút: `bảy giờ mười lăm sáng` -> 07:15; explicit
  seconds remain available. A spoken 1-12 hour still requires a day period.
- Full spoken dates require day, month and year. `đầu/cuối tháng này/sau` means
  first/last calendar day of that month, including leap years and year rollover.
  Week boundaries and dates missing a year remain unsupported rather than guessed.
- Numeric strings use field-aware separators. Money `amount` uses Vietnamese dot
  grouping; a number field treats a single dot/comma as decimal. For other integer
  fields, ambiguous `1.234` rejects instead of becoming 1234. Ambiguous monetary
  comma grouping such as `500,000` rejects. An explicit scale coefficient such as
  `1.234 triệu` uses decimal arithmetic before multiplication.

Run the same E4 audio/public-test configuration in a fresh timestamped directory:

```powershell
Set-Location D:\JarvisMate_4
& .\.venv-asr-train\Scripts\python.exe -B .\python\run_e4.py --all
```

For a one-sample check, replace `--all` with `--id public_0002`. The wrapper uses
local E4 `exports/best`, local Qwen, CUDA offload, the existing selection filter and
120-second development timeout. It performs inference only. No previous prediction
rows are reused; output reflects the current code and models.

New outputs use Vietnam time (UTC+07:00):
`public-test-e4-normalized-YYYYMMDD-HHMMSS`. `run_train.py` similarly uses
`train-all-YYYYMMDD-HHMMSS`. CLI `run` without `--run-dir` defaults to
`.agent-work/lifemate-runs/<split>-<mode>-YYYYMMDD-HHMMSS`; an explicit path is
preserved. Same-second collisions add numeric microseconds; existing output is
never overwritten.

Four completed prediction directories with UUID suffixes were renamed using their
manifest `started_at` converted to Vietnam time. The mapping and SHA256 checks are
in `.agent-work/lifemate-runs/run-directory-renames-20261101-091506.json`.
Historical manifest/argv contents are preserved as execution provenance.

Verification: system Python with `PYTHONPATH=D:\JarvisMate_4\python\src`,
`python -B -m unittest discover -s python/tests -p 'test_*.py'`: 170 tests,
166 passed, 4 skipped, exit 0. New normalization tests (10) and run-path/wrapper
checks (5) all passed in the local venv. Existing argument/parser checks in that
venv: 24 tests, 23 passed, 1 skipped for the missing IANA database. These checks
use synthetic fixtures and the Train catalog validator, not public-test labels.
No E4/Qwen benchmark was rerun by this change.

### Verification in D:\JarvisMate_4 (2026-10-31)

From the repository root, with `PYTHONPATH=D:\JarvisMate_4\python\src`:

- `python -B -m unittest discover -s python/tests -p 'test_*.py'`:
  155 tests, 151 passed, 4 skipped, exit 0. This includes controlled pipeline checks
  and synthetic tiny-model ASR checks; no competition-model benchmark was run.
- `.\.venv-asr-train\Scripts\python.exe -B -m unittest discover -s python/tests -p test_arguments.py -v`:
  24 tests, 23 passed, 1 skipped (IANA database unavailable in this venv), exit 0.
  The actual lm-format-enforcer parser accepted Vietnamese numeric/time proposals.
  The DST test passed separately in the system Python full-suite run.
- The copied venv initially imported LifeMate from JarvisMate_2. An offline
  `python -m pip install --no-index --no-deps --no-build-isolation -e ./python`
  using the venv interpreter repaired the editable package/CLI. Direct import now
  resolves under JarvisMate_4 and `Scripts/lifemate.exe --help` succeeds.

These are implementation checks, not Qwen accuracy, organizer replay or Docker
acceptance. The earlier handoff's unexecuted baseline/model gates remain historical
and do not become complete merely because these checks passed.

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
Validation/error analysis; conditional SFT remains design-only.
