# LifeMate testing and evaluation

Read [benchmark rules](benchmark.md) for the score and submission contract. A local passing test establishes only the cases it exercised; distinguish harness checks, sample scores, and organizer results.

## Development loop

1. Choose a small, real request path through audio, planning, and tool execution. Record the sample IDs and the behavior being tested before changing code.
2. Keep a held-out portion of labeled `train` for development evaluation. Record how it was selected and keep it stable when comparing revisions. Do not label public or private test data for tuning.
3. Test deterministic boundaries separately: audio input handling, tool-schema selection and arguments, unavailable app and missing-information cases, execution results, call logging, and JSONL serialization.
4. Run the integrated slice through the split-matched `zaic_tools` environment with one `ToolEnv` per sample. Read app data only through its calls. Use `env.get_tool_calls()` and `env.get_state_hash()` for output.
5. Report sample-level failures before aggregate scores. Separate speech errors, intent/parameter errors, invalid or extra calls, wrong final state, out-of-scope mistakes, timeouts, and non-reproducible output.

## Evidence to record

For each evaluation, record the code revision, dataset split and sample selection, model/component versions, seed and decoding settings, exact command, exit status, elapsed time, and scoring result. Record state-hash matches, tool-call F1, empty-gold accuracy, schema-rejected calls, and timeout count when the evaluator supplies them. Keep traces bounded and free of user secrets or hidden environment files.

A correct transcript alone does not prove a correct tool plan. A valid call list alone does not prove the requested app state. A submitted hash alone does not prove reproducibility; verify replay with the same split-matched environment. Before submission, check the offline Docker run, total model-size and context limits, the 30-second per-sample budget, deterministic reruns, and one JSONL row per sample.

For implementation changes, run the narrowest meaningful behavioral tests first and the applicable integrated check before claiming completion. Reviewers compare the changed behavior with the task's issue/PR and [code standards](code_standard.md), and report only checks actually run.
