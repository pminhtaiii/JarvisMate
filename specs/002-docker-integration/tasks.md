# Tasks: Configurable offline Docker integration

**Input**: Design artifacts in `specs/002-docker-integration/`.
**Status**: In progress; checked tasks record delivered source/tests/docs, and runtime gates stay unchecked until measured.
**Tests**: Focused behavioral verification is required by spec FR-017. Existing local
policy separates controlled checks from explicitly enabled actual-model/GPU acceptance.

Every task states its owning file(s). `[P]` means disjoint files and no dependency on
another unfinished task in the same phase. Story labels map to spec user stories.

## Phase 1: Setup

- [x] T001 Record the integration-only continuation/deadline policy and legacy compatibility in `docs/adr/011-configurable-docker-integration.md`, linking this spec and explicit user-authorized exceptions.
- [x] T002 Confirm package/organizer runtime dependency layout and CUDA build inputs in `python/pyproject.toml` and `specs/002-docker-integration/research.md`; keep training dependencies out.

## Phase 2: Foundation

- [x] T003 Define strict config/attempt records, terminal states and deadline/identity validation in `python/src/lifemate/configuration.py` and `python/src/lifemate/contracts.py` without changing legacy defaults.
- [x] T004 Add TOML loading, known CLI overrides, snapshot/template/parameter/context preflight and configuration fingerprinting in `python/src/lifemate/configuration.py`.
- [x] T005 Verify unknown keys, invalid devices/dtypes/limits, absent snapshots, incompatible templates and pre-environment rejection in `python/tests/test_integration_config.py`.
- [x] T006 Define unique durable staging, fsynced pre-dispatch reservations binding sample/attempt/worker/config identity, accepted/failed journal and incomplete-publication guard in `python/src/lifemate/artifacts.py`; fail closed on corrupt journal and keep legacy artifacts compatible.

**Checkpoint**: Configuration and attempt/output boundaries are explicit; no model or
ToolEnv is created for invalid settings. Foundation is required by every story.

## Phase 3: US1 - Native audio integration (Priority: P1)

**Goal**: One prepared request, native next-action decisions and real execution feedback.
**Independent test**: Controlled dependent calls return exact expected calls/hash;
ASR counts equal distinct required clips and historical actions are not replayed.

- [x] T007 [P] [US1] Add content-digest keyed sample-local transcript reuse and ASR count/timing events in `python/src/lifemate/dataset.py`, preserving history and diagnostic transcript mode.
- [x] T008 [P] [US1] Implement eligible-tool native rendering, actual call/result messages and strict one-call/EOS/neutral-finish parsing in `python/src/lifemate/adapters/qwen_native.py`.
- [x] T009 [US1] Implement constrained native decoding and checkpoint-specific tokenizer/template validation in `python/src/lifemate/adapters/qwen_native.py`, reusing existing local model/session helpers without an unconstrained fallback.
- [x] T010 [US1] Verify native render/parse, actual tokenizer EOS, zero-argument tools, Unicode, malformed/multiple calls, extra text and output/time cuts in `python/tests/test_qwen_native.py`.
- [x] T011 [US1] Verify repeated-reference/identical-content reuse, distinct historical clips, supplied history text and empty/missing audio handling in `python/tests/test_asr_once.py`.
- [x] T012 [US1] Wire native adapter/prepared request into an explicit integration path in `python/src/lifemate/agent.py` and `python/src/lifemate/integration.py`; retain one environment, eligibility checks, schema-attempt logging and legacy defaults.
- [x] T013 [US1] Verify lookup-dependent second calls, no history replay, clarification after partial execution and exact authoritative output in `python/tests/test_integration_pipeline.py`; run applicable existing runner/ASR regressions and record commands/results in `specs/002-docker-integration/quickstart.md`.

**Checkpoint**: Native integration works with controlled adapters. This alone is not
a deadline-compliant/container-ready release.

## Phase 4: US2 - Full-attempt supervision (Priority: P1)

**Goal**: No late success, no uncertain replay, bounded recovery for later samples.
**Independent test**: Blocking doubles at ASR/planner/tool/output boundaries time out
and cannot publish late rows; a different sample can run after worker recovery.

- [x] T014 [US2] Implement persistent spawned worker loading, bounded framed IPC, ready/result identities and per-sample durable staging in `python/src/lifemate/worker.py`.
- [x] T015 [US2] Implement exclusive run ownership, durable-reservation-before-dispatch ordering, monotonic dispatch deadlines, bounded IPC reads/writes/partial frames and log draining, process-group termination/reaping, stale-message rejection and output quarantine in `python/src/lifemate/supervisor.py`.
- [x] T016 [US2] Add bounded recovery for subsequent distinct IDs, startup/reload timing and confirmed prior-worker termination in `python/src/lifemate/supervisor.py`; classify reserved-without-durable-acceptance IDs as uncertain after parent death and never replay them, including resume.
- [x] T017 [US2] Connect timely supervisor acceptance and acceptance-journal durability before next dispatch, partial outputs, nonzero incomplete exit and complete-publication guard in `python/src/lifemate/integration.py` and `python/src/lifemate/artifacts.py`; write failure must preserve the uncertain reservation.
- [x] T018 [US2] Verify blocked stages/dispatch writes/partial IPC frames, late/stale messages, parent death before dispatch/after mutation/before acceptance fsync, reservation/acceptance write failures, corrupt journals, exclusive ownership, old-worker termination, no uncertain replay, bounded recovery and publication denial in `python/tests/test_integration_supervisor.py`.
- [x] T019 [US2] Add per-clip/per-decision/tool/collection/durable-output/full-attempt spans, tokens, termination overshoot and startup/recovery/packaging totals in `python/src/lifemate/worker.py` and `python/src/lifemate/artifacts.py`; verify them in `python/tests/test_integration_pipeline.py`.

**Checkpoint**: Timed success is validated independently of worker cooperation.
Record OS kill limits; a timeout is never a valid empty result.

## Phase 5: US3 - Configurable offline container (Priority: P1)

**Goal**: Same image, selectable local checkpoints/GPU/settings, reproducible provenance.
**Independent test**: Same image runs compatible checkpoint configurations offline;
startup rejects incompatible settings before ToolEnv creation.

- [x] T020 [P] [US3] Add documented model/device/dtype/offload/limits/selection example in `configs/integration.example.toml`, matching `contracts/cli-container.md`.
- [x] T021 [P] [US3] Add minimal pinned GPU runtime/package/organizer installation and integration entrypoint in `Dockerfile`; exclude weights/data/secrets/training/git/runs via `.dockerignore`.
- [x] T022 [US3] Finalize separate CLI overrides/preflight and effective model/template/device/driver/config provenance in `python/src/lifemate/integration.py` and `python/src/lifemate/artifacts.py`.
- [x] T023 [US3] Verify compatible checkpoint switching, CLI precedence, startup readiness, provenance and model/config mismatch resume rejection in `python/tests/test_integration_config.py`.
- [ ] T024 [US3] Build and run the image with `--network none`, selected GPU and read-only model/data/config mounts; record exact commands, digest, resolved dependencies and actual outcomes in `specs/002-docker-integration/quickstart.md`.
- [ ] T025 [US3] Validate actual ASR/Qwen checkpoints and a second compatible configuration without source/image changes; record startup, memory and limitations in `specs/002-docker-integration/quickstart.md`.

**Checkpoint**: Actual offline image evidence exists. Metadata-only checks cannot
complete T024/T025; unavailable checkpoints/GPU leave them pending.

## Phase 6: US4 - Empty/clarification diagnostics (Priority: P2)

**Goal**: Separate rare-case and ASR/planner errors without adding inference passes.
**Independent test**: Offline reports reproduce known category counts/arguments/errors
and retain timeout/failure denominators without giving labels to inference.

- [ ] T026 [US4] Implement offline Train-reference joining and empty/clarification diagnostics in `python/src/lifemate/diagnostics.py`, including false empty/false clarification, intended-tool/params correctness and overlapping-group denominators.
- [ ] T027 [US4] Verify valid empty vs failed/timeout, missing-info after earlier calls, unsuccessful clarification, unavailable metrics and label-isolated reports in `python/tests/test_integration_diagnostics.py`.
- [ ] T028 [US4] Add report invocation/paired transcript-audio evidence handling to `python/src/lifemate/diagnostics.py` and `specs/002-docker-integration/quickstart.md`; preserve inference input whitelist and supplied-runtime scoring semantics.
- [ ] T029 [US4] Freeze and record grouped Train selection/category counts and run paired transcript/audio diagnostics using actual checkpoints; record dataset, IDs, commands and per-category errors in `specs/002-docker-integration/quickstart.md`, keeping raw data/traces ignored.

**Checkpoint**: Frequency and behavior evidence is available; training/rebalancing is
a separate experiment, not implicitly authorized implementation here.

## Phase 7: Verification and Handoff

- [ ] T030 Run focused controlled checks and applicable legacy regressions from `python/tests/`; record exact commands/results in `specs/002-docker-integration/quickstart.md` without marking model/GPU acceptance from doubles.
- [ ] T031 Measure paired baseline/integration latency and correctness on the fixed selection, then change one justified inference setting at a time; record GPU/settings, p50/p95/max, timeout counts, memory/tokens and regressions in `specs/002-docker-integration/quickstart.md`.
- [ ] T032 Confirm organizer startup/recovery/packaging accounting, failed-sample representation and final entrypoint requirements; update `specs/002-docker-integration/contracts/runtime.md` and `contracts/cli-container.md` before submission-readiness claims.
- [ ] T033 Verify deterministic reruns, model/context limits, exact selected-ID output coverage and complete-publication behavior; record development-vs-competition-hardware evidence limits in `specs/002-docker-integration/quickstart.md`.
- [ ] T034 Update `context/architecture.md`, `context/tech_stack.md`, `context/testing.md` and `python/README.md` with implemented contracts and measured status only, retaining legacy/proposed distinctions and linking ADR 011.

## Dependencies and Execution Order

```text
T001-T002 -> T003-T006 -> US1 (T007-T013) -> US2 (T014-T019)
                                      -> US3 (T020-T025; end-to-end requires US2)
                                      -> US4 (T026-T029; reports include US2 failures)
US1 + US2 + US3 + US4 -> T030-T034
```

US2 can be developed with blocking doubles independently of real models after the
foundation, then integrated after US1. US3 packaging/config can be authored before
US1/US2 finish; offline end-to-end acceptance depends on them. US4 report logic can
be verified with completed/failure fixtures before real runs exist. Real-model
experiments depend on provided snapshots/data/GPU and cannot be claimed from mocks.

## Parallel Opportunities

- US1: T007 request preparation and T008 native adapter touch disjoint owners.
- US2: After IPC contract agreement, worker and supervisor test fixtures may be
  authored separately; T014-T017 mutations stay ordered because boundaries interact.
- US3: T020 example config and T021 container files are disjoint after foundation.
- US4: Report fixtures can be prepared while inference acceptance runs; T026-T028
  share report code and stay sequential.

These are work-allocation options, not authorization to spawn agents automatically.

## Implementation Strategy

1. Foundation + US1 is the controlled integration milestone, not a submission claim.
2. US2 + US3 complete the required bounded offline deployment slice; all three P1
   stories are necessary for the user's usable baseline.
3. US4 adds diagnosis before any later training experiment.
4. Keep runtime/hardware gates unchecked until exact command/dataset outcomes exist.
5. Retain the legacy comparison runner; avoid training/HTTP/distributed additions.
