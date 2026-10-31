# Tasks: Native Qwen planner and supervised fine-tuning

**Input**: [spec](spec.md), [plan](plan.md), [research](research.md),
[data model](data-model.md), [contracts](contracts/), [quickstart](quickstart.md).
All tasks are unchecked. Tests are explicitly required by FR-015. Task completion
requires the stated behavior and recorded checks, not just authored source.

## Phase 1: Setup

- [ ] T001 Record baseline revision, existing dirty-file boundaries, dataset/model availability and feature 002 measurement status in `specs/003-native-qwen-planner-sft/validation.md`; do not claim absent runs passed.

## Phase 2: Foundational contracts

- [ ] T002 Add explicit protocol configuration/default and preflight compatibility in `python/src/lifemate/contracts.py` and `python/src/lifemate/cli.py`, retaining structured control and rejecting incompatible profile/example combinations.
- [ ] T003 Extend resolved protocol/prompt/template/constraint execution identity in `python/src/lifemate/artifacts.py`, `python/src/lifemate/provenance.py` and `python/src/lifemate/checkpoint.py`; keep structured feature 002 identity compatible.

## Phase 3: US1 — Native protocol MVP (P1)

**Goal**: Native model conversation with unchanged canonical executor authority.
**Independent test**: Lookup/result/action and finish/clarification fixtures preserve
exact authoritative attempts, single ToolEnv and no unintended dispatch.

- [ ] T004 [US1] Add strict native output/termination fixtures in `python/tests/test_qwen_protocol.py` for calls, finish, Unicode, zero args, malformed/multiple/prose output, duplicate keys and token/time cuts.
- [ ] T005 [US1] Implement shared native function/message serialization and strict decision decoding in `python/src/lifemate/adapters/qwen_protocol.py`, preserving extensions, tool whitelist and historical-data interpretation.
- [ ] T006 [US1] Add native system policy and protocol-aware rendering in `python/src/lifemate/prompting.py`, separating actual tool results from correction feedback without changing structured control rendering.
- [ ] T007 [US1] Implement native single-call plus neutral-final LMFE branches in `python/src/lifemate/adapters/constrained.py`, preserving tool/schema binding and admitting EOS only after complete branches.
- [ ] T008 [US1] Wire native tools/rendering/grammar and token-ID EOS detection into `python/src/lifemate/adapters/planner.py`; normalize to canonical decisions and retain existing hard adapter failure/deadline behavior.
- [ ] T009 [US1] Preserve selection-filter JSON behavior and native rejection feedback in `python/src/lifemate/adapters/planner.py`; verify rejected proposals never appear as executed native tool results.
- [ ] T010 [US1] Add bounded native-output/EOS/canonical trace metadata and provenance in `python/src/lifemate/adapters/planner.py` and `python/src/lifemate/agent.py` without changing authoritative submission or routine payload logging.
- [ ] T011 [US1] Add and run execution invariants and native adapter integration in `python/tests/test_agent.py` and `python/tests/test_inference.py`, including schema-rejected attempts, done:false, empty finish, missing-info variants and uncertain execution.
- [ ] T012 [US1] Add and run protocol CLI/preflight/resume tests in `python/tests/test_cli.py` and `python/tests/test_checkpoint.py`, rejecting mixed-protocol acceptance populations and mismatched template identities.
- [ ] T013 [US1] Run actual local tokenizer/LMFE grammar and supplied-runtime smoke cases from `python/tests/test_qwen_protocol.py` and `python/tests/test_real_samples.py`; record commands/assets/results or precise external blockers in `specs/003-native-qwen-planner-sft/validation.md`.

**Checkpoint**: US1 is the smallest runnable feature; it needs no training packages.

## Phase 4: US2 — Protocol comparison and SFT gate (P1)

**Goal**: Freeze source groups and measure protocol effects before fitting.
**Independent test**: Same IDs/checkpoint/non-factor settings, complete coverage or
explicit missing evidence, transcript/audio separated and full-attempt timings.

- [ ] T014 [US2] Implement CPU-only frozen grouped Train partition with exact/near-duplicate and shared-template audit, reusing `python/src/lifemate/prompt_profiles.py` partition-v1 validation in `python/src/lifemate/training/data.py` and `python/src/lifemate/training/__main__.py`, with standard-library-only partition imports and no overwrite.
- [ ] T015 [US2] Add and run partition/source-identity/group-separation checks in `python/tests/test_training_data.py`, including fit-side roadmap smoke groups, near-duplicate candidate decisions, related conversation/templates and transitive unions.
- [ ] T016 [US2] Record frozen partition, eligible checkpoint/runtime/catalog and actual baseline configuration under `.agent-work/lifemate-runs/native-sft/`; summarize identities and evaluator/report availability in `specs/003-native-qwen-planner-sft/validation.md`.
- [ ] T017 [US2] Extend factor validation and CLI choices with protocol/planner-model comparisons in `python/src/lifemate/reporting.py` and `python/src/lifemate/cli.py`; test narrowly allowed differences and forbidden ASR/template/budget drift in `python/tests/test_reporting.py` and `python/tests/test_cli.py` without weakening existing factors.
- [ ] T018 [US2] Run paired structured/native transcript and audio validation with feature 002 reports into `.agent-work/lifemate-runs/native-sft/`; include all selected IDs, score availability, malformed/extra calls and full-attempt latency.
- [ ] T019 [US2] Record protocol decision, per-sample regressions, recurring transcript planner errors and conditional SFT eligibility in `specs/003-native-qwen-planner-sft/validation.md`; missing evaluator evidence blocks score promotion.

## Phase 5: US3 — Auditable native SFT data (P2)

**Goal**: Fit-only next-action rows with runtime parity and verified token masks.
**Independent test**: Strict-prefix sentinels, source groups, terminal/empty cases,
grounding exclusions and actual tokenizer final-completion masks.

- [ ] T020 [US3] Add export fixtures for future-result leakage, label whitelist, native target parity, history, clarification, invalid gold and overflow in `python/tests/test_training_data.py`.
- [ ] T021 [US3] Implement fit-only gold-prefix conversion, ID-grounding/pairing/terminal audits and declared policy-finish provenance in `python/src/lifemate/training/data.py`, using no environment access.
- [ ] T022 [US3] Add `export` command and source/partition/template identities, exclusions, distributions and immutable artifact outputs in `python/src/lifemate/training/__main__.py` and `python/src/lifemate/training/data.py`.
- [ ] T023 [US3] Implement actual-tokenizer target/EOS-only labels, prompt/completion boundary checks and context/output-budget exclusions in `python/src/lifemate/training/data.py`, sharing native runtime rendering.
- [ ] T024 [US3] Run leakage/mask/rendering/coverage audits against actual tokenizer and supplied fit data; save manifests under `.agent-work/lifemate-runs/native-sft/sft/` and sanitized evidence in `specs/003-native-qwen-planner-sft/validation.md`.
- [ ] T025 [US3] Reconcile native target serialization and accepted all-linear LoRA/conditional QLoRA method in `docs/design/train-to-sft.md` while retaining the existing single source of truth for conversion invariants and clearly marking implementation evidence limits.

## Phase 6: US4 — Controlled adapter fitting and deployment evaluation (P3)

**Goal**: Fit/save/reload adapter and compare its actual deployment export with native base.
**Independent test**: Fit-only smoke plus inference-environment reload and closed-loop
predicted calls/real observations; no promotion on teacher-forced metrics alone.

- [ ] T026 [US4] Establish isolated one-batch compatible training environment and exact `python/requirements-training.txt` lock; record GPU/BF16/VRAM and method-selection evidence in `specs/003-native-qwen-planner-sft/validation.md` before a real fit.
- [ ] T027 [US4] Implement validated config, audited-input gate, all-linear LoRA/NF4 QLoRA, target-only training, deterministic seed and memory preflight in `python/src/lifemate/training/fit.py` with lazy optional imports.
- [ ] T028 [US4] Add fit command, checkpoint/provenance/failure manifests and adapter save/reload in `python/src/lifemate/training/__main__.py` and `python/src/lifemate/training/fit.py`; preserve checkpoint selection evidence.
- [ ] T029 [US4] Implement original-base verification and self-contained merge/export in `python/src/lifemate/training/export.py` and its command in `python/src/lifemate/training/__main__.py`, refusing mismatches/overwrite and copying exact tokenizer identity.
- [ ] T030 [US4] Add and run config/input rejection, mask audit, dependency isolation, fit-only smoke/save/reload/merge checks in `python/tests/test_training_fit.py`; verify base/protocol mismatch rejection and recorded memory.
- [ ] T031 [US4] Execute eligible controlled fit and actual merged-export native transcript/audio comparisons under `.agent-work/lifemate-runs/native-sft/`; record full coverage, evaluator evidence and per-ID regressions in `specs/003-native-qwen-planner-sft/validation.md`.
- [ ] T032 [US4] Measure actual export on offline A30 audio pipeline, model/context budgets and deterministic reruns; record promotion or retained-base outcome and unavailable gates in `specs/003-native-qwen-planner-sft/validation.md`.

## Phase 7: Documentation and handoff

- [ ] T033 Update `python/README.md`, `context/architecture.md` and `context/tech_stack.md` with implemented protocol/training usage and measured evidence only; retain baseline control and unresolved experiment trade-offs.
- [ ] T034 Run implemented checks from `specs/003-native-qwen-planner-sft/quickstart.md` at their applicable scope; record exact commands, passes/failures/external blockers in `specs/003-native-qwen-planner-sft/validation.md` without treating partial acceptance as complete.
- [ ] T035 Review requirement-to-task coverage, documentation links and ignored data/weight boundaries in `specs/003-native-qwen-planner-sft/validation.md` and link the authorized issue/PR when one exists; do not publish datasets or claim unrun acceptance.

## Dependencies and implementation strategy

T001 -> T002–T003 -> US1 -> US2 -> US3 -> US4 -> handoff. Export engineering may
proceed after native rendering/partition acceptance; full fitting additionally requires
T019 and T026. Missing hardware/scorer/reporting blocks dependent measured acceptance,
not independent controlled engineering. Keep every blocked acceptance task unchecked.
Feature 002 measurement/reporting foundation exists on the publication base; its
real-runtime acceptance is external and is not established by this task list.

**MVP**: Stop after US1's actual-tokenizer/runtime verification; then obtain US2 evidence
before committing compute to fitting. Introduce one experiment factor at a time.

## Parallel opportunities

Tasks are intentionally unmarked `[P]` because core edits share files and evidence
gates. Independent read-only work can run alongside implementation after prerequisite
contracts settle: US1 malformed-parser review versus runner-invariant review; US2
scorer availability versus hardware readiness; US3 exclusion review versus mask review;
US4 license/provenance audit versus deployment timing preparation. Do not parallelize
shared-GPU experiments or edits to the same files without explicit ownership.

## Coverage

FR-001–006: T004–T011; FR-007: T002–T003/T012;
FR-008: T014–T019; FR-009–011: T020–T025;
FR-012: T026–T030; FR-013–014: T031–T032;
FR-015: T004/T011–T013/T015/T020/T024/T030/T034.
