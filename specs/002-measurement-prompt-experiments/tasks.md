# Tasks: Pipeline measurement and prompt experiments

**Input**: [plan.md](plan.md), [spec.md](spec.md), research, data model and contracts.

**Status**: Planning only; all implementation/validation work is unchecked.

**Tests**: Focused behavioral checks required by the specification; no model tests
or runtime benchmarks are executed by generating this list.

## Phase 1: Setup

- [x] T001 Confirm existing sample/failure/resume extension seams and preserve public behavior in `python/src/lifemate/contracts.py`, `cli.py`, `artifacts.py`, and `checkpoint.py`; document any changed assumptions in `specs/002-measurement-prompt-experiments/research.md`.

## Phase 2: Foundation

- [x] T002 Define validated metric records, optional sink, version/availability/status values and injectable monotonic spans in `python/src/lifemate/metrics.py` per `contracts/measurement.md`.
- [x] T003 Add additive metadata serialization and original-run attempt identity to `python/src/lifemate/artifacts.py`; preserve existing schema keys, payload bounds and exact prediction fields.

## Phase 3: US1 - Locate sample latency (P1, MVP)

**Goal**: Observe full sample and stage time without changing authoritative execution.
**Independent test**: Fake-clock multi-clip/multi-call success and failure fixtures.

- [x] T004 [US1] Instrument each history/current clip in `python/src/lifemate/dataset.py` and each environment/planner/tool/final-collection boundary in `python/src/lifemate/agent.py`, including partial spans on errors.
- [x] T005 [US1] Add optional per-generation telemetry and completed-device timing in `python/src/lifemate/adapters/common.py`, `adapters/planner.py`, and `adapters/asr.py`; count actual tokens and separate filter/corrective/action/ASR roles.
- [x] T006 [US1] Measure full attempt through durable output/trace close in `python/src/lifemate/cli.py` and `artifacts.py`; retain failed outcomes for continued and fatal paths and separate run-overhead publication time.
- [x] T007 [US1] Preserve legacy elapsed semantics and imported measurements in `python/src/lifemate/contracts.py`, `artifacts.py`, and `checkpoint.py`; leave absent legacy/full-attempt metrics unavailable.
- [x] T008 [US1] Add behavioral coverage in `python/tests/test_metrics.py` and extend `test_agent.py`, `test_artifacts.py`, and `test_cli.py` for nested spans, failure timing, offload accounting, trace-creation/output overhead crossing the full 30s target while the loop succeeds, I/O loss and generous-deadline prediction parity.

**Checkpoint**: US1 works with controlled adapters independently of reports/prompts.

## Phase 4: US2 - Compare runs honestly (P2)

**Goal**: Offline, reproducible reports and compatible single-factor comparisons.
**Independent test**: Synthetic completed/failed/incomplete/resumed artifacts.

- [x] T009 [US2] Implement validated manifest/trace measurement readers and nearest-rank distributions in `python/src/lifemate/reporting.py`, with explicit coverage, missing values, failures/imports and weighted token rates.
- [x] T010 [US2] Add evaluation identity validation, explicit gold_empty/sample_score handling, paired factor checks and acceptance classifications in `python/src/lifemate/reporting.py` per `contracts/experiments.md`; missing evidence stays exploratory.
- [x] T011 [US2] Add offline `report` and `compare-runs` parsers in `python/src/lifemate/cli.py`; atomically generate JSON/Markdown, validate output locations, and expose report failure without masking original inference errors in `artifacts.py`.
- [x] T012 [US2] Add synthetic aggregation/CLI tests in `python/tests/test_reporting.py` and `test_cli.py` for small/empty populations, unknown versions, invalid artifacts, incomplete failure, imports, incompatible factors/evaluation and no-model reporting; include empty-gold score independent of hash, full-total overruns after loop success, allowed report regeneration and rejected comparison overlap.

**Checkpoint**: US2 can be verified with fixtures without inference or prompt changes.

## Phase 5: US3 - Precise prompts and fit-only demonstrations (P3)

**Goal**: Opt-in deterministic prompt factors with provenance and leakage checks.
**Independent test**: Rendered messages, fit/group fixtures, budgets and checkpoint identity.

- [x] T013 [US3] Define baseline/precise-v1 profiles and fixed bundle/partition validation in `python/src/lifemate/prompt_profiles.py`; add offline source-prefix/target audit in `example_audit.py` per `contracts/prompts.md`, with fit/group/catalog checks and deterministic identity.
- [x] T014 [US3] Extend `python/src/lifemate/prompting.py` for resolved instructions and separately scoped fixed demonstrations; preserve exact baseline rendering and live top-level allowlist, and enforce added-token/full-context budgets in `adapters/planner.py`.
- [x] T015 [US3] Wire proposed run options and separate `audit-examples` command through `python/src/lifemate/cli.py`, `contracts.py`, and `adapters/planner.py`; reject invalid combinations/non-validation selections/overlaps before inference and record example overhead.
- [x] T016 [US3] Include effective profile/template/bundle/partition/budget identity in `python/src/lifemate/artifacts.py`, `provenance.py`, and `checkpoint.py`; test baseline legacy handling and strict/mixed resume behavior.
- [x] T017 [US3] Add `python/tests/test_prompt_profiles.py` and extend relevant CLI/prompt/checkpoint tests for exact baseline messages, scoped IDs, strict-prefix rejection, fit/validation group exclusion, frozen hashes, changed artifacts, deterministic order and overflow.

**Checkpoint**: US3 configuration/rendering is independently verifiable; model-quality
claims still require US2 reports and actual held-out evaluation.

## Phase 6: Documentation and acceptance handoff

- [ ] T018 Update `python/README.md` and `context/testing.md` with implemented metrics/options and exact checks actually run; retain explicit evidence limits and separate model setup.
- [ ] T019 Execute controlled checks from `specs/002-measurement-prompt-experiments/quickstart.md` after implementation and record outcomes in a new `specs/002-measurement-prompt-experiments/validation.md`; do not substitute static inspection for test results.
- [ ] T020 Record the frozen validation/fit selection, experiment hypothesis and commands in `specs/002-measurement-prompt-experiments/validation.md`; when execution is authorized and data/hardware/evaluator are available, run the audio control and separate instruction/few-shot arms, attach reports, and disclose unavailable acceptance prerequisites.

## Dependencies and execution order

T001 -> T002 -> T003. US1: T004 -> T005 -> T006 -> T007 -> T008.
US2: T009 -> T010 -> T011 -> T012. US3: T013 -> T014 -> T015 -> T016 -> T017.
Integrate US2 after US1; US2 readers can first be verified using fixtures. US3 pure
profile validation can be developed after foundation, but real prompt comparisons
require completed US1/US2. T018/T019 follow all included stories; T020 requires actual
data, authorized execution and available evaluation/hardware.

No `[P]` tasks are marked: integration changes touch shared CLI/store/adapter files.
Safe parallel opportunities after contracts freeze: US2 synthetic report fixtures
in `python/tests/test_reporting.py` while US1 instrumentation proceeds; US3 pure
profile fixtures in `python/tests/test_prompt_profiles.py` while US2 reporting is
implemented. Coordinate fixture requirements; serialize edits to shared modules.

## Implementation strategy

Deliver US1 as the smallest useful increment, validate it, then add US2 and US3.
Use fake adapters/clocks before real models. Keep every experiment single-factor;
do not implement a harness optimization, reflection, scorer, server or model tuning
under these tasks. There are 20 tasks: US1 5, US2 4, US3 5, setup/foundation 3,
and documentation/acceptance 3. All remain unchecked.
