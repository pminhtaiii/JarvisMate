# Feature Specification: Native planner QLoRA SFT baseline

**Branch**: `codex/006-planner-sft-baseline`
**Created**: 2026-11-06
**Status**: Planned; implementation, training and acceptance pending.

## Agreed scope

Deliver one Qwen3-4B-Instruct-2507 supervised fine-tuning baseline using NF4 +
LoRA, supplied clean transcripts and gold next-action targets. Train on all of the
designated training set; keep the existing separate validation set excluded from
training. Paths are configurable execution inputs. The runtime generates one call,
executes it, appends its actual result and generates the next action directly,
without reflection, critique or a separate judgment pass.

The supplied image is a recipe reference. Its counts, ASR views, epoch estimate,
validation NLL and best step are unverified and are not results of this feature.

## User Scenarios & Testing

### User Story 1 - Export faithful next-action data (Priority: P1)

A contributor converts designated train/validation trajectories into auditable
native examples without future-result leakage or a new holdout split.

**Independent test**: Controlled lookup/action, empty and clarification trajectories
produce exact targets/prefixes; overlapping datasets and malformed sources fail.

**Acceptance scenarios**:

1. Each call target sees only its strictly previous call/result pairs.
2. All derived validation rows stay validation-only; training is not repartitioned.
3. Only final-completion and terminal tokens receive loss, including when history
   contains earlier assistant messages.
4. Invalid/over-budget sources are explicitly audited and block readiness until
   resolved; no silent exclusion or target truncation occurs.

### User Story 2 - Train one reproducible adapter (Priority: P1)

A contributor trains the fixed recipe on one RTX 5090 or H200 and retains data,
environment, checkpoint and optimizer identities.

**Independent test**: Real-checkpoint short training proves finite loss, adapter
gradients, frozen base weights, effective batch 16 and matching checkpoint restore.

**Acceptance scenarios**:

1. Validation never contributes gradients, examples or augmentation to training.
2. Hardware-dependent microbatch/accumulation preserves effective batch 16.
3. Explicit resume restores optimizer/scheduler/RNG/data progress only for matching
   committed checkpoints. Incompatible CUDA or OOM fails without changing the recipe.

### User Story 3 - Export and assess the deployable baseline (Priority: P1)

A contributor exports a standalone FP16 snapshot for feature 002 and measures
executed behavior and complete audio latency on the separate validation set.

**Independent test**: Offline merged reload without training libraries, actual
tokenizer/native protocol checks and executed calls/hash on fixed validation IDs.

**Acceptance scenarios**:

1. A deterministic recorded rule selects one saved checkpoint using validation
   diagnostics; NLL is kept distinct from the competition score.
2. Export merges the adapter into a fresh unquantized original base and preserves
   model/tokenizer/template identities.
3. Feature 002 evaluates actual predicted calls/results and complete sample times;
   absent scorer/reference hashes are reported unavailable, never fabricated.

### Edge cases

Cross-dataset duplicate IDs/conversations/inputs; test data declared validation;
unequal calls/results; unavailable tools; ungrounded IDs; calls after terminal
clarification; empty gold; schema-invalid targets; template/EOS mismatch; all-masked
targets; pad equal to EOS; overflow; partial batches; OOM; interrupted checkpoints;
unsupported GPU kernels; quantized-to-FP16 export behavior differences.

## Functional Requirements

- **FR-001**: Accept explicit train, validation, catalog, local base and output
  paths; record identities and permitted development-data roles. Public/private
  competition test is excluded from tuning/checkpoint selection.
- **FR-002**: Use 100% of designated training sources with no new split, sampling
  or rebalance. Account for every source; unresolved exclusions block a full-data
  training-ready claim. Validation remains completely outside fitting.
- **FR-003**: Audit IDs, normalized visible-input duplicates and available source/
  conversation groups across sets before expansion. Fail on overlap, report missing
  grouping metadata and never silently repartition data.
- **FR-004**: Follow existing SFT semantic conversion rules using supplied transcripts,
  eligible tools and gold strict prefixes; replace its legacy JSON serialization
  with feature 002's native Qwen protocol. Preserve arguments and temporal context.
- **FR-005**: Supervise one next call or native finish. Empty gold emits one finish
  row. Successful waiting clarification emits no extra finish. History is context.
- **FR-006**: Share native message/termination rendering with feature 002 and verify
  actual tokenizer boundaries. Code owns eligibility, dispatch and stopping.
- **FR-007**: Mask everything except the final completion and terminal tokens;
  mask padding by position. Disable packing. Reject overflow without silently
  removing targets or required observations.
- **FR-008**: Implement the fixed recipe in the plan; train only LoRA A/B weights
  and verify module matches, frozen base/MLP/embedding/head and parameter counts.
- **FR-009**: Support one selected RTX 5090 or H200 with explicit batching and a
  compatible recorded software environment; no automatic recipe mutation on OOM.
- **FR-010**: Save resumable candidates and validation NLL every 100 updates through
  update 500. Record unique training-row/source coverage per checkpoint. Only
  checkpoints that have trained on every ready training row and source may be
  selected or exported; fail selection if no eligible finite-NLL candidate exists.
- **FR-011**: Export standalone merged FP16 from a fresh original unquantized base,
  retain adapter/provenance and verify offline reload/native compatibility.
- **FR-012**: Assess executed calls/state using supplied competition semantics where
  references/scorer exist, with separate empty/clarification/failure/timeout counts.
  NLL alone establishes neither a competition score nor checkpoint quality.
- **FR-013**: Gate deployment acceptance on deterministic offline full audio attempts
  strictly <30s, total models <6B, planner <5B and context plus reserved output
  <=16,384. Distinguish training/development GPU evidence from A30 acceptance.
- **FR-014**: Keep training packages/artifacts outside inference. ASR training,
  augmentation, synthetic data, searches, reflection and whole-chain targets are
  outside this baseline.
- **FR-015**: Include focused behavior checks for leakage/masks/terminal handling,
  checkpoint identities and merged reload. Actual GPU and runtime gates remain explicit.

## Success Criteria

- **SC-001**: Every source is accounted for, cross-role overlap is zero and controlled
  future-result leakage/masking checks pass.
- **SC-002**: One complete fixed-recipe run yields reloadable adapter candidates,
  a deterministic selection record and standalone merged FP16 planner.
- **SC-003**: Evidence identifies data, commands, revision, settings, hardware,
  failures, available scores and full sample timing; all accepted audio attempts
  complete strictly under 30 seconds on the measured hardware.
- **SC-004**: No numerical score floor is invented. Weak/unavailable scores are
  reported honestly and do not establish competitive performance.

## Dependencies and user-authorized changes

Feature 002 owns native inference, execution, offline Docker and deadline supervision;
its implementation remains pending. Training/export can progress after the shared
native boundary exists; complete audio acceptance depends on that runtime.
User direction authorizes tuning now despite the older conditional roadmap gate,
and replaces its internal 80/20 proposal with the existing separate validation set.
Paths, counts, license/release eligibility and GPU access are execution preflight
inputs, not unresolved design questions.
