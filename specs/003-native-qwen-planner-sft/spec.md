# Feature Specification: Native Qwen planner and supervised fine-tuning

**Feature**: `003-native-qwen-planner-sft`
**Created**: 2026-10-31
**Status**: Planned; implementation and model experiments have not run.
**Input**: Adopt Qwen native function calling before next-action SFT; optimize the
competition benchmark while keeping the entire audio pipeline below 30 seconds.

## Clarifications and scope

Decisions accepted in the design interview:

- Use Qwen3-4B-Instruct-2507 as the initial candidate, with native tool messages and
  outputs at the model boundary and the existing canonical executor decisions inside Python.
- Generate one call per decision; use a completed short native assistant response
  for termination. Reject malformed, incomplete, or multiple-call outputs explicitly.
- Compare current and native protocols before fitting. Use frozen grouped Train
  validation, comparing supplied transcripts and ASR separately.
- Fit only supplied Train gold trajectories initially. Supervise only the next
  action completion. Use all-linear LoRA, or QLoRA when measured memory requires it.
- Select on the competition benchmark with full-pipeline latency as a constraint.
  GRPO, synthetic augmentation, and recovery-data training are separate later work.
- “Five tuning rounds” was a transcription error; there is no fixed round count.

## User Scenarios & Testing

### User Story 1 — Execute native Qwen tool decisions (Priority: P1)

As a pipeline developer, I can use Qwen's native function-calling conversation
format without changing the organizer execution or submission contract.

**Why this priority**: Training must match the actual inference protocol.

**Independent Test**: Tokenizer-rendered fixtures and a controlled planner execute
a lookup followed by an action, preserving exact arguments, observations and logs.

**Acceptance Scenarios**:

1. **Given** a request requiring a contact ID, **when** the planner searches and
   receives a result, **then** the next native call can use that observed ID; no
   future result enters the earlier prompt.
2. **Given** installed-tool definitions, **when** the native prompt is rendered,
   **then** only eligible tools plus `sys.ask_missing_info` are exposed, with exact
   names, Vietnamese descriptions and parameter constraints.
3. **Given** one complete native call, **when** it is parsed, **then** exactly one
   canonical decision reaches the existing runner and any actual attempt is logged
   by the sample's one ToolEnv.
4. **Given** a completed no-call assistant turn, **when** it terminates normally,
   **then** the runner finishes without adding a synthetic benchmark call.
5. **Given** malformed, truncated or multiple-call output, **when** it is rejected,
   **then** no call from that response is executed and it is not treated as finish.

### User Story 2 — Measure the protocol change (Priority: P1)

As a model developer, I can compare the current and native protocols before
training and attribute results to formatting rather than weight updates.

**Independent Test**: A report compares identical source IDs and checkpoint under
both protocols, recording coverage, scoring availability and full-attempt timing.

**Acceptance Scenarios**:

1. **Given** a frozen grouped split, **when** the two protocols run, **then** the
   checkpoint, decoding, installed tools, execution policy and sample IDs match;
   only the documented protocol factor changes.
2. **Given** supplied transcripts and ASR inputs, **when** results are evaluated,
   **then** planner-only and full audio results are reported separately.
3. **Given** unavailable official scoring or missing latency evidence, **when** a
   report is produced, **then** it explicitly states the unavailable result rather
   than presenting diagnostics as the competition score or A30 compliance.

### User Story 3 — Export auditable next-action training data (Priority: P2)

As a training developer, I can convert fit-partition gold trajectories into native
Qwen prompt-completion rows with correct supervision and no label leakage.

**Independent Test**: Export fixtures cover lookup/action, empty gold, clarification,
history, invalid gold and long prompts; actual tokenizer masks select only targets.

**Acceptance Scenarios**:

1. **Given** grouped source partitions, **when** trajectories expand into steps,
   **then** all derived rows retain their source group and validation never enters fit.
2. **Given** target call k, **when** its row renders, **then** only calls/results
   strictly before k are visible and the target is one native assistant tool call.
3. **Given** ordinary completion or empty gold, **when** a finish target is exported,
   **then** it is a short native no-call assistant completion. Successful terminal
   missing-information calls have no additional finish target.
4. **Given** malformed pairings, unexplained IDs or context overflow, **when**
   audited, **then** exclusions carry explicit reasons; the exporter invents no IDs
   or targets and reads no environment files.

### User Story 4 — Fit and evaluate a planner adapter (Priority: P3)

As a model developer, I can train a reproducible adapter and evaluate the exported
candidate through the actual execution loop against the unchanged base model.

**Independent Test**: A fit-only smoke run saves and reloads an adapter; closed-loop
evaluation uses model predictions and actual tool results, never gold prefixes.

**Acceptance Scenarios**:

1. **Given** a hardware/memory preflight and audited fit artifact, **when** fitting
   starts, **then** a pinned training configuration records all-linear LoRA or NF4
   QLoRA, package/model/data identities, seed, masks and measured memory.
2. **Given** saved candidates, **when** one is proposed for promotion, **then** its
   actual deployment export is compared with the same native-protocol base on the
   same validation cases using benchmark outcomes and whole-pipeline timing.
3. **Given** no demonstrated gain, reproducibility, eligibility or deadline evidence,
   **when** experiments end, **then** the base remains the fallback; completing the
   training infrastructure does not imply a successful model.

### Edge Cases

- Incomplete delimiter or JSON, duplicate keys, non-finite numbers, extra payload,
  prose mixed with a call, multiple calls, or token/time exhaustion.
- Empty no-call output versus a deliberate completed final response.
- Empty search, `done:false`, schema rejection, and uncertain execution.
- `sys.ask_missing_info` with true, false, absent or unsuccessful waiting results.
- Catalog extension semantics, zero-argument functions, Unicode names and arguments.
- Historical calls already executed, and rejected proposals that were never executed.
- Gold that continues after terminal clarification; long histories; duplicate groups.
- Optional selection-filter feedback, mixed checkpoint identities, and exported
  quantization changing predictions or latency.

## Requirements

### Functional Requirements

- **FR-001**: Render tools, calls and observations using the selected checkpoint's
  pinned native chat template, with identical training/inference serialization.
- **FR-002**: Preserve the existing `Planner.next_action` canonical call/finish
  interface and Python ownership of execution; native parsing belongs to the adapter.
- **FR-003**: Accept at most one complete eligible native call per decision; validate
  bounded output strictly and reject ambiguous, malformed or unfinished responses.
- **FR-004**: Distinguish normal no-call completion from token/deadline cuts and
  failures; termination adds no organizer tool.
- **FR-005**: Preserve single-environment execution, authoritative attempts/hash,
  schema-error logging, missing-info termination and uncertain-execution policy.
- **FR-006**: Preserve all sample evidence and catalog semantics; validation feedback
  must not impersonate a result of an executed tool.
- **FR-007**: Version protocol, prompt, template and constraint identities in run
  provenance/checkpoint compatibility, with explicit baseline/native selection.
- **FR-008**: Compare protocols on a frozen source-group partition before SFT and
  keep transcript and ASR modes separate.
- **FR-009**: Export initial SFT rows from supplied Train fit only, following the
  [gold conversion design](../../docs/design/train-to-sft.md), with native targets.
- **FR-010**: Mask every token outside the final target completion and its ending
  token; audit masks with the actual tokenizer and reject destructive truncation.
- **FR-011**: Record export provenance, distributions, context lengths, exclusions,
  duplicate/group separation and target grounding before fitting.
- **FR-012**: Provide isolated, pinned optional training dependencies, all-linear
  LoRA/QLoRA configuration, deterministic seeds, saving and deployment loading.
- **FR-013**: Evaluate actual exported candidates closed-loop against the native base;
  teacher-forced diagnostics cannot substitute for competition evaluation.
- **FR-014**: Keep data/weights/traces ignored and final inference offline; enforce
  model-size/context restrictions and measure full audio pipeline below 30 seconds.
- **FR-015**: Include focused behavioral verification for native protocol parsing,
  constraints, execution invariants, exporter leakage/masks and adapter reload.

### Key Entities

Protocol profile; native conversation; parsed native decision; source partition;
SFT row; export manifest; training configuration; candidate evaluation record.
See [data-model.md](data-model.md).

## Success Criteria

- **SC-001**: All protocol acceptance fixtures produce the specified decision or
  explicit rejection, with zero unintended dispatches.
- **SC-002**: Integrated controlled cases preserve exact authoritative calls and
  single-environment counts, including failed argument attempts and clarification.
- **SC-003**: Export audit finds zero cross-partition groups, future-result leaks,
  unmasked non-target tokens, or silently truncated required evidence in accepted rows.
- **SC-004**: A fit-only smoke adapter saves/reloads and executes the native protocol
  under the intended inference stack with recorded provenance.
- **SC-005**: Protocol and tuned/base comparisons report identical coverage or
  explicit exclusions, score availability and measured latency. Model promotion
  requires a higher supported benchmark result and strict <30-second full attempts
  on the target hardware; infrastructure completion is independent of promotion.

## Assumptions and exclusions

The supplied benchmark brief is the current requirements reference. Train data,
official scoring access and training hardware may require receiving-machine work;
their availability is checked before dependent experiments. No performance result
is established here. Feature 002 measurement/reporting source and controlled-test
evidence are present on the publication base; real model/GPU/evaluator acceptance
still requires execution. Parallel tool execution, ASR training,
synthetic data, DPO/GRPO, model-family search and TypeScript transport are excluded.
