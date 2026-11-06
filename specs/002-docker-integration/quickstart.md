# Integration Validation Guide

**Status**: Planned commands become runnable after tasks.md is implemented. No model,
container or GPU acceptance was performed during planning.

## Prerequisites

- Linux GPU server, Docker, compatible NVIDIA driver and NVIDIA Container Toolkit.
  Select the actual host GPU; no A30-only installation logic.
- Local Whisper/PhoWhisper and native-template-compatible Qwen3 snapshots. Exported
  fine-tuned snapshots are inputs; training remains on a separate branch.
- Supplied Train input/audio/catalog and split-matched organizer runtime/environment
  assets. Access app data only through ToolEnv, including during validation.
- Fixed IDs covering single-call, dependent multi-call, empty-gold, missing-info and
  history. Freeze grouped fit/validation membership before training derivation;
  explicitly report absent categories instead of inventing coverage.

## 1. Controlled checks

After implementation, install the package and run:

```powershell
$env:PYTHONPATH = 'python/src'
python -m unittest discover -s python/tests -p 'test_integration*.py' -v
python -m unittest discover -s python/tests -p 'test_qwen_native.py' -v
python -m unittest discover -s python/tests -p 'test_asr_once.py' -v
```

Verify exact calls/hash with controlled adapters, one ASR call per distinct clip,
native parser/EOS/no-tool/clarification, no labels, blocked ASR/planner/tool/output
timeouts, late/stale rejection, no uncertain replay, bounded recovery for a distinct
sample, and blocked incomplete publication. Run applicable legacy runner/ASR checks.

Inject supervisor death (a) after reservation but before dispatch, (b) after a tool
mutation but before staging and (c) after a timely result but before acceptance fsync.
After recovery, each reserved ID without durable acceptance must remain uncertain,
with no new ToolEnv or dispatch for it. Confirm exclusive run ownership, old-worker
termination, journal corruption rejection and reservation/acceptance write failures.
Verify the deadline also interrupts blocked dispatch writes and incomplete result
frames, with worker logs drained without blocking supervisor control.

## 2. Actual configuration

Copy proposed `configs/integration.example.toml` into ignored local storage. Replace
model paths, selection/hardware settings and run proposed preflight:

```bash
python -m lifemate.integration --config /absolute/config/integration.toml --check-config
```

Expected: effective configuration and identities validated. Actual worker startup
then checks template/tokenizer compatibility and memory. Neither preflight nor model
loading establishes the deadline.

## 3. Offline image

```bash
docker build -t lifemate-integration:dev .
```

Launch as in [container contract](contracts/cli-container.md), networking disabled,
models/data read-only and output persistent. Verify no missing dependency triggers
a download, correct runtime per split and actual host GPU identity. Record digest.

## 4. End-to-end acceptance

Run fixed IDs in transcript diagnostic and audio modes with identical planner settings.
Inspect real feedback, authoritative calls/hash, schema-rejected attempts, empty
completion and clarification. Transcript mode is not audio acceptance.

Record exact commands, dataset hashes/IDs, revision, model/tokenizer/template identity,
seed, GPU/CPU/RAM/driver/CUDA, precision/offload, peak memory, stage times, full attempt
times, p50/p95/max, failures/timeouts and startup/recovery/packaging/total wall time.
Every accepted full attempt must be <30 seconds. Compare legacy/native on paired
IDs/settings only where checkpoints support both protocols; disclose incompatibility.

Report empty/clarification category denominators/errors. Use supplied evaluation
for score/hash claims when available; report unavailable metrics rather than reading
hidden state or inventing aggregation. Optimize one setting at a time with paired
correctness and timing evidence.

## 5. Promotion gates

- Controlled checks and applicable legacy regressions pass.
- Actual checkpoints execute offline in the image using the split-matched runtime.
- Required categories are exercised and failures remain visible.
- Full attempts meet deadline on the stated development GPU; competition hardware
  is a separate acceptance gate when different.
- Parameter/context limits and deterministic repeated outputs are verified.
- Organizer startup/accounting, final Docker entrypoint and failed-sample output
  rules are confirmed before claiming submission readiness.

Unrun gates stay pending. Record actual dataset/command/results in the run evidence.

## Recorded evidence

Entries record only checks actually run, with exact commands and outcomes. Controlled
doubles and tokenizer-only checks never establish model accuracy, GPU memory fit,
container behaviour or deadline compliance on competition hardware.

Environment for local controlled checks: Windows 10 Pro 10.0.19045, CPython 3.11.15
(uv), dev virtualenv `.venv` with torch 2.9.0+cpu, transformers 4.57.1, numpy 2.3.4,
lm-format-enforcer 0.11.3. No GPU, Docker, model weights or supplied Train data are
present on this machine; real-model, container and GPU runs belong on the GPU server.

### US1 native integration (T007-T013), 2026-11-06

```powershell
$env:PYTHONPATH = 'python/src;python/tests'
.venv/Scripts/python.exe -m unittest test_asr_once test_integration_pipeline test_qwen_native `
  test_agent test_cli test_dataset test_audio test_inference test_artifacts test_runtime test_checkpoint test_selection
# Ran 111 tests in 7.8s: OK (skipped=6; the actual-tokenizer class and pre-existing opt-in checks)
$env:LIFEMATE_NATIVE_TOKENIZER = (Resolve-Path .agent-work/models/qwen3-4b-instruct-2507-tokenizer)
.venv/Scripts/python.exe -m unittest test_qwen_native
# Ran 12 tests in 51.6s: OK
```

- Actual tokenizer: Qwen/Qwen3-4B-Instruct-2507 tokenizer/config files only (no
  weights), fetched with `huggingface_hub.snapshot_download(allow_patterns=*.json,*.txt,*.jinja)`
  into ignored `.agent-work/models/`. EOS is `<|im_end|>` (151645); `<tool_call>` is one
  regular token (151657). The real LMFE enforcer admits native calls (Unicode, zero-
  argument, `x-one-of`, `sys.ask_missing_info`, either argument order) and then allows
  only EOS; it rejects prose, ineligible tools, wrong types, extra/duplicate keys and a
  second call.
- Measured constraint overhead (same machine, pure-Python LMFE): building token data
  took 8.4 s per planner load (startup). LMFE's base `SequenceParser` dropped the JSON
  free-text shortcut, making each token inside a string argument take >200 s; the
  `TailSequence` fix brings those tokens to ~0.01 s. One step remains costly: ~3.3 s
  to compute the allowed set where a string value opens, per string argument per
  decision. Separate per-`x-one-of` branches made that step 13 s and then stalled, so
  decoding uses one merged schema per tool and ToolEnv validates the groups. This is
  the main measured latency risk for the 30 s budget; re-measure on the server CPU
  and treat any optimization as a paired T031 change.

### US2 full-attempt supervision (T012, T014-T019), 2026-11-06

```powershell
$env:PYTHONPATH = 'python/src;python/tests'
.venv/Scripts/python.exe -m unittest test_integration_supervisor   # Ran 26 tests in 142.8s: OK
.venv/Scripts/python.exe -m unittest test_integration_pipeline     # Ran 11 tests: OK
```

Real spawned workers (`lifemate.worker` with `integration_doubles:factory`) and a rogue
worker exercised: blocked ASR, planner, tool and durable-output stages (2 s budget)
ending as `timeout` with confirmed process-group termination, recorded overshoot,
quarantined staging and recovery into generation 2 for later IDs; worker crash after a
mutation recorded `EXECUTION_UNCERTAIN` with one environment open; worker-reported
failures kept the healthy worker; partial/stale/late/silent frames, oversized garbage
frames, startup without `ready` and a blocked 900 KB dispatch write all bounded by the
deadline; failed or disabled recovery stopped nonzero with accepted rows retained;
reservation and acceptance journal write failures dispatched nothing / left the
reservation uncertain; supervisor death after reservation, after dispatch, after a
timely result before acceptance, and after a tool mutation (orphan worker terminated
via its recorded pid once its kernel lock proved it alive) never redispatched the
reserved ID; changed model identity blocked resume. On Windows the dead owner's file
lock can be released with a short delay, so ownership acquisition waits up to 5 s.
These are Windows results with controlled doubles; Linux process-group behaviour,
GPU kernels and real model stalls are server gates (T024/T025).

### US3 configurable container (T020-T023), 2026-11-06

```powershell
$env:PYTHONPATH = 'python/src;python/tests'
.venv/Scripts/python.exe -m unittest test_integration_config   # Ran 17 tests: OK
```

Verified with controlled workers: the documented example parses under the strict
schema; `--check-config` validates without creating a run or worker; an invalid
`--device` override exits 2 before any run directory exists; a second compatible
planner snapshot selected with `--planner-model` runs with no code change and a
different run identity; manifests record host, worker hardware/model metadata,
startup and packaging time; resuming with a switched model is rejected (exit 2).
`Dockerfile`, `.dockerignore` and `scripts/integration/server-acceptance.sh` are
authored but **not built or run**: this machine has no Docker or GPU. T024/T025 stay
pending until the server run records the image id, resolved packages and outcomes:

```bash
scripts/integration/server-acceptance.sh --models /abs/models --data /abs/data \
  --config /abs/config --output /abs/output --gpu 0 --second-planner /models/planner-b
```

### US4 diagnostics (T026-T028), 2026-11-06

```powershell
$env:PYTHONPATH = 'python/src;python/tests'
.venv/Scripts/python.exe -m unittest test_integration_diagnostics   # Ran 7 tests: OK
```

Report invocation (offline, after inference; labels never enter the run):

```bash
python -m lifemate.diagnostics --run /abs/output/run-transcript \
  --references /abs/data/train/train.jsonl --catalog /abs/data/train/train_tools_catalog.json \
  --paired-audio /abs/output/run-audio --output /abs/output/diagnostics.json
```

Use two runs over the same frozen ID file with identical planner settings: one with
`data.mode = "transcript"` and one with `"audio"`. The report keeps every selected ID
in its denominators (timeouts, failures, uncertain and unattempted stay separate from
valid empty predictions); reports empty-gold correctness, false empty, clarification
presence precision/recall, intended tool, missing-parameter correctness, unnecessary and
unsuccessful clarification, and overlapping single/multi-call, history and
clarification-after-calls groups; and computes benchmark call matching (fuzzy token-F1
> 0.6 after lowercasing/NFC) as `f1_without_state_gate`. Train labels have no gold
`state_hash`, so hash match and official score are reported as unavailable. Paired
mode attributes IDs exact in transcript but not audio to speech errors. Verified only
with controlled journals; T029 needs the frozen Train selection and real checkpoints
on the server.

### Full controlled regression (T030), 2026-11-06

```powershell
$env:PYTHONPATH = 'python/src;python/tests'
$env:LIFEMATE_NATIVE_TOKENIZER = (Resolve-Path .agent-work/models/qwen3-4b-instruct-2507-tokenizer)
.venv/Scripts/python.exe -m unittest discover -s python/tests -p 'test_*.py'
# Ran 163 tests in 215.2s: OK (skipped=3: pre-existing opt-in real-data/runtime checks)
node scripts/ci/check-context.mjs   # Context checks passed (42 Markdown files)
```

No model/GPU acceptance is inferred from these doubles. Pending server gates: T024/T025
(image build/offline run, second checkpoint), T029 (frozen Train selection, paired
diagnostics), T031 (paired latency/correctness), T032 (organizer accounting and
failed-row rules), T033 (deterministic reruns and hardware evidence limits).
