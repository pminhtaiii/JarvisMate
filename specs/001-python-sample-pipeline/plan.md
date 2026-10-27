# Implementation Plan: Runnable Python sample pipeline

**Feature**: `001-python-sample-pipeline` | **Date**: 2026-10-27 | **Spec**: [spec.md](spec.md)
**Git branch**: `feat/docs-lifemate-stack` (preserved). Spec Kit reports the feature
identifier as BRANCH; that does not mean a Git branch was created.
**Status**: Source/tests authored; install, tests and real-model acceptance are unexecuted.
See [validation.md](validation.md) for the receiving-machine handoff.

## Summary

Build a small Python package with `check-data` and `run` commands. Process explicit
sample IDs sequentially using one general structured ReAct planner and exactly one
organizer environment per sample. Require traces, retain partial results, and stop
on the first execution failure. Establish a training-transcript checkpoint before
connecting audio ASR. Validate on the uploaded subset before attempting a full split.

Use the official Spec Kit 1.2.3 scaffolding, templates, and PowerShell setup scripts.
See [research.md](research.md) for evidence and choices, [contracts/](contracts/) for
interfaces, and [quickstart.md](quickstart.md) for proposed validation commands.

## Technical Context

**Language/Version**: Python 3.11+; standard-library core. Windows development and
Linux execution. Keep the root TypeScript project untouched.

**Primary Dependencies**: Organizer split runtime (stdlib only). Optional local
inference dependencies: PyTorch, Transformers, NumPy. Pin versions after validating
Qwen and Whisper integration; the model card requires Transformers >=4.51 for Qwen3.
No agent framework, HTTP service, database, or new TypeScript dependencies.

**Storage**: Existing ignored `sample/` for local data; unique run directories under
ignored `.agent-work/lifemate-runs/` for traces, manifest, partial/completed results.

**Testing**: Standard-library `unittest` under `python/tests/`; controlled adapters
for GPU-free checks and separately opt-in real-runtime/model smoke runs.

**Target Platform**: Python CLI on Windows/Linux. Future final-container target remains
A30/16 CPU cores/64 GB RAM; Docker compliance is outside this feature.

**Project Type**: Python library and CLI, retaining models across sequential samples.

**Performance Goals**: Establish behavior and record phase timings before optimizing.
Default sample budget 30 seconds; explicit longer development budgets are labeled
noncompliant. No measured performance goal is asserted by this plan.

**Constraints**: Offline inference, model totals <6B and planner <5B parameters,
context <=16,384 tokens including generation reservation, exactly one ToolEnv/sample,
no uncertain-execution retry, Vietnamese catalogs, labels excluded from inference.

**Scale/Scope**: First one, then four selected local training samples. The full train
JSONL has 1,545 records, but only four have local current audio. Full-split processing
is an explicit option requiring complete selected assets; not the first milestone.

## Constitution Check

| Principle | Before research | After design | Evidence |
|---|---|---|---|
| Benchmark integrity | PASS | PASS | Runtime uses ToolEnv only; input whitelist; authoritative serialization |
| Capability boundaries | PASS | PASS | Explicit planner/ASR/environment contracts; complete sample stays in Python |
| Deterministic execution safety | PASS | PASS | Preflight, organizer validation, bounds, no retry, fail-fast manifest |
| Observable evidence | PASS | PASS | Required traces from first runnable story; controlled/model evidence separated |
| Smallest runnable increment | PASS | PASS | Standard-library CLI/core, optional inference deps, no UI/TS/network service |

No justified violations or unresolved design clarifications. Compute and model files
remain execution prerequisites with separate acceptance evidence, not invented guarantees.

## Project Structure

### Documentation (this feature)

```text
specs/001-python-sample-pipeline/
  spec.md
  plan.md
  research.md
  data-model.md
  contracts/cli.md
  contracts/planner.md
  contracts/artifacts.md
  quickstart.md
  tasks.md
  validation.md
  checklists/requirements.md
  analysis.md
```

### Source Code (authored; execution validation pending)

```text
python/
  pyproject.toml
  README.md
  src/lifemate/
    __init__.py
    __main__.py
    cli.py
    contracts.py
    jsonio.py
    dataset.py
    runtime.py
    agent.py
    artifacts.py
    prompting.py
    adapters/planner.py
    adapters/asr.py
    adapters/common.py
  tests/
    test_dataset.py
    test_runtime.py
    test_agent.py
    test_artifacts.py
    test_cli.py
    test_inference.py
    test_audio.py
    test_real_samples.py
```

**Structure Decision**: One Python package with small capability modules, standard
interfaces, and injected adapter instances. Test fixtures stay inside test code;
local dataset contents, weights, and generated artifacts remain ignored. No generic
plugin registry or framework is needed.

## Runtime Design

1. Parse explicit split, data root, runtime directory, input mode, selected IDs, bounds,
   and run directory. Resolve all paths and refuse reuse of a run directory.
2. Preflight the selected records and catalog before any model load or ToolEnv creation.
   Record input failures in the run manifest before sample traces or environments exist.
   Require the catalog at the exact path used by ToolEnv; the supplied runtime silently
   relaxes schema checks if it is missing. Validate selected asset paths with existence
   checks only for environment state; never open hidden files in our code. A contained
   directory alias can correct the expected spelling without changing uploaded data.
3. Use an explicit trusted runtime directory (`tools/train` or `tools/test`) with package
   loading via `importlib.util.spec_from_file_location` and package search locations.
   One invocation supports one split/runtime. For a complete official package, point
   to its `zaic_tools` directory. No copying or editing runtime source.
4. Load the selected local pretrained planner once; audio mode loads exactly one ASR
   candidate once. Keep model loading outside per-sample execution timing and report
   initialization separately. No implicit network fetches or transcript fallbacks.
5. For each sample, start its trace and monotonic deadline before request preparation.
   Build the input whitelist: training transcript mode uses current `audio_text`
   and previous user transcripts; audio mode transcribes current and history-user WAVs
   using the already loaded ASR. Preserve assistant text/calls/results in order.
   Never replay history or include labels. ASR consumes the sample's deadline budget.
6. After request preparation succeeds, create exactly one ToolEnv for that sample,
   then begin planning. The planner sees only declared tools plus the system tool.
7. Enforce the planner action contract, context cap, step bound (default 16 model
   decisions), and remaining deadline. Reject malformed or unavailable actions before env.call;
   return bounded validation feedback for correction within the same step budget.
8. Write call-intent trace before dispatch; send well-formed, allowed calls to ToolEnv.call
   even when their arguments violate the tool schema. The environment validates and logs
   the attempt for submitted tool_calls; return schema-error feedback to the planner.
   Record the returned result as an observation; `done:false` may require another
   decision. Exceptions with uncertain effects fail the sample without retry.
9. Finish on explicit finish or after a successful `sys.ask_missing_info` call whose
   result has `waiting_for_user:true`. Other results, including success without that
   condition, return to the planner within the remaining bounds. Retrieve
   authoritative calls/hash, finish the trace, flush the result row, update the manifest.
   No extra model call is required solely to compose a closing message.
10. On failure, stop before the next sample; preserve earlier rows and available failed
    sample log/hash as diagnostic evidence only. Publish completed results only after
    coverage and output validation pass. Never turn failure evidence into a successful row.

### Timing and failure boundaries

Pass remaining time to model generation stopping criteria; check it before/after
ASR and tool calls. The bundled tools are synchronous: an overrun is detected when
control returns; hard interruption of a stuck native/GPU call is not promised by the
CLI. A future outer process supervisor is required to establish hard container timing.
A run killed externally leaves an incomplete manifest/partial output, not a completed run.

### Traces and artifacts

Implement the event and publication contract in [contracts/artifacts.md](contracts/artifacts.md).
Require trace availability before further effects. Keep data-bearing dataset-debug
payloads explicitly enabled by `--trace-payloads`; metadata traces remain required
by default; metadata-only runs do not satisfy baseline-validation evidence. Preserve
exact calls in the authoritative prediction output regardless
of trace truncation/redaction. A sampled completion is labeled as a subset, not a
competition-ready full submission.

## Delivery Checkpoints

1. GPU-free dataset, runtime, controlled ReAct, and artifact verification.
2. One real pretrained-planner run on a selected training transcript with the supplied
   environment, then the four selected IDs. This is externally blocked until weights
   and suitable compute are available; retain an explicit blocked acceptance task.
3. Audio adapter checks, then the same real samples in audio mode with a selected ASR.
4. Record evidence and update affected context. Full-split/Docker compliance and
   TypeScript/HTTP integration are later features.

## Follow-on roadmap

This feature delivers the pretrained sample baseline. The project-wide sequence is
[Baseline -> Train Validation -> Error Analysis -> conditional Fine-tuning](../../context/roadmap.md).
The [Train-to-SFT design](../../docs/design/train-to-sft.md) plans next-action
supervision from Train gold prefixes as a separate later feature. This link does
not add an exporter/trainer to feature 001 or complete any implementation task.

## Complexity Tracking

No constitution violations. Do not implement speculative recovery caches, domain
routers, custom schema engines, custom scoring aggregation, or workflow services.
