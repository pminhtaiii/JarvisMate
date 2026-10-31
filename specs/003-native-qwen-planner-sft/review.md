# Plan review and publication evidence

**Date**: 2026-10-31 (Asia/Saigon).
**Base**: JarvisMate `main` at `3054d0e039aa57158addf98474c2b3dcb8e17dbc`.
**Scope**: Planning documents only; no runtime implementation or training changes.

Two independent Luna subagents used max reasoning: requirements alignment and
implementation feasibility/standards. Both reviewed the feature documents and
relevant repository boundaries; feasibility was checked against the current
publication base after discovering the original checkout predates measurement PR #8.
Final source hashes and axis reports are retained in ignored review artifacts;
the commit containing this record identifies the published candidate.

## Requirements review

R1 (P2): The shared SFT design still allowed full fine-tuning, conflicting with
accepted all-linear LoRA/conditional QLoRA. Updated
[shared design](../../docs/design/train-to-sft.md) to identify the native model
serialization versus canonical executor decisions and the accepted method; T025
keeps implementation-time reconciliation explicit. Disposition: addressed.

The remaining accepted decisions are represented: one native call per decision,
native final completion, canonical executor authority, baseline comparison before
fit, grouped Train-only supervision, benchmark/latency objective, optional later
GRPO and no fixed number of tuning rounds.

## Feasibility and standards review

R2 (P1): The existing comparator only supports harness/instructions/few-shot and
rejects changed planner weights. [Experiment contract](contracts/experiments.md)
now specifies protocol/planner-model factors with narrow identity permissions;
T017 adds comparator/CLI changes and regression checks. Existing factor checks
remain strict. Disposition: addressed.

R3 (P2): Duplicate grouping needed an explicit near-duplicate policy and existing
partition compatibility. [Training contract](contracts/training.md) now defines
versioned candidate detection/review, transitive groups, limitations and immutable
partition-v1 provenance; T014–T015 cover producer/validator/tests. Disposition: addressed.

R4 (P2): Dependency wording treated measurement as only planned despite its merged
foundation. Plan/spec/tasks distinguish present source/controlled-test evidence from
unverified model/GPU/evaluator acceptance. Disposition: addressed.

The feasibility reviewer found no remaining material issue in native envelope/EOS,
target masking or executor isolation. This is design review, not runtime verification.

## Executed planning checks

- `node scripts/ci/check-context.mjs`: passed (52 Markdown files, 0 canonical facts).
- Spec Kit `check-prerequisites.ps1 -Json -RequireTasks -IncludeTasks`: passed for
  `specs/003-native-qwen-planner-sft`, with explicit feature selection/no-persist.
- Python document audit: relative links and placeholder checks passed; all 35 task
  IDs are sequential and checklist entries have file paths. Story counts:
  US1 10, US2 6, US3 6, US4 7; 6 setup/foundation/handoff tasks.
- `git diff --check`: passed before publication.

Native tokenizer/LMFE tests, exporter checks, fitting, official scoring and A30
timings were not run. Their acceptance tasks remain unchecked. No dataset,
environment state, weights or debug traces are included in the PR.
