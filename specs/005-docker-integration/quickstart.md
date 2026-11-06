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
