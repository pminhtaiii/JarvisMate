# Feature Specification: Configurable offline Docker integration

**Feature Branch**: `codex/005-docker-integration`
**Created**: 2026-11-06
**Status**: Planned; implementation and GPU acceptance pending
**Input**: Agreed grilling decisions: preserve the existing runner; integrate ASR,
native Qwen tool calling and execution in one offline container; selectable models
and GPU settings; transcribe each distinct clip once; enforce 30 seconds per sample;
diagnose empty-call and missing-information behavior. ASR training is separate.

## User Scenarios & Testing

### User Story 1 - Run audio through native tool execution (Priority: P1)

As a contributor, I can run selected samples using my ASR and Qwen checkpoints
without changing orchestration or repeating speech recognition during planning.

**Why this priority**: This is the requested integration baseline.

**Independent Test**: A controlled audio sample with a lookup-dependent second call
produces expected authoritative calls/hash using one ASR invocation per distinct clip
and one environment. Real-model acceptance is separate and uses supplied Train.

**Acceptance Scenarios**:

1. **Given** one current WAV and a three-decision loop, **when** the sample runs,
   **then** ASR transcribes that WAV once and every decision reuses its transcript.
2. **Given** historical audio with repeated clip references, **when** request preparation
   runs, **then** each distinct clip is transcribed once, history order is preserved,
   and historical calls are never executed again.
3. **Given** a lookup needed by a later call, **when** the planner continues, **then**
   native messages contain the actual preceding call/result pair; code owns dispatch.
4. **Given** the legacy CLI, **when** its existing checks run, **then** the new integration
   has not changed its default prompt/protocol/execution contracts.

### User Story 2 - Bound the complete sample attempt (Priority: P1)

As a contributor, I can stop overruns without confusing timeout with a valid empty
result or silently replaying uncertain effects.

**Why this priority**: The 30-second constraint is the primary acceptance criterion.

**Independent Test**: Inject blocked ASR, planner, tool and output operations; the
supervisor expires attempts, rejects late results, and recovers for a different sample.

**Acceptance Scenarios**:

1. **Given** ready models, **when** a sample is dispatched, **then** one deadline covers
   preparation, ASR, environment creation, LLM turns, execution, collection, trace
   closure and durable per-sample output.
2. **Given** a blocked worker, **when** the deadline expires, **then** its process group
   is terminated and late output is quarantined. A complete-looking response is not success.
3. **Given** uncertain effects, **when** the batch continues, **then** the failed sample
   is not retried and receives no replacement environment.
4. **Given** recovered models, **when** the next distinct sample begins, **then** it gets
   its own deadline; reload/recovery remains visible in total run wall time.

### User Story 3 - Deploy and switch models without code edits (Priority: P1)

As a contributor, I can launch one container on an available GPU and replace compatible
model snapshots/settings while retaining reproducible run identity.

**Why this priority**: Integration must fit the actual infrastructure.

**Independent Test**: Use the same image with two compatible checkpoint configurations
and a selected visible GPU; verify effective settings and offline inference.

**Acceptance Scenarios**:

1. **Given** mounted snapshots and split data, **when** networking is disabled,
   **then** the container loads locally and processes selected samples.
2. **Given** a compatible replacement model, **when** its path changes, **then** no
   Python edit/image rebuild is needed; provenance changes and mixed resume is rejected.
3. **Given** another GPU host, **when** device/precision/offload changes, **then** no
   hard-coded A30 model or GPU index prevents the run.
4. **Given** an incompatible model or invalid configuration, **when** preflight runs,
   **then** it fails before creating a sample environment.

### User Story 4 - Diagnose empty and missing-information cases (Priority: P2)

As a contributor, I can distinguish speech, planner and rare-case failures before
deciding whether to rebalance or fine-tune again.

**Why this priority**: Overall metrics can hide these behaviors; training is deferred.

**Independent Test**: Controlled empty, unnecessary-call, clarification-argument and
clarification-after-earlier-call cases; paired transcript/audio reports with denominators.

**Acceptance Scenarios**:

1. **Given** no installed app supports a request, **when** Qwen completes without calls,
   **then** the output uses the environment's empty log and actual hash.
2. **Given** required information unavailable from context and eligible lookups,
   **when** Qwen requests it, **then** `sys.ask_missing_info` is an executed/scored call
   with the intended tool and missing parameter names.
3. **Given** clarification returns `ok: true, waiting_for_user: true`, **when** execution
   returns, **then** the loop stops without another LLM turn.
4. **Given** malformed/truncated output, timeout or crash, **when** reporting runs,
   **then** it remains a failure, never a successful empty prediction.

### Edge Cases

- Repeated clip references, identical audio at different paths, missing/corrupt WAVs,
  supplied historical text and ASR producing empty text.
- Multiple native calls, prose, duplicate keys, fabricated names, non-object arguments,
  missing terminators and generation ending at the token limit.
- Discoverable missing details, ambiguous lookups, unsuccessful clarification,
  and clarification after earlier successful calls.
- Schema-rejected calls remain in the authoritative attempted-call log.
- Context overflow, OOM, worker crash, blocked storage, late/stale acknowledgements.
- Failed worker recovery stops nonzero with prior accepted results retained.

## Requirements

### Functional Requirements

- **FR-001**: Add a separate integration entry point reusing existing ASR/planner/executor
  boundaries. Retain the legacy structured runner for comparison.
- **FR-002**: Transcribe each distinct required audio clip at most once per sample;
  reuse across references and planner turns. Distinct historical clips may require
  additional transcriptions; all count toward the same sample deadline.
- **FR-003**: Use the selected Qwen tokenizer/chat template and native tool messages;
  accept one call per decision or an explicit valid no-tool completion.
- **FR-004**: Expose only installed-app tools plus `sys.ask_missing_info`. Feed actual
  call/results back before the next decision. The model cannot author execution results.
- **FR-005**: Create one split-matched `ToolEnv` per attempted sample; obtain submission
  calls/hash from it. Access app data only through tools; exclude labels/future results
  from inference.
- **FR-006**: Deterministically validate model output/eligibility and bound execution.
  Delegate argument-schema validation/logging to ToolEnv; never retry uncertain effects,
  restart a failed sample or drop attempted calls.
- **FR-007**: Independently supervise a maximum 30-second full sample attempt, including
  durable per-sample output. Accept success only strictly before expiry. Shorter budgets
  may be configured; longer ones are rejected by this new entry point.
- **FR-008**: Distinguish completed, needs-info, timeout and failed attempts. Continue
  to distinct samples after isolated failures; stop if bounded recovery fails. Retain
  failures, exit nonzero for incomplete runs and block complete-submission publication.
- **FR-009**: Load models once per healthy worker. Report startup/recovery and final
  batch packaging separately and include them in total wall time. Confirm organizer
  timing/accounting rules before claiming submission readiness.
- **FR-010**: Configure local model paths, device, precision, explicit offload,
  context/output/step bounds and selection. Reject unknown options and incompatible
  configurations; record effective settings and identities.
- **FR-011**: Support Whisper/PhoWhisper-compatible ASR snapshots and compatible Qwen3
  causal snapshots with native tool templates. Fine-tuned exported snapshots are valid
  inputs; training, adapter merging and arbitrary architecture support are excluded.
- **FR-012**: Provide one offline Docker image; install dependencies at build time;
  use read-only model/data mounts and writable output. Select one GPU at launch.
- **FR-013**: Record per-clip ASR counts/times, per-decision LLM time/tokens, tool time,
  collection/output time, full attempt time and stop reasons. Routine logs omit payloads;
  explicit dataset-debug traces follow existing testing guidance.
- **FR-014**: Evaluate a fixed recorded Train selection with frozen group-disjoint
  validation where applicable. Report empty and clarification behavior with denominators,
  false empty and unnecessary clarification errors. Gold is offline-evaluation-only.
  Do not fabricate unavailable score/hash metrics.
- **FR-015**: Exclude model training, rebalancing, synthetic data generation, HTTP/UI,
  multi-server serving, model sharding and TypeScript transport from this feature.
- **FR-016**: Record parameter counts/context use; competition acceptance requires
  total models <6B, planner <5B, context <=16,384, deterministic offline inference
  and a hardware-identified timing report.
- **FR-017**: Include focused behavioral verification of these non-trivial boundaries
  and injected failure paths; real checkpoints/GPU/container runs are separate gates.

### Key Entities

- **Integration configuration**: Models, hardware, inference settings and run selection.
- **Prepared request**: Current text, ordered history and per-distinct-clip transcripts.
- **Native decision**: One eligible call or terminated no-tool completion.
- **Sample attempt**: Unique identity, shared deadline, worker generation and status.
- **Run evidence**: Authoritative predictions, attempt ledger, timings and diagnostics.

## Success Criteria

- **SC-001**: Controlled multi-turn cases demonstrate one transcription per distinct
  clip, no history replay, one environment and exact expected calls/hash.
- **SC-002**: Every accepted attempt has measured full duration <30 seconds; injected
  overruns accept no late result and never retry the failed sample. Record process
  termination overshoot rather than claiming instantaneous cancellation.
- **SC-003**: The same image handles compatible model swaps and selected GPU settings
  fully offline, with effective configuration and model identities recorded.
- **SC-004**: Real acceptance selection covers single-call, dependent multi-call,
  empty-gold, missing-info and historical audio, or explicitly reports missing coverage.
  Report every failure and category denominator without promising model accuracy.
- **SC-005**: Compare baseline/integration on paired IDs, models and hardware where
  protocols allow; report correctness, latency distribution/max and timeout counts.
  Promote optimizations only with measured paired evidence.

## Assumptions and External Acceptance Gates

- Base: `fine-tuned-asr` at `f9226c41e6504437c51f13726a5f6eee2d8c4537`, matching the
  cached JarvisMate remote ref at planning time; no live fetch is claimed.
- User supplies local snapshots, split assets and GPU access. Actual paths/hardware
  are run inputs, not design blockers. Model compatibility must be checked.
- A30 is the supplied competition reference, not a deployment constant. Other-GPU
  results demonstrate only the measured development hardware.
- Organizer startup/warm-up accounting and permitted failed-row representation need
  final confirmation. Until then, disclose overheads and block complete publication
  if any sample fails; never invent a failure row or state hash.
- This feature owns integration. Existing 002 measurement and 003 native/SFT drafts
  are references, not dependencies requiring training implementation.
