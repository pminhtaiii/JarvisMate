# Tasks: Runnable Python sample pipeline

**Input**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md).
**Status**: Baseline source/tests are authored; all 27 acceptance tasks remain open
until their stated checks run. The user explicitly deferred execution to the receiving
teammate. See [validation.md](validation.md) for per-task authored coverage and
[python/README.md](../../python/README.md) for handoff commands. Code presence and a
branch push do not establish passing tests, actual model runs or feature completion.

Tests are explicitly required by FR-017. Use focused behavioral cases rather than
tests mirroring implementation. `[P]` means disjoint file work after listed prerequisites;
it is not authorization to delegate implementation to Luna. Luna remains exploration-only.

## Phase 1: Setup

- [ ] T001 Create the installable Python 3.11+ package and optional inference extras in `python/pyproject.toml`, `python/src/lifemate/__init__.py`, `python/src/lifemate/__main__.py`, and `python/README.md`; preserve root Node tooling and use standard-library core/test dependencies.

## Phase 2: Foundational boundaries

- [ ] T002 Define validated run/sample/action/outcome interfaces, stable failure codes, and planner/ASR/environment protocols in `python/src/lifemate/contracts.py` per `specs/001-python-sample-pipeline/data-model.md` and contracts; represent success, needs-info, and failure separately.
- [ ] T003 [P] Add selected-record, duplicate/unknown ID, label isolation, history-shape, safe-path/symlink, and selected-assets-only tests in `python/tests/test_dataset.py` after T002; assert malformed inputs fail before models or environments open.
- [ ] T004 Implement JSONL indexing, explicit ID/all selection, transcript-mode normalization, exact installed-tool filtering, and selected path/catalog validation in `python/src/lifemate/dataset.py` to satisfy T003; never read hidden state or replay history.
- [ ] T005 [P] Add missing-catalog, split/package mismatch, implemented-tool coverage, one-environment factory, and no-hidden-read contract checks in `python/tests/test_runtime.py` after T002; guard runtime-internal reads separately from forbidden pipeline reads.
- [ ] T006 Implement trusted split-package loading and original ToolEnv delegation in `python/src/lifemate/runtime.py` to satisfy T005; require valid catalog at ToolEnv's actual path, verify selected runtime tool coverage, and use only state-path existence checks before ToolEnv opens it.
- [ ] T007 [P] Add UTF-8 trace ordering, explicit payload omission/redaction/truncation, storage-failure-before-next-effect, exact prediction fields, and authoritative-result preservation tests in `python/tests/test_artifacts.py` after T002.
- [ ] T008 Implement required trace sink, run manifest/provenance, exact single-row serialization, unique-run protection, bounded explicit debug payload capture, and failure-safe flushing in `python/src/lifemate/artifacts.py` to satisfy T007.

**Checkpoint**: Foundational tests pass with no weights/GPU. Runtime source and hidden
state contents are unchanged. T003/T005/T007 may be developed independently after T002;
their paired implementations must pass before dependent story integration.

## Phase 3: US1 - Inspect one text-to-tools sample (P1, core MVP)

**Goal**: One selected training transcript produces an authoritative result and a detailed trace.

**Independent test**: Controlled lookup-to-action sequence verifies actual dispatch
and returned-value use; an opt-in real environment smoke verifies package integration.
A real pretrained-planner run has separate acceptance and may remain blocked by compute.

- [ ] T009 [P] [US1] Add bounded ReAct tests in `python/tests/test_agent.py` for lookup-to-action ID binding; strict JSON/duplicate-key/non-finite/extra-field and unavailable-tool rejection with zero environment calls; allowed calls with schema-invalid arguments reaching ToolEnv.call, remaining in submitted tool_calls, and returning correction feedback; done-false observations; finish/empty outcomes; needs-info termination only on success with waiting_for_user:true and continued planning on success with the field false or absent; uncertain execution; one ToolEnv; and step/deadline exhaustion after Phase 2.
- [ ] T010 [P] [US1] Add GPU-free planner-adapter tests in `python/tests/test_inference.py` for local-only loading, unavailable weights/device, deterministic generation settings, model/context caps, prompt-plus-output budgeting, model reuse, and deadline stopping after Phase 2.
- [ ] T011 [US1] Implement whitelisted Vietnamese-catalog prompt construction, ordered history/observations, prompt identity, token-budget rejection, and bounded validation feedback in `python/src/lifemate/prompting.py`; prove labels/history replay instructions cannot enter execution.
- [ ] T012 [US1] Implement strict action parsing and the bounded single-sample ReAct loop in `python/src/lifemate/agent.py` after T009/T011, with pre-dispatch shape/eligibility checks, argument validation and logging through ToolEnv.call, trace-before-dispatch, missing-info termination only on success with waiting_for_user:true, authoritative result collection, and no automatic retry/reset.
- [ ] T013 [US1] Implement the real local Qwen adapter in `python/src/lifemate/adapters/planner.py` after T010/T011; pin compatible optional dependency versions in `python/pyproject.toml`, reuse model instances, enforce context/model limits, and keep inference offline.
- [ ] T014 [US1] Add CLI preflight/single-run, exit-code, stdout/stderr, unavailable-model, trace-I/O, and no-fabricated-result tests in `python/tests/test_cli.py` after T004/T006/T008/T012/T013, injecting controlled adapters without a production fake backend; assert preflight input failures are recorded in the run manifest with zero sample traces, model invocations, or environments.
- [ ] T015 [US1] Implement `check-data` and single-selected-sample `run` orchestration in `python/src/lifemate/cli.py` and connect `python/src/lifemate/__main__.py` after T014; complete preflight before model/ToolEnv invocation and emit stable summaries/errors.
- [ ] T016 [US1] Implement opt-in supplied-runtime integration checks in `python/tests/test_real_samples.py` using `LIFEMATE_REAL_DATA_ROOT`, `LIFEMATE_REAL_SAMPLE_ID`, and `LIFEMATE_RUNTIME_DIR`; choose an allowed schema-valid read tool from the sample, verify trace/log/hash, and explicitly skip absent data by default without reading labels or hidden state.
- [ ] T017 [US1] When local weights and suitable compute are available, execute the real-planner transcript checkpoint for `train_1748` and then the four explicit training IDs per `specs/001-python-sample-pipeline/quickstart.md`; record commands, traces, calls, timings, and model provenance under `.agent-work/lifemate-runs/` and summarize actual evidence in `specs/001-python-sample-pipeline/validation.md`.

**Checkpoint**: T009-T016 establish implementation/controlled integration, not model
accuracy. T017 is externally gated by model weights/compute and four-ID batch support
from US2; leave it unchecked until its real runs actually occur.

## Phase 4: US2 - Run a selected subset and expose failures (P1)

**Goal**: Selected samples run sequentially with durable progress and visible first failure.

**Independent test**: Complete a two-sample run, then inject a second-sample failure
in a three-sample batch; preserve the first row and fail without invoking the third.

- [ ] T018 [US2] Extend `python/tests/test_cli.py` and `python/tests/test_artifacts.py` after T015 with selected-order/count checks, sequential model reuse, second-sample failure, later-sample noninvocation, partial-output preservation, atomic publication failure, incomplete manifest, and existing-run refusal.
- [ ] T019 [US2] Implement append-and-flush progress, manifest transitions, exact selected coverage checks, and final-file publication in `python/src/lifemate/artifacts.py` after T018; retain failed-sample diagnostic evidence without emitting a successful row.
- [ ] T020 [US2] Extend `python/src/lifemate/cli.py` after T019 for dataset-ordered selected batches, fail-fast nonzero termination, run-level model reuse, explicit subset/full-split scope, and no automatic resume/retry.
- [ ] T021 [US2] Prepare the documented contained directory alias/catalog layout without modifying original environment directories and run selected preflight plus the opt-in real-runtime smoke via `python/tests/test_real_samples.py` after T016/T020; record actual commands/statuses and the missing-asset/fail-fast controls in `specs/001-python-sample-pipeline/validation.md`, never copying or inspecting environment contents.

**Checkpoint**: Selected-batch infrastructure is independently testable with controlled
adapters, regardless of T017. No full-split score or submission claim follows.

## Phase 5: US3 - Run the same samples from audio (P2)

**Goal**: Actual current/history-user audio replaces supplied transcripts behind the same loop.

**Independent test**: Controlled ASR verifies ordering, no supplied-text fallback, and
unchanged execution contracts; real ASR/planner runs are a separate externally gated step.

- [ ] T022 [US3] Add WAV format/sample-rate checks, current/history-user ordering, missing-audio failure, no supplied-transcript fallback, assistant-history preservation, local-only model reuse, and timing-budget tests in `python/tests/test_audio.py` after T020.
- [ ] T023 [US3] Implement the local Whisper/PhoWhisper ASR adapter with PCM WAV/NumPy input in `python/src/lifemate/adapters/asr.py` after T022; select one local ASR per run, transcribe Vietnamese, and fail clearly on unsupported input or unavailable resources.
- [ ] T024 [US3] Integrate current/history-user ASR preparation and audio-specific preflight into `python/src/lifemate/dataset.py`, `python/src/lifemate/cli.py`, and `python/src/lifemate/prompting.py` after T023; enforce audio-mode label/transcript exclusion and include ASR in per-sample timing.
- [ ] T025 [US3] When weights/compute are available, run real transcript/audio comparisons on all four local training IDs using the same planner and each ASR candidate in separate runs per `specs/001-python-sample-pipeline/quickstart.md`; record manifests/traces and per-sample path/timing differences in `specs/001-python-sample-pipeline/validation.md`, keeping any blocked acceptance explicit.

## Phase 6: Validation and documentation

- [ ] T026 Run the focused Python suite and available opt-in checks, verify no hidden reads/runtime edits/label leakage, and record exact outcomes and external blocks in `specs/001-python-sample-pipeline/validation.md`; mark only tasks whose implementation and stated checks actually completed.
- [ ] T027 Update `python/README.md`, `context/architecture.md`, `context/testing.md`, and `context/tech_stack.md` with the implemented command/contracts and measured evidence only; recheck `specs/001-python-sample-pipeline/spec.md`, `plan.md`, and `tasks.md` for consistency and run `git diff --check`.

## Dependencies & Execution Order

- T001 -> T002 -> independent test branches T003/T005/T007 -> implementations
  T004/T006/T008 -> US1 integration. Pair tests with their immediate implementation
  as appropriate, but do not bypass any external dependency.
- US1 core: T009 -> T012; T010 -> T013; T011 -> T012/T013;
  T004/T006/T008/T012/T013 -> T014 -> T015 -> T016.
- US2: T015 -> T018 -> T019 -> T020; T016/T020 -> T021.
- US3: T020 -> T022 -> T023 -> T024.
- Real-model leaf gates: T017 depends on T013/T016/T020 plus external compute/weights;
  T025 depends on T017/T024 plus both ASR snapshots. These gates do not block
  independent infrastructure work, but remain required for full feature acceptance.
- T026 depends on the implementation branches through T024 and all available checks;
  it reports blocked real-model gates honestly. T027 follows T026. Feature completion
  still requires T017/T025 and every other canonical task to be satisfied.

## Parallel Opportunities

- Foundation: T003, T005, T007 own separate test files after contracts exist.
- US1: T009 (`test_agent.py`) and T010 (`test_inference.py`) can proceed together
  after foundation. Their implementation merges must respect T011 and shared contracts.
- US2: keep T018-T020 serial; CLI and artifact ownership overlap.
- US3: keep T022-T024 serial; no speculative parallel work before the ASR contract test.
- Real-model acceptance waits for external resources while independent implementation
  can proceed. `[P]` labels describe file independence, not a mandate to spawn agents.

## Implementation Strategy

1. Deliver the one-sample transcript CLI with required traces and controlled checks.
2. Add selected-subset batches and inject failures before trusting completed artifacts.
3. Add ASR for the same local sample IDs; compare real model paths when possible.
4. Keep T017/T025 open if compute is unavailable. Report infrastructure progress
   separately; do not mark the real baseline complete or fabricate validation output.
5. TypeScript/HTTP/UI, final Docker/full-split compliance, specialist agents,
   fine-tuning, custom scorer aggregation, and latency optimization are later work.

The [project roadmap](../../context/roadmap.md) sequences follow-on Train Validation,
error analysis, and conditional [Train-to-SFT planning](../../docs/design/train-to-sft.md).
The 27 tasks here remain the baseline implementation ledger; no training task or
completion claim is added by that documentation. Real execution acceptance stays
open until a teammate with the required resources records its evidence.

## Requirement Coverage

| Requirements | Tasks |
|---|---|
| FR-001/002 | T003-T006, T014-T015, T018-T021 |
| FR-003 | T002, T006, T011-T015, T023-T024 |
| FR-004/005 | T003-T004, T009, T011, T022-T024 |
| FR-006/007/008/009 | T005-T006, T009, T012, T016, T021 |
| FR-010/011/012/013 | T007-T008, T012, T014-T015, T018-T021 |
| FR-014/015/016 | T010-T013, T017, T022-T025 |
| FR-017; SC-001 through SC-006 | T003/T005/T007/T009/T010/T014/T016/T018/T021/T022 and T017/T025/T026 |
