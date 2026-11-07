# Implementation Plan: Configurable offline Docker integration

**Branch**: `codex/005-docker-integration` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)

## Summary

Add a separate Python integration command around existing capability boundaries:
prepare/transcribe once, native Qwen next-action inference, deterministic execution
in one `ToolEnv`, and authoritative output. Package it in one offline Docker image
with configurable model mounts/GPU settings. A persistent worker keeps models
loaded; an external supervisor bounds full attempts and quarantines late results.
Preserve `python -m lifemate run` defaults for comparison.

Implementation exists with controlled checks; it is not yet a built container or a latency claim. ASR training
material and the root `asr/` experiment folder are removed on this branch; the
runtime ASR adapter remains in the Python package.

## Technical Context

**Language/Version**: Python >=3.11; Linux container; PowerShell authoring supported.
**Primary Dependencies**: Existing PyTorch 2.9.0, Transformers 4.57.1, NumPy 2.3.4,
LM Format Enforcer 0.11.3 and split-matched `zaic_tools`; standard-library TOML,
subprocess, bounded IPC and monotonic timing. Validate pins against CUDA during
implementation; record resolved dependencies and base-image digest after a real build.
**Storage**: Read-only local models/data; ignored run JSON/JSONL and traces.
**Testing**: Existing unittest conventions, controlled adapters and actual tokenizer
checks; separate real-model, offline-container and GPU acceptance.
**Target Platform**: NVIDIA GPU Linux server, Docker and NVIDIA Container Toolkit;
selectable GPU visibility, compatible precision; no fixed GPU model.
**Project Type**: Python CLI/library with container packaging.
**Performance Goals**: Every accepted full attempt <30 seconds; component time,
total/max/percentiles, tokens, timeout counts and GPU-memory measurements.
**Constraints**: Offline deterministic inference; one environment/sample; no uncertain
replay; total model params <6B, planner <5B, context <=16,384.
**Scale/Scope**: Sequential selected samples, later full split; one container, one
healthy persistent worker and one selected GPU. No training/serving system.

## Constitution Check

| Principle | Before research | After design |
|---|---|---|
| I. Benchmark integrity | Pass: retain ToolEnv/log/hash and label isolation | Pass: contracts block incomplete publication |
| II. Capability boundaries | Pass: reuse ASR/planner/executor | Pass: native adapter maps to canonical decisions |
| III. Deterministic execution safety | User-authorized exception: integration continues after isolated failures | Pass with exception documented below: no retry, quarantined output, legacy fail-fast retained |
| IV. Observable evidence | Pass: timings and failure ledger required | Pass: full-attempt clock, provenance, category reports and unrun gates explicit |
| V. Smallest runnable increment | Pass: integration only, training deferred | Pass: stdlib config/supervision; no service or trainer |

The user selected continuation after isolated failures and latency optimization now.
These override the initial fail-fast/defer-optimization baseline for this entry point
only. Record that scope in ADR 011 during implementation; legacy policy and the
constitution remain unchanged.

## Phase 0: Research

Decisions/source evidence: [research.md](research.md). Prior native and measurement
proposals informed this self-contained plan, not delivered functionality. Checkpoint paths/GPU identities
are deployment inputs; the CUDA image digest is resolved by the build acceptance task.

## Phase 1: Design

- [Data model](data-model.md): configuration, prepared audio, attempts and evidence.
- [Runtime contract](contracts/runtime.md): native protocol, ASR reuse, supervision,
  output commitment, failures and recovery.
- [CLI/container contract](contracts/cli-container.md): settings, mounts and commands.
- [Quickstart](quickstart.md): validation stages and evidence requirements.

Keep the executor's canonical call/finish boundary. Render/parse native messages in
a separate adapter; reuse model/session code without changing legacy serialization.
Prove native constraints, tokenizer EOS and an explicit no-tool branch against the
actual checkpoint. Do not assume the user's exported model matches the old prompt.

Use a persistent spawned worker, never fork after CUDA initialization. Worker owns
models, environment, traces and durable staged output. Supervisor starts the clock
before dispatch and accepts only timely completion. On expiry, terminate the worker
process group and quarantine output. Recovery is only for subsequent distinct samples,
bounded and timed separately; never retry uncertain sample effects.

Unique per-attempt durable artifacts are inside the sample budget. Supervisor
acceptance controls later publication. Batch ledger persistence/JSONL assembly is
separately timed bookkeeping, with no inference or tool work deferred into packaging.
Confirm organizer accounting before submission-readiness claims.

Before dispatch, durably reserve sample/attempt/worker/configuration identity under
exclusive run ownership. This is scheduling bookkeeping, timed separately and included
in run wall time; no sample preparation or execution may precede the attempt clock.
If reservation durability fails, dispatch nothing and stop nonzero. On restart, a
reservation without durable acceptance is uncertain, never unattempted. Establish
prior worker termination before continuing with other IDs; never infer acceptance
from staged files alone. Add crash-window checks to the supervisor acceptance tests.

## Project Structure

### Documentation (this feature)

```text
specs/002-docker-integration/
  spec.md
  plan.md
  research.md
  data-model.md
  contracts/runtime.md
  contracts/cli-container.md
  quickstart.md
  tasks.md
  checklists/requirements.md
```

### Source Code (planned additions and affected existing files)

```text
Dockerfile
.dockerignore
configs/integration.example.toml
python/src/lifemate/
  integration.py             # separate CLI and batch coordination
  configuration.py           # strict TOML + known CLI overrides
  supervisor.py              # deadlines, worker lifecycle, acceptance
  worker.py                  # models and isolated sample attempts
  adapters/qwen_native.py     # native messages/parser/decoding
  dataset.py                 # per-sample distinct-clip reuse
  agent.py                   # reuse executor; explicit integration mode
  artifacts.py               # staging/acceptance/provenance support
  diagnostics.py             # offline report; labels outside inference
python/tests/
  test_integration_config.py
  test_qwen_native.py
  test_asr_once.py
  test_integration_supervisor.py
  test_integration_pipeline.py
  test_integration_diagnostics.py
```

**Structure Decision**: Extend the existing package, not a second pipeline tree.
Merge helpers into existing owners where that reduces indirection without weakening
the capability or behavioral-test boundaries.

## Phase 2: Implementation Handoff

[tasks.md](tasks.md) contains unchecked, dependency-ordered work. Establish config
and attempt contracts, then native audio integration, deadline supervision, Docker
deployment and diagnostics. Focused tests are required by FR-017. Real checkpoints
follow controlled correctness/failure checks.

## Complexity Tracking

| Exception | Why needed | Simpler alternative rejected because |
|---|---|---|
| Integration continues after isolated failures | Explicit user decision, retaining failed-attempt evidence | Legacy fail-fast does not meet requested batch behavior |
| External process supervision | Bound blocked native/GPU/tool/output operations | Cooperative stopping only checks when control returns |

No accuracy, latency, GPU-memory or complete-submission gate is passed by this plan.
