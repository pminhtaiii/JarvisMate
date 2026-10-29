# Implementation Plan: Pipeline measurement and prompt experiments

**Feature**: `002-measurement-prompt-experiments` | **Date**: 2026-10-29

**Git branch**: `15.11` (unchanged; feature identifier is not a created branch)

**Spec**: [spec.md](spec.md)

## Summary

Extend current trace/manifest boundaries with structured timing and optional adapter
telemetry; add offline report/comparison commands. Keep the current prompt as default
and introduce opt-in precision/few-shot configurations with fit-partition validation
and checkpoint-aware identity. Measure first; evaluate harness and prompt factors
separately. No implementation or runtime result is established by this plan.

Read the [baseline plan](../001-python-sample-pipeline/plan.md) for existing execution
contracts; this feature's new boundaries live in [contracts](contracts/).

## Technical Context

**Language/Version**: Python 3.11+.

**Primary Dependencies**: Existing local adapters, PyTorch/Transformers and
split-matched zaic_tools; standard-library measurement/reporting, no new package.

**Storage**: Existing ignored `.agent-work/lifemate-runs/` files, derived JSON/Markdown
reports, local versioned prompt/example metadata.

**Testing**: Existing unittest style; controlled adapters/clocks, artifact fixtures,
separate real-model/runtime acceptance.

**Target Platform**: Windows/Linux development; final offline Linux/A30.

**Project Type**: Existing library/CLI.

**Performance Goals**: Diagnose full audio time against strict <30 seconds; track
instrumentation cost without promising an unmeasured speedup.

**Constraints**: Offline/deterministic, one ToolEnv, unchanged prediction schema,
bounded sanitized metrics, existing 16,384-token context and model-size limits.

**Scale/Scope**: Current sequential worker and validation runs; no new scheduler,
concurrent inference, remote service, profiler or optimizer.

## Constitution Check

Pre-research and post-design checks pass at design level:

| Principle | Evidence |
|---|---|
| I. Benchmark integrity | Preserve ToolEnv/output; fit-only examples; labels only in separate evaluation evidence. |
| II. Capability boundaries | Preserve adapter string protocols; optional telemetry; Python owns sample measurement. |
| III. Execution safety | No extra calls/retries; deterministic profiles; preserve failure/resume defaults. |
| IV. Observable evidence | Explicit unavailable/partial data, coverage and provenance; no result claims. |
| V. Smallest increment | Local files, CLI/store reuse, no new dependency or service. |

Existing opt-in continuation/mixed resume remain development behavior; mixed
identities cannot support acceptance comparisons. External startup-accounting
uncertainty is handled by separate initialization metrics. No exception is requested.

## Project Structure

```text
specs/002-measurement-prompt-experiments/
  spec.md, plan.md, research.md, data-model.md, quickstart.md, tasks.md
  contracts/measurement.md, prompts.md, experiments.md
python/src/lifemate/
  metrics.py, reporting.py, prompt_profiles.py, example_audit.py  # proposed modules
  prompting.py, contracts.py, cli.py
  agent.py, dataset.py, artifacts.py, provenance.py, checkpoint.py
  adapters/common.py, adapters/asr.py, adapters/planner.py
python/tests/
  test_metrics.py, test_reporting.py, test_prompt_profiles.py  # proposed tests
  # extend existing CLI/checkpoint/orchestration tests
```

**Structure Decision**: Extend Python's complete sample boundary, expose reports as
CLI commands, and leave the eventual TypeScript transport unchanged.

## Phase 0: Research

[research.md](research.md) resolves repository integration and design choices. No
new dependency/API upgrade is proposed. Broad timing and durable trace mechanisms
exist; fine-grained telemetry, reporting and configurable prompts require integration.

## Phase 1: Design

1. Add versioned metric values and optional telemetry sinks, keeping adapter return
   values and ToolEnv authority intact. Legacy adapters report unavailable details.
2. Measure the full CLI attempt separately from agent-loop elapsed; retain stages,
   generation metadata, failure timings and attempt provenance.
   Preserve the existing loop timeout; classify full-attempt overruns in reports,
   without changing completed-row/resume behavior or adding deadline enforcement.
3. Extend RunStore failure paths and offline readers for incomplete/process-loss
   evidence without changing execution policy.
4. Add offline report/compare commands requiring no models or simulated state.
5. Resolve prompt/example configuration before model loading. Pass it to LocalPlanner;
   derive manifests/checkpoint identity from resolved content, not baseline constants.
6. Implement opt-in precise-v1 and deterministic compatible fit-only examples, then
   compare factors separately using the experiment contract.
   A separate offline example-audit command verifies source gold prefixes/targets;
   inference receives only its validated fit artifact, never raw labeled records.

The contracts define timing, bounds, CLI/configuration, failure behavior, budgets,
provenance and acceptance. [quickstart.md](quickstart.md) contains future validation
scenarios, not claims that the proposed commands already exist.

## Phase 2: Task handoff

[tasks.md](tasks.md) orders implementation and validation. Measurement is the MVP;
prompt experiments follow its reporting contract. All implementation tasks remain
unchecked. Real models/runtime/A30 testing is separate execution work.

## Complexity Tracking

No constitution violation, new service, database or runtime dependency.
