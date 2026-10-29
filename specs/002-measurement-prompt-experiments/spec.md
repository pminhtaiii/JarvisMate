# Feature Specification: Pipeline measurement and prompt experiments

**Feature identifier**: `002-measurement-prompt-experiments`

**Created**: 2026-10-29

**Status**: Planned; documentation only

**Input**: Specify offline measurement from ASR through tool execution and output,
then controlled harness and prompt improvements, including optional few-shot examples.

## User Scenarios & Testing

### User Story 1 - Locate sample latency (Priority: P1)

As a developer, I can inspect total sample time and individual transcription,
generation, tool, and output timings without enabling raw dataset payloads.

**Independent test**: Controlled adapters and a fake clock exercise success and
failure without real models or organizer data.

**Acceptance scenarios**:
1. Audio history and multi-call requests record every ASR clip, model generation,
   tool dispatch, final collection, and output persistence.
2. Failures retain available timings with explicit partial/unavailable values;
   absent measurements are never represented as zero.
3. Instrumentation preserves authoritative calls/hash and never repeats tools.

### User Story 2 - Compare runs honestly (Priority: P2)

As a developer, I can generate local reports with latency distributions, coverage,
failures, tokens, and available correctness evidence.

**Independent test**: Synthetic artifacts verify aggregation without inference.

**Acceptance scenarios**:
1. Reports include p50/p95/p99/max, counts, timeouts, over-budget and not-started
   samples, including incomplete runs.
2. Resume imports remain separate from newly executed attempts and their hardware.
3. Missing correctness evidence yields unavailable, not invented accuracy;
   incompatible paired experiments fail comparison with explicit reasons.

### User Story 3 - Evaluate precise prompts and examples (Priority: P3)

As a developer, I can select a versioned precision prompt and optional validated
fit-only examples, with deterministic rendering and reproducible provenance.

**Independent test**: Message fixtures and preflight/checkpoint tests verify example
eligibility, context boundaries, budgets, and identity.

**Acceptance scenarios**:
1. Default configuration preserves the current prompt and action grammar.
2. An opt-in precision profile emphasizes evidence-based IDs, exact schemas,
   context/time, observation-dependent actions, missing information, and stopping,
   without another model pass or a request for hidden reasoning.
3. Held-out/test/unknown-partition or incompatible examples fail preflight.
4. Harness-only and prompt-only candidates are compared separately with the same
   baseline before combined experiments.

### Edge cases

Cover empty requests, schema rejects, failed/selection-filter generations, token
truncation, context overflow, audio history, offload, unavailable adapter metrics,
zero completions, trace/output I/O failure, abrupt process loss, legacy artifacts,
resume imports, and interrupted report publication.

## Requirements

### Functional Requirements

- **FR-001**: Target strictly under 30 seconds per audio sample across ASR, planning,
  tools, authoritative collection and durable prediction output; measure model
  initialization/setup separately pending organizer startup-accounting guidance.
  This feature detects full-attempt overruns retrospectively and preserves the
  existing agent-loop timeout; full-attempt deadline enforcement is separate work.
- **FR-002**: Use monotonic wall timing, including CPU waits, transfers, synchronous
  trace overhead and GPU work required to return completed outputs.
- **FR-003**: Record per-clip ASR, each generation including filters/corrections,
  each tool call, final collection, output persistence, and total attempt time.
- **FR-004**: Record available input/output token counts, generation duration/rate,
  role and stop reason, with explicit availability; distinguish ASR from planner.
- **FR-005**: Extend bounded sanitized metadata traces/manifests while preserving
  payload opt-in, prediction schema, execution safety, and existing defaults.
- **FR-006**: Report distributions with population counts, failures, partial timing,
  overruns, not-started IDs, imports and incomplete coverage.
- **FR-007**: Attach correctness only from explicit compatible evaluation evidence;
  preserve state-hash gating for nonempty gold and the separate empty-gold rule.
- **FR-008**: Regenerate reports offline without models or ToolEnv; validate sample
  IDs and experiment identity before paired comparisons.
- **FR-009**: Version/hash resolved prompt content and example provenance and include
  these in execution identity and strict checkpoint compatibility.
- **FR-010**: Provide baseline and opt-in precision profiles plus optional
  deterministic fit-only examples with a bounded token budget.
- **FR-011**: Reject invalid configuration/bundles before inference; enforce context
  plus reserved generation tokens without silently dropping live evidence.
- **FR-012**: Isolate harness-only, instruction-only, and few-shot factors; otherwise
  hold samples, models, ASR, runtime, decoding, limits and hardware/protocol fixed.
- **FR-013**: Preserve failure/resume policy and one ToolEnv; metrics/reporting never
  replay calls, reopen completed environments, or promote incomplete output.

### Key entities

Run identity, sample attempt, span, generation, prompt profile, example bundle,
partition manifest, report and comparison: see [data-model.md](data-model.md).

## Success Criteria

- **SC-001**: Every selected ID is classified; every started attempt has a terminal
  measurement or explicit incomplete evidence; imports are identified separately.
- **SC-002**: Fake-clock fixtures reproduce documented timing/percentile results
  including failures, missing values and empty populations.
- **SC-003**: Baseline messages remain equivalent and controlled instrumentation
  with generous deadlines produces identical authoritative predictions. Real runs
  near the deadline may fail earlier due to instrumentation cost; report that cost
  and those failures rather than promising deadline-edge output equivalence.
- **SC-004**: Leaking/invalid examples and changed prompt identities fail preflight
  or strict resume; valid bundles render deterministically within budget.
- **SC-005**: Acceptance reports name dataset, command, revision and hardware.
  Compliance claims require fully measured audio coverage on A30 with no failures,
  unknown timings or samples at/above 30 seconds in the stated coverage.
- **SC-006**: Candidate promotion follows the paired correctness/latency policy in
  [contracts/experiments.md](contracts/experiments.md), not JSON validity alone.

## Assumptions and exclusions

This local subsystem adds no HTTP server, dashboard, external telemetry or runtime
dependency. Reflection, SFT, specialist agents, parallel execution changes, automatic
prompt search, a new benchmark scorer, full-attempt deadline enforcement and hard
process supervision are excluded.
Frozen Train Validation, evaluation evidence and A30 access are execution
prerequisites, not completed facts. Detailed baseline trace requirements still apply.
Planning does not authorize implementation or inference runs.
