# LifeMate testing and evaluation

Read [benchmark rules](benchmark.md) for the score and submission contract. A local passing test establishes only the cases it exercised; distinguish harness checks, sample scores, and organizer results.

## Baseline handoff status

The [Python README](../python/README.md) documents the authored implementation and
`unittest` commands for controlled tests and the separately enabled supplied-runtime
smoke. At the user's request these tests, model loading and inference have **not**
been executed on the authoring machine. Follow the
[validation handoff](../specs/001-python-sample-pipeline/validation.md) and record actual
outcomes before checking off execution tasks/gates or claiming tested behavior.
Implementation-authoring checkboxes record delivered source/tests/docs only; the
ledger separately lists the unrun acceptance gates, including controlled checks.

## Development loop

1. Choose a small, real request path through audio, planning, and tool execution. Record the sample IDs and the behavior being tested before changing code.
2. Keep a held-out portion of labeled `train` for development evaluation. Record how it was selected and keep it stable when comparing revisions. Do not label public or private test data for tuning.
3. Test deterministic boundaries separately: audio input handling, tool-schema selection and arguments, unavailable app and missing-information cases, execution results, call logging, and JSONL serialization.
4. Run the integrated slice through the split-matched `zaic_tools` environment with one `ToolEnv` per sample. Read app data only through its calls. Use `env.get_tool_calls()` and `env.get_state_hash()` for output.
5. Report sample-level failures before aggregate scores. Separate speech errors, intent/parameter errors, invalid or extra calls, wrong final state, out-of-scope mistakes, timeouts, and non-reproducible output.

## Train Validation and error analysis

Use the [roadmap](roadmap.md) for the frozen source-sample/conversation-group split,
paired transcript/audio evaluation, error taxonomy, and conditional tuning gate.
Freeze groups before any trajectory-to-step expansion. Validation references may be
inspected by evaluation/model selection, but are excluded from optimizer updates,
SFT fit rows, augmentation and prompt/retrieval example banks. Disclose repeated
validation-guided selection; it is development validation, not the private test score.

Separate teacher-forced next-action diagnostics from closed-loop runs. Closed-loop
validation uses actual predicted calls and environment observations; supplied gold
prefixes are never fed to the evaluated inference agent. Keep baseline/tuned comparisons
on identical IDs, runtime, prompt, ASR and decoding configuration and report incomplete
coverage or unavailable metrics explicitly. `label.final_state` is not the full state
from which to construct a gold hash. The [SFT design](../docs/design/train-to-sft.md)
defines future exporter/loss-mask/leakage checks; none has been implemented by this update.

## Evidence to record

The [measurement and prompt specification](../specs/002-measurement-prompt-experiments/spec.md)
and linked plan/contracts define the measurement and controlled-experiment behavior.
Spans, telemetry, offline `report`/`compare-runs`/`audit-examples`, and opt-in
`precise-v1`/fit-only prompt profiles are implemented (see
[python/README.md](../python/README.md#measurement-reports-and-prompt-profiles)) and
covered by the controlled suite; see
[002 validation](../specs/002-measurement-prompt-experiments/validation.md) for the exact
command and per-file results. No real run, report, comparison, or evaluator-scored
result exists yet; latency/compliance/accuracy claims still require actual hardware,
models and an evaluator.

For each evaluation, record the code revision, dataset split and sample selection, model/component versions, seed and decoding settings, exact command, exit status, elapsed time, and scoring result. Record state-hash matches, tool-call F1, empty-gold accuracy, schema-rejected calls, and timeout count when the evaluator supplies them. Keep traces bounded and free of user secrets or hidden environment files.

Per-sample traces are required under [ADR 009](../docs/adr/009-require-execution-traces-from-first-baseline.md). Record whether the request came from a supplied training transcript or ASR, the request text used, available tool names, ordered planner action outputs, validation outcomes, actual tool calls and observed results, timing, stopping reason, errors, and the authoritative call log and final state hash when available. Compare the executed path as well as the final state, using training references for evaluation only, never as planner input.

Store these explicitly enabled dataset-debug traces under ignored `.agent-work/lifemate-runs/`, separate from submission rows and routine logs. Bound and sanitize trace payloads, mark truncation or redaction explicitly, and preserve exact authoritative call arguments in the submission result. Do not read hidden environment files to enrich a trace. A successful final state alone must not hide extra, invalid, or incorrect calls.

Baseline-validation runs explicitly enable the detailed dataset-debug payloads above. Metadata-only operational traces must mark omitted payloads and do not satisfy the baseline's detailed evidence requirement.

Preflight input failures stop the run and are recorded in the run manifest before sample traces or environments are created. After sample execution starts, worker crashes, exhausted execution bounds, and unrecoverable planner output are execution failures. The initial development batch stops on its first execution failure, preserves completed results and available failure evidence, and exits nonzero under [ADR 010](../docs/adr/010-stop-development-batch-on-execution-failure.md). A failure trace may be unavailable before sample execution or after storage/process failure; report that limitation. Distinguish failures from valid empty call lists, and never present an incomplete run as submission-ready. An observable error response from a tool is evidence for the planner; it is not automatically a worker crash or batch failure.

A correct transcript alone does not prove a correct tool plan. A valid call list alone does not prove the requested app state. A submitted hash alone does not prove reproducibility; verify replay with the same split-matched environment. Before submission, check the offline Docker run, total model-size and context limits, the 30-second per-sample budget, deterministic reruns, and one JSONL row per sample.

For implementation changes, run the narrowest meaningful behavioral tests first and the applicable integrated check before claiming completion. Reviewers compare the changed behavior with the task's issue/PR and [code standards](code_standard.md), and report only checks actually run.
