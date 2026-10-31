# Implementation Plan: Native Qwen planner and supervised fine-tuning

**Feature**: `003-native-qwen-planner-sft` | **Date**: 2026-10-31
**Git branch**: `codex/native-qwen-planner-sft-plan`
**Publication base**: JarvisMate `main`, reviewed at `3054d0e039aa57158addf98474c2b3dcb8e17dbc`
**Spec**: [spec.md](spec.md)

## Summary

Adopt Qwen's native tool serialization behind the canonical Python planner boundary.
Implement native prompts, constrained single calls, strict parsing and EOS-aware
completion; compare protocols before fitting. Then export fit-only next-action data,
train optional LoRA/QLoRA adapters and evaluate a merged deployment checkpoint.
Implementation, training and runtime acceptance remain outstanding.

## Technical Context

**Language/Version**: Python 3.11+; existing library/CLI and unittest conventions.

**Primary Dependencies**: Existing inference pins: PyTorch 2.9.0, Transformers
4.57.1, LMFE 0.11.3. Optional isolated training uses TRL/PEFT/bitsandbytes; exact
compatible versions are locked after a one-batch smoke and before fitting.

**Storage**: Ignored `.agent-work/lifemate-runs/` partitions, examples, manifests,
reports, adapters and exports. Competition data/weights remain outside source control.

**Testing**: Controlled parser/grammar/rendering/runner checks, actual-tokenizer
mask and grammar tests, fit smoke, real ToolEnv and separate A30 acceptance.

**Target Platform**: Windows/Linux development; training preferably isolated Linux;
final offline Linux on A30/16-core CPU/64 GB RAM.

**Project Type**: Existing library/CLI with optional offline training module.

**Performance Goals**: Higher supported benchmark outcome; complete audio attempts
strictly <30 seconds on target hardware. No unmeasured speedup promised.

**Constraints**: One ToolEnv, sequential decisions, unchanged submission, LLM <5B,
all models <6B, prompt plus reserved output <=16,384 tokens, fit-only training,
fixed seeds/greedy inference, no automatic uncertain-execution retries.

**Scale/Scope**: Approximately 1,600 source Train cases per brief; actual counts
and lengths audited. One initial model, no fixed trial count.

## Constitution Check

Pre-research and post-design checks pass at design level:

| Principle | Evidence |
|---|---|
| I. Benchmark integrity | Original ToolEnv/log/hash; groups split before expansion; gold only in offline export/evaluation. |
| II. Capability boundaries | Native serialization/parsing stays in adapter; runner retains execution authority. |
| III. Execution safety | One complete call or EOS-confirmed final response; token/deadline cuts never become finish. |
| IV. Observable evidence | Protocol/template/constraint identities, bounded native traces, explicit score/hardware availability. |
| V. Smallest increment | Protocol MVP before conditional training; no Qwen-Agent, server, parallel dispatcher or inference trainer dependency. |

The constitution defers tuning while establishing the baseline. Training remains
gated on baseline/error evidence; planning does not claim the gate passed. No
amendment/exception is required. Existing contracts remain the structured control;
native-specific behavior is defined in this feature until implemented.

## Project Structure

```text
specs/003-native-qwen-planner-sft/
  spec.md, plan.md, research.md, data-model.md, quickstart.md, tasks.md
  contracts/native-protocol.md, training.md, experiments.md
python/src/lifemate/
  prompting.py, adapters/planner.py, adapters/constrained.py
  adapters/qwen_protocol.py                       # proposed native codec
  contracts.py, cli.py, artifacts.py, checkpoint.py, provenance.py
  prompt_profiles.py, reporting.py
  training/__init__.py, __main__.py, data.py       # proposed offline path
  training/fit.py, export.py
python/tests/
  test_qwen_protocol.py, test_training_data.py, test_training_fit.py  # proposed
  test_inference.py, test_agent.py, test_cli.py, test_checkpoint.py, test_reporting.py
python/requirements-training.txt                  # proposed compatible exact lock
```

**Structure Decision**: Share native rendering with training. Save training adapters
and merge onto the original full-precision base for deployment; existing
`--planner-model` loads the export, avoiding a new inference adapter-loading API.

## Phase 0: Research

[research.md](research.md) resolves native serialization, finish supervision, grammar,
masking, method and evaluation boundaries. No product clarification remains. Hardware,
training package lock, dataset counts and evaluator availability are measured execution
prerequisites with explicit blocked outcomes, not assumed facts.

## Phase 1: Design and contracts

1. Add explicit `--planner-protocol structured-v1|qwen-native-v1`; structured remains
   the comparison control/default until acceptance. Native is required for training.
   Protocol selection is orthogonal to feature 002 instruction profiles; reject
   incompatible profiles/example bundles before loading models.
2. Pass eligible definitions via `tools=`, executed calls as assistant `tool_calls`,
   results as `tool` messages. Keep supplied history in initial context data to
   preserve its current interpretation. Native conversion covers current observations.
3. Compose native single-call grammar from literal envelope, tool-bound argument
   schema and suffix, plus fixed neutral final text `Mình hiểu.`. Require actual EOS.
   Parse strictly and return the existing canonical decision to the runner.
4. Keep selection-filter planning in its separate JSON protocol. Its rejected
   proposals are correction data, never executed results. Initial experiments use
   this filter disabled; focused checks cover compatibility.
5. Version prompt/template/protocol/constraint and resume identities. Opt-in bounded
   traces retain native output, EOS/stop reason and interpreted canonical action.
6. Reuse feature 002 partition-manifest v1 validation and reporting. Its foundation
   is present on the publication base with controlled checks recorded in its
   [validation](../002-measurement-prompt-experiments/validation.md); real model/GPU/
   evaluator acceptance remains unestablished. Extend its comparator with narrow
   `protocol` and `planner-model` factors per [experiments](contracts/experiments.md),
   then freeze groups and compare transcript/audio runs. Existing factors reject
   changed models and cannot be reused unchanged. Missing official outcomes block promotion.
7. Add optional `python -m lifemate.training` partition/export/fit/merge commands
   per [training contract](contracts/training.md). Reuse explicit input whitelists
   and native rendering; keep inference label-free and loss target-only.
8. Lock compatible training packages after smoke. Start all-linear rank-32/alpha-64
   LoRA; use NF4/double-quant/BF16 QLoRA if measured memory requires it. Initial
   numeric settings are experiments, not established optima.
9. Merge/reload using original base identity; evaluate actual deployment export
   under pinned inference. Promote only with benchmark/timing evidence; keep base fallback.

Post-design constitution gates remain satisfied. [quickstart.md](quickstart.md)
defines future validation; new commands are not implemented by these documents.

## Phase 2: Task handoff

[tasks.md](tasks.md) orders unchecked implementation work. US1 is the protocol MVP;
US2 supplies evidence before US3/US4 fitting. Feature 002 full-attempt reporting is
an external acceptance dependency. Missing scoring blocks score-based promotion,
not parser/export development. Real training remains conditional on error analysis.

## Complexity Tracking

No constitution violation. New optional training dependencies and the native codec
serve the accepted feature; no synthetic generator, RL, server or parallel executor.
