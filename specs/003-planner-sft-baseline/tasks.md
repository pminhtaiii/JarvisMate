# Tasks: Native planner QLoRA SFT baseline

**Input**: [plan.md](plan.md), [spec.md](spec.md) and linked design contracts.
**Status**: Authoring tasks delivered; every execution gate below is pending. A checked task
means its code and controlled checks exist, not that real training or GPU acceptance ran.
**Tests**: Focused behavior checks required by FR-015; actual model/GPU gates separate.

## Phase 1: Setup

- [x] T001 Record user-authorized tuning, separate validation, native next-action format and no-reflection decisions in `docs/adr/012-native-planner-sft-baseline.md`; update conflicting feature-specific pointers in `context/roadmap.md` and `docs/design/train-to-sft.md` without claiming measured results.
- [x] T002 Define isolated training extra and compatible-version resolution procedure in `python/pyproject.toml` and `specs/003-planner-sft-baseline/quickstart.md`; preserve inference dependencies and keep training packages out of Docker runtime.

## Phase 2: Foundation

- [x] T003 Implement strict TOML configuration, fixed recipe, role/path validation, CLI stages and bounded stage errors in `python/src/lifemate/sft/__init__.py` and `python/src/lifemate/sft/__main__.py`.
- [x] T004 Add explicit local paths, selected device, microbatch/accumulation, token limits and ignored-output settings in `configs/planner-sft.example.toml`.
- [x] T005 Establish shared pure native rendering and exact finish/terminal contract in `python/src/lifemate/adapters/qwen_native.py`, coordinating feature 002 T008-T010; prove real-tokenizer training/inference prefix equality before ready exports. Do not implement the remaining 002 supervisor/container here.

**Checkpoint**: Stable native protocol and explicit configuration; no data or GPU claims yet.

## Phase 3: US1 - Faithful data export (P1, MVP)

**Goal**: All designated train sources and separate validation sources become
auditable native next-action rows without a new split or future-result leakage.
**Independent test**: Controlled sources prove exact prefixes/targets and overlap rejection.

- [x] T006 [US1] Implement input-role/content identities, ID/group/visible-input overlap audit and complete source accounting in `python/src/lifemate/sft/data.py`; read JSONL/catalog only and report unavailable group metadata.
- [x] T007 [US1] Implement whitelisted strict-prefix conversion, eligible-schema preservation, empty finish and waiting-clarification terminal handling in `python/src/lifemate/sft/data.py`; audit invalid pairs/targets/dependencies instead of silently repairing or discarding them.
- [x] T008 [US1] Add native real-tokenizer rendering, exact target spans, context/output-budget rejection and ready/audit manifests in `python/src/lifemate/sft/data.py`; block full-data readiness on unresolved source exclusions.
- [x] T009 [US1] Verify future-result sentinel isolation, history, Unicode/arguments, overlap, malformed sources, terminal rules and overflow in `python/tests/test_sft_data.py`, including separately enabled actual-tokenizer cases.
- [ ] T010 [US1] Wire preflight/prepare stages and artifact identity checks in `python/src/lifemate/sft/__main__.py`; document and record actual supplied-source export counts when inputs are available in `specs/003-planner-sft-baseline/quickstart.md`. *Partial: stages wired and Train counts recorded; no separate validation input exists yet.*

**Checkpoint**: Ready full-data export or explicit blocking audit; source counts are measured only after execution.

## Phase 4: US2 - One fixed adapter run (P1)

**Goal**: One recorded 500-update run on one selected 5090 or H200.
**Independent test**: Real-checkpoint smoke proves finite loss, adapter gradients,
frozen base and complete matching checkpoint restoration.

- [x] T011 [US2] Implement positional final-completion/terminal/padding masks and loss normalized over total supervised tokens in the full 16-example accumulation window in `python/src/lifemate/sft/training.py`; keep historical assistant messages masked and disable packing.
- [x] T012 [US2] Implement NF4 double-quantized BF16 preparation, standard q/k/v/o LoRA, module/trainable-count validation, checkpointing and fixed AdamW schedule in `python/src/lifemate/sft/training.py`.
- [x] T013 [US2] Implement deterministic full-coverage streaming, batch product 16, 500-update coverage preflight, no dropped partial batches and recorded epochs/row coverage in `python/src/lifemate/sft/training.py`.
- [x] T014 [US2] Implement no-grad validation every 100 updates, finite token-weighted NLL, per-checkpoint persisted unique row/source coverage, full-coverage-only earliest-tie selection, no-eligible-candidate failure, atomic checkpoints and config/data/base/RNG/sampler/coverage restore validation in `python/src/lifemate/sft/training.py`.
- [x] T015 [US2] Verify target/padding/EOS masks, batch/coverage guards, rejection of best-NLL update100 with 2120 rows, eligible later selection, no eligible finite candidate, resumed coverage and mismatched/incomplete checkpoints in `python/tests/test_sft_training.py`; include dropout-disabled 1x16/4x4 gradient equivalence with unequal target lengths and frozen/trainable checks, with real-GPU cases separately enabled.
- [ ] T016 [US2] Wire train/resume/explicit smoke mode in `python/src/lifemate/sft/__main__.py`; run NF4 BF16 forward/backward/memory feasibility on the selected actual host and record resolved package lock, CUDA/driver/GPU and effective settings in `specs/003-planner-sft-baseline/quickstart.md`. *Partial: CLI and smoke mode delivered; the host run is pending.*
- [ ] T017 [US2] Run the one full fixed-recipe experiment and record command/status, data identities, actual coverage, five checkpoint diagnostics, selection and failures in `specs/003-planner-sft-baseline/quickstart.md`; leave pending without host/assets and never substitute invented results.

**Checkpoint**: Selected complete adapter and reproducibility evidence. Selection is not a competition score.

## Phase 5: US3 - Merged export and assessment (P1)

**Goal**: Standalone FP16 export and honest competition/runtime evidence.
**Independent test**: Actual merged offline reload/native parsing, followed by
executed validation calls/hash under feature 002 when available.

- [x] T018 [US3] Implement selected-checkpoint identity and full-coverage eligibility validation against its manifest, merge into a fresh original unquantized base, standalone FP16 saving and export manifests in `python/src/lifemate/sft/export.py`; retain tokenizer/template/generation settings and parameter accounting.
- [x] T019 [US3] Wire export CLI in `python/src/lifemate/sft/__main__.py` and verify identity errors, ineligible/forged coverage selections, interrupted export, offline reload without training libraries and native call/finish/clarification parsing in `python/tests/test_sft_export.py`.
- [ ] T020 [US3] Run actual selected-adapter versus merged fixed-prompt diagnostics and inference-environment reload; record differences and artifacts in `specs/003-planner-sft-baseline/quickstart.md` rather than assuming quantized/FP16 equivalence.
- [ ] T021 [US3] After feature 002 runtime readiness, run one fixed separate-validation assessment of the merged export using actual calls/results, available supplied competition scoring and full audio timing; record exact IDs/commands/runtime/hardware, category denominators, failures/timeouts and p50/p95/max in `specs/003-planner-sft-baseline/quickstart.md`.
- [ ] T022 [US3] Record offline Docker, deterministic rerun, model/context limits and A30 timing/accounting gates against the actual exported system in `specs/003-planner-sft-baseline/quickstart.md`; keep missing scorer/hashes/hardware and external 002 prerequisites explicitly pending.

**Checkpoint**: Training/export may be complete while competition acceptance remains pending.

## Phase 6: Verification and documentation

- [x] T023 Run focused authored SFT checks and applicable native/dataset regressions, recording exact commands/results in `specs/003-planner-sft-baseline/quickstart.md`; distinguish controlled, actual-tokenizer, GPU and full runtime evidence.
- [x] T024 Update `python/README.md`, `context/architecture.md`, `context/tech_stack.md` and `context/testing.md` with implemented SFT commands and the external-validation/native-format boundary, linking measured evidence and remaining gates.

## Dependencies

```text
T001-T002 -> T003-T005 -> US1 (T006-T010)
US1 -> US2 (T011-T017) -> US3 export (T018-T020)
US3 export + feature 002 runtime/GPU readiness -> T021-T022
All delivered boundaries -> T023-T024
```

Feature 002's shared native adapter/tokenizer boundary blocks ready native exports.
Its execution/supervisor/Docker tasks block full audio acceptance, not trainer
authoring. Real datasets/GPU are command inputs; unavailable resources keep execution
tasks pending without preventing implementation of the planned boundaries.

## Parallel opportunities and implementation strategy

After T003 defines configuration, T004 example configuration and T005 shared adapter
work touch separate files. US1 fixture authoring can accompany converter work once
the row contract is fixed. US2 mask/selection fixtures can accompany trainer authoring;
US3 export fixtures can accompany merger authoring. Shared-file implementation tasks
remain ordered; these opportunities do not require extra agents.

MVP: foundation + US1 audited export. Then complete US2 and merged US3 export as
the smallest usable tuned model. Execute US3 acceptance only through the real
feature 002 path; do not reimplement its supervisor or claim compliance from mocks.
Unchecked tasks stay open until their stated deliverables or execution gates pass.
