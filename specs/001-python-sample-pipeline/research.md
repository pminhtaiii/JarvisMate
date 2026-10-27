# Research: Runnable Python sample pipeline

**Date**: 2026-10-27. Research resolves implementation choices; it does not report
model accuracy or completed sample execution.

## 1. Official workflow and setup

- **Decision**: Initialize official Spec Kit 1.2.3 using `specify init --here --force
  --non-interactive --integration none --script ps --ignore-agent-tools`; use its
  templates and create-feature/setup-plan/setup-tasks/prerequisite scripts.
- **Rationale**: Shared scaffolding preserves installed project skills and the existing
  Git branch. The official workflow separates constitution, specification, planning,
  tasks, and consistency analysis. This request ends before implementation.
- **Alternatives considered**: Handwritten substitute scaffolding; rejected after the
  user requested the upstream workflow. Installing another agent integration is unnecessary.
- **Sources**: [Official repository](https://github.com/github/spec-kit),
  [existing projects](https://github.github.io/spec-kit/guides/existing-projects.html),
  [quickstart](https://github.github.io/spec-kit/quickstart.html).
- **Hooks**: No `.specify/extensions.yml` is installed; before/after constitution,
  plan, and task hooks have nothing to dispatch. Workflow-engine approval gates are
  not executed: these artifacts are prepared for review, not automatic implementation.

## 2. Local data and first validation subset

- **Decision**: Validate explicit training IDs `train_1748` through `train_1751` first.
  Require every selected record/asset; do not infer a full dataset from local audio.
- **Rationale**: Read-only input inspection found 1,545 unique training records but
  only four current-request WAVs and 41 referenced history WAVs locally. User explicitly
  wants a sample-first pipeline; missing unrelated audio must not block selected tests.
- **Alternatives considered**: Entire split as first gate; silent missing-asset skip.
  Both obscure the intended subset and coverage.
- **Evidence**: `sample/train/train.jsonl` and audio filenames only. No hidden state
  was read, and no sample tool execution occurred during planning. Public-test inputs
  were not inspected for tuning.

## 3. Preserve supplied environment behavior

- **Decision**: Load one trusted split runtime per process using its package directory.
  Use the original ToolEnv constructor and methods; repair external layout before running.
- **Rationale**: `tools/train/__init__.py` expects a correctly spelled
  `<root>/train/train_environment/<id>/state.json` and split catalog at
  `<root>/train/train_tools_catalog.json`. Local uploads use `train_enviroment` and
  store catalogs under `tools/`. A missing catalog silently disables schema checks.
- **Alternatives considered**: Patch the runtime, copy hidden state into fixtures,
  or construct a custom Session from files; rejected because the organizer runtime
  must remain authoritative and hidden state is not pipeline input.
- **Implementation implication**: Preflight requires a nonempty valid catalog, known
  tool implementations, and selected state-path existence. A contained directory alias
  supplies the expected spelling without changing the original directory; catalog
  placement is explicit. Environment contents are never inspected or copied.

## 4. Exact available tools and reference IDs

- **Decision**: Use tool names listed in `context.installed_apps[app].tools`, verify
  catalog/app membership, and add `sys.ask_missing_info` unconditionally.
- **Rationale**: Training records have 1-80 tools; the catalog's 147 tools are not
  all available to a given sample. `env.validate` checks schema without logging;
  `env.call` logs actual attempts, including rejected ones.
- **Alternatives considered**: Send the full split catalog or authorize by app prefix
  alone; both can expose tools absent from the sample's declared list.
- **Reference semantics**: `x-ref` is descriptive metadata in this runtime, not a
  guarantee that an ID exists. Obtain IDs through observations and inspect outcomes;
  a nonexistent ID can return `ok: true, done: false`. Do not build a hidden-state ID index.

## 5. History and label isolation

- **Decision**: Construct a separate inference input with no `label` field. Preserve
  ordered history and distinguish prior user transcripts/audio from assistant text,
  historical calls, and results. History actions are never executed by the runner.
- **Rationale**: Training user entries have `role/audio/audio_text`; assistant entries
  have `role/text` with optional calls/results. Current environment state already
  includes those historical effects. Training labels expose gold calls and final state.
- **Alternatives considered**: Serialize the raw row; replay historical calls; use
  supplied transcripts as an audio-mode fallback. All would invalidate the intended test.

## 6. Planner protocol and bounds

- **Decision**: Strict JSON action union: a single call or finish per model decision.
  Default 16 decisions/sample; every malformed/rejected proposal consumes one decision.
  Use organizer validation and return correction feedback before execution.
- **Rationale**: ADR 007 chooses structured ReAct, not a multi-step expression executor.
  A small action grammar makes execution and traces inspectable without another framework.
- **Alternatives considered**: Free text with extracted JSON, arbitrary code expressions,
  or a mandatory closing response; each adds ambiguity or unnecessary model work.
- **Timing**: Default 30 seconds with monotonic checks and generation stopping criteria.
  Larger development budgets are explicit. Synchronous native/tool calls may overrun;
  hard preemption and final-container timing remain separately verifiable.

## 7. Local inference adapters

- **Decision**: Use Transformers/PyTorch local adapters. Initial planner experiment is
  Qwen3-4B-Instruct-2507. Support Whisper-small and PhoWhisper-small behind the same
  ASR interface, selecting one per run. Read PCM WAV with standard-library `wave` and
  NumPy for model input; reject unsupported audio clearly instead of adding FFmpeg.
- **Rationale**: Publisher cards show local Transformers support. Qwen documents 4B
  parameters, non-thinking behavior, and a minimum Transformers version of 4.51.
  Its larger native context does not override the competition's 16,384-token cap.
- **Alternatives considered**: Remote inference, vLLM service, paid APIs, and tuning.
  The first baseline needs none of these and final inference must remain offline.
- **Evidence limits**: No weights/compute are available yet. Pin tested dependency
  versions and snapshot identities during implementation; license/release eligibility
  must be checked against organizer rules before a submission claim.
- **Sources**: [Qwen publisher card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507),
  [PhoWhisper publisher card](https://huggingface.co/vinai/PhoWhisper-small),
  [Whisper model card](https://huggingface.co/openai/whisper-small).

## 8. Fail-fast evidence and publication

- **Decision**: Unique run directory, durable completed-row progress, required traces,
  run manifest, and a final prediction file published only on successful selected coverage.
- **Rationale**: ADRs 009/010 require diagnosing the executed path and stopping visibly
  on failure. A partial result must never look like an ordinary successful empty result.
- **Alternatives considered**: Continue-on-error default; placeholder empty rows;
  automatic reruns or response-cache recovery. These are deferred or prohibited.
- **Trace detail**: Metadata traces are mandatory; explicitly enabled dataset-debug
  payloads supply request/call/result detail for baseline inspection. Truncation and
  redaction are visible; authoritative output stays exact and separate. Metadata-only
  runs cannot satisfy detailed baseline-validation evidence.

## 9. Interface scope

- **Decision**: Implement Python CLI/library now, reuse models across its batch, and
  keep public Python contracts compatible with a later persistent JSONL worker.
- **Rationale**: User accepted Python CLI first. ADR 002's whole-sample boundary remains
  intact without implementing TypeScript or a service prematurely.
- **Alternatives considered**: Build outer harness, stdin worker transport, HTTP queue,
  and Docker in this feature; deferred to keep sample-first delivery bounded.

## 10. Validation layers

- **Decision**: Use `unittest` and injected controlled adapters for deterministic boundary
  checks, an opt-in supplied-environment smoke, and distinct real-model acceptance tasks.
- **Rationale**: Compute is unavailable; infrastructure can be tested without pretending
  controlled responses establish model quality. Existing Node contributor tests are
  not substitutes for Python behavior tests.
- **Alternatives considered**: Make GPU availability block every test; mark end-to-end
  acceptance complete using canned outputs. Both undermine evidence quality.
