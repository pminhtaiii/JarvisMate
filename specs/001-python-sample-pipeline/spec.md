# Feature Specification: Runnable Python sample pipeline

**Feature**: `001-python-sample-pipeline`
**Git branch at planning**: `feat/docs-lifemate-stack` (unchanged; no branch created)
**Created**: 2026-10-27
**Status**: Ready for implementation review; implementation not started
**Input**: Build the Python pipeline on a few supplied competition samples first,
using one general planner, structured ReAct, organizer tools, required traces,
stop-on-failure behavior, and competition-shaped JSONL results. Start from training
transcripts, then connect real audio inference. GPU access is not currently available.

## User Scenarios & Testing

### User Story 1 - Inspect one text-to-tools sample (Priority: P1)

As a developer, I can select one training sample and run its supplied transcript
through the planner and the real simulated apps, producing an authoritative result
and a trace of how the agent reached it.

**Why this priority**: Establishes the core runnable path independently of speech errors.

**Independent Test**: Select one locally available training ID. With controlled
planner responses, verify real environment dispatch, returned-value use, call logging,
and output; with a real pretrained planner, record a separate text-input run when
weights/compute are available. A controlled run is not model evidence.

**Acceptance Scenarios**:

1. **Given** a selected record and matching environment, **when** the planner looks up
   an entity and uses its observed ID in a later action, **then** actual calls,
   results, validation decisions, and the final environment hash are inspectable.
2. **Given** an unsupported request, **when** the planner finishes without a tool,
   **then** the result contains an empty authoritative call list and a real hash.
3. **Given** missing required information, **when** the planner calls
   `sys.ask_missing_info`, **then** that call is recorded and the sample stops as a
   valid missing-information outcome, including any earlier executed calls.
4. **Given** labels and historical actions, **when** inference runs, **then** labels
   never enter planner inputs and history is not re-executed.

### User Story 2 - Run a selected subset and expose failures (Priority: P1)

As a developer, I can process a few explicit sample IDs sequentially and inspect a
clear outcome without silently losing samples or earlier work.

**Why this priority**: The immediate target is the uploaded subset, not the complete dataset.

**Independent Test**: Run a successful two-sample batch, then inject a failure
in its second sample. Confirm persistence of the first result and failure trace,
a nonzero exit, and no processing of a third queued sample.

**Acceptance Scenarios**:

1. **Given** two selected IDs, **when** both complete, **then** exactly two UTF-8
   JSONL result rows appear in dataset order, separate from traces.
2. **Given** an execution failure, **when** it occurs, **then** the batch stops,
   preserves completed rows and failure evidence, and publishes no complete result.
3. **Given** missing selected assets, duplicate IDs, malformed records, or unsafe
   paths, **when** preflight runs, **then** it reports the defect before opening an
   environment or invoking a model; selected IDs are never silently skipped.
4. **Given** a subset run, **when** it completes, **then** its manifest labels it a
   subset result rather than a full competition submission.

### User Story 3 - Run the same samples from audio (Priority: P2)

As a developer, I can switch from supplied training transcripts to actual audio
without changing tool execution, and compare resulting tool paths.

**Why this priority**: Completes the speech-to-tools path after the text checkpoint.

**Independent Test**: Run the same local IDs in transcript and audio modes with
real planner/ASR weights; record differing transcripts, paths, and timing.
GPU-free tests verify adapter behavior with controlled ASR output.

**Acceptance Scenarios**:

1. **Given** current and history-user audio, **when** audio mode runs, **then** ASR
   supplies all user-turn request text without supplied-transcript fallback;
   previous assistant history remains context.
2. **Given** missing audio or model weights, **when** preflight/loading runs,
   **then** it fails without fabricating a transcript or sample result.
3. **Given** multiple selected samples, **when** they execute, **then** model
   instances are reused while each sample has one isolated environment.

### Edge Cases

- Invalid model JSON, unexpected action fields, unavailable tools, schema-invalid
  arguments, context overflow, and exhausted action/time budgets.
- Schema-valid `done: false` or empty results return to the planner; they are not
  automatically runtime failures.
- A runtime exception after possible execution fails the batch without repeating
  the uncertain call; preserve whatever authoritative evidence remains available.
- Historical actions are already applied and must not execute again.
- Missing-information outcomes can follow earlier mutations.
- Trace/output write failures prevent further effects and success publication.
  An external hard crash may leave partial evidence.
- Full JSONL records coexist with only a few local assets. Selection is explicit;
  unrelated missing assets do not block a selected-subset run.

## Requirements

### Functional Requirements

- **FR-001**: Provide a direct Python CLI that checks data and runs explicit selected
  IDs. A full-split option must be explicit; subset selection is the quickstart.
- **FR-002**: Validate record identity, context/history shape, tool references, selected
  asset existence, and path containment before inference; reject duplicate/unknown IDs.
- **FR-003**: Separate parsing, ASR, planning, and execution with small interfaces.
  Preserve the eventual whole-sample Python boundary for TypeScript integration.
- **FR-004**: Whitelist planner context/history; exclude top-level `label`. Supplied
  current/history transcripts are permitted only in training-transcript mode.
- **FR-005**: Expose sample-declared tools matching the split catalog, plus
  `sys.ask_missing_info`; preserve Vietnamese descriptions and exact identifiers.
- **FR-006**: Create exactly one split-matched `ToolEnv` per executed sample.
  Access app data through tool calls, never hidden-file reads/copies/parsing or
  `get_state()` as planner context. Require a valid catalog before environment creation.
- **FR-007**: Use one general planner in a bounded structured ReAct loop. Validate
  action shape, eligibility, and arguments deterministically with the organizer's
  schema validator before dispatch; feed observations into subsequent decisions.
- **FR-008**: Distinguish finish, missing-information, valid empty outcome, and failure.
  Invalid proposals are traced and may be corrected within the action bound before
  execution. Every actual environment call, including rejected calls, remains logged.
- **FR-009**: Never automatically retry uncertain executions or recreate failed
  sample environments. Historical actions remain context only.
- **FR-010**: Emit rows with exactly `id`, `tool_calls` (`name`, `arguments`), and
  `state_hash`, obtained unchanged from the environment.
- **FR-011**: Required traces record input mode/text, available tool names, planner
  actions, validation, actual calls/results, timing, errors, stop reason, and available
  authoritative log/hash. Mark bounds/redaction explicitly; hidden reasoning is not required.
  Detailed baseline inspection explicitly enables data-bearing debug payloads;
  default metadata traces mark omitted payloads instead of logging raw data silently.
  Metadata-only runs do not satisfy the detailed baseline-validation evidence requirement.
- **FR-012**: Stop the batch at its first execution failure, preserve earlier results
  and failure evidence, and exit nonzero. Never fabricate empty results or hashes for
  failures or mark incomplete output complete.
- **FR-013**: Keep trace, manifest, and prediction artifacts local and separate.
  Record selection, split, revision, configuration, model identities, decoding/seed,
  timing, coverage, and completion status. Preserve earlier run directories.
- **FR-014**: Support real offline planner/ASR adapters using local weights,
  deterministic decoding, and benchmark model/context limits. Reuse loaded models;
  fail clearly when dependencies or weights are unavailable.
- **FR-015**: Transcribe current and historical user audio in audio mode. Preserve
  ordered assistant text and supplied historical calls/results without execution.
  Transcript-versus-ASR comparisons use training records only.
- **FR-016**: Enforce finite model/tool steps and a configurable sample deadline;
  record overruns and distinguish slower development runs from benchmark compliance.
- **FR-017**: Include focused automated boundary tests, GPU-free controlled integration
  checks, and opt-in real-sample smoke validation. Pipeline/test code must not read
  hidden state. Real-model evidence must be reported separately.

### Key Entities

- **Sample input**: selected identity, context, request, and history.
- **Planner action**: structured decision to call a tool or finish.
- **Observation**: validation feedback or a tool result associated with an action.
- **Sample outcome**: completion category with authoritative result, or explicit failure.
- **Execution trace**: ordered observable evidence for a sample.
- **Run manifest**: selection, provenance, timing, coverage, and completion status.

## Success Criteria

### Measurable Outcomes

- **SC-001**: A selected training sample produces a parseable result whose call list
  and hash exactly equal the environment values captured for that execution.
- **SC-002**: Controlled checks demonstrate result-dependent lookup-to-action,
  missing-information, unsupported empty outcomes, forbidden tools, malformed output,
  and uncertain-execution failure without duplicate environment creation or effects.
- **SC-003**: Every started sample has a trace or an explicitly reported storage
  failure; successful samples have complete terminal trace events. Baseline-validation
  runs explicitly enable detailed debug payloads; metadata-only evidence is insufficient.
- **SC-004**: Failure injection proves later queued samples are not invoked, earlier
  completed rows remain available, and no complete result is published.
- **SC-005**: Record actual pretrained-planner transcript runs and planner+ASR audio
  runs separately on the four uploaded training IDs with complete assets once compute
  and weights are available. Report individual behavior/timing; no unmeasured accuracy
  or 30-second performance threshold is claimed.
- **SC-006**: Completed subsets have one result per selected ID and explicit subset
  coverage. Full submission readiness requires all split IDs, audio mode, and separately
  verified organizer constraints.

## Assumptions and Scope

- First validate a few uploaded training samples, initially `train_1748` through
  `train_1751`; implementation checks their asset completeness.
- Preserve supplied runtime implementations, Vietnamese catalogs, and original environment
  directories. Layout preparation may add a contained directory alias for the expected
  spelling and place the unchanged catalog at its expected split path; our code must
  not inspect or copy environment contents.
- GPU access and local model snapshots are external execution prerequisites, not
  unresolved product behavior. Controlled checks do not substitute for SC-005.
- Include Python CLI/library and sequential model reuse. Defer TypeScript integration,
  stdin worker-protocol implementation, HTTP/UI, full Docker submission, fine-tuning,
  specialist agents, and latency optimization. Keep the agreed runtime boundaries intact.
- Follow ADRs 002, 003, 005, and 007-010. Completing this spec is not implementation
  approval or a claim of working behavior.
