<!--
Sync impact: initial adoption -> 1.0.0 (2026-10-27).
Derived from existing LifeMate instructions and accepted ADRs; no new product commitments.
Principles: benchmark integrity; capability boundaries; deterministic execution safety;
observable evidence; smallest runnable increment.
Templates checked: spec-template.md, plan-template.md, tasks-template.md (compatible; unchanged).
No command-template directory or extension hooks installed with the none integration.
Deferred placeholders: none.
-->
# LifeMate Constitution

## Core Principles

### I. Benchmark integrity

Benchmark execution MUST follow [benchmark rules](../../context/benchmark.md): use the
split-matched organizer runtime, one `ToolEnv` per sample, and its authoritative call
log and hash. Simulated app data MUST be accessed through tools, not by reading,
copying, or parsing environment files. Training references MUST remain outside
planner inputs; public/private test data MUST NOT be labeled for tuning.

### II. Capability boundaries

ASR, planning, and tool execution MUST have independently replaceable interfaces.
Python owns complete sample execution; the eventual TypeScript harness owns outer
scheduling and reporting. Follow [architecture](../../context/architecture.md) and
accepted ADRs for the current baseline, including one general planner and structured ReAct.

### III. Deterministic execution safety

Code MUST enforce external-data validation, tool eligibility, execution bounds,
and schema checks. Model output cannot bypass these controls. Uncertain executions
MUST NOT be automatically repeated or restarted with a fresh sample environment.
The initial development batch MUST stop on its first execution failure, retaining
completed results and evidence. Valid empty results MUST remain distinct from failures.

### IV. Observable evidence

Development runs MUST retain per-sample traces sufficient to inspect the executed
path as well as the final outcome, following [testing guidance](../../context/testing.md).
Claims MUST identify actual dataset selection, command, revision, model settings,
and measured outcomes. Controlled responses establish orchestration behavior, not
model accuracy; a planned feature is not a completion claim.

### V. Smallest runnable increment

Changes MUST implement the smallest complete authorized slice, reuse the supplied
runtime, and follow [code standards](../../context/code_standard.md). Non-trivial
boundary behavior MUST include focused behavioral verification. Model tuning,
specialist agents, and UI work remain deferred while establishing the runnable baseline.

## Competition constraints

The offline, deterministic final runner and model/context/time limits are defined
in the benchmark reference. A working development subset does not establish full-split
coverage or final-container compliance. Development prioritizes runnable behavior
before latency optimization while retaining timing evidence.

## Development workflow

Specifications define outcomes; plans define implementation; `tasks.md` records
implementation progress. GitHub issues/PRs remain the shared coordination record per
[team workflow](../../context/team.md). Use focused checks before broader checks and
record ADRs for consequential trade-offs. Keep local datasets and traces ignored.

## Governance

This initial constitution consolidates existing project rules for Spec Kit planning.
Explicit user instructions and the competition requirements retain precedence.
Amendments MUST identify the changed principle, rationale, affected artifacts, and
compatibility impact; use major/minor/patch versioning for incompatible changes,
new principles, and clarifications respectively. Plans MUST evaluate these principles
before research and again after design; reviewers cite rules and concrete evidence.

**Version**: 1.0.0 | **Ratified**: 2026-10-27 | **Last Amended**: 2026-10-27
