# LifeMate runtime architecture

## Agreed outline

Keep speech recognition, request/tool planning, and tool execution behind separate interfaces. The MVP path is:

Use one general planner for the MVP, with only the current sample's available tools exposed; cross-domain requests remain within its sample loop. See [ADR 008](../docs/adr/008-single-general-planner-for-mvp.md) for the decision and trade-off with domain specialists.

1. Receive the sample audio and its provided context, conversation history, installed-app list, and tool definitions.
2. Run ASR to produce request text for planning.
3. Create exactly one `ToolEnv` for the sample. Use a structured ReAct loop: the planner proposes a tool call using the request, sample context, installed-app tools, and prior observations; deterministic code validates and executes it through that environment. Return the result to the planner for its next decision. Use `sys.ask_missing_info` when required information is missing, and produce no calls for unsupported requests.
4. Bound the loop and preserve the no-automatic-retry policy for uncertain executions. Every attempted call goes through the same environment. Prioritize a working baseline before latency optimization while measuring elapsed time; the competition deadline remains a submission constraint. See [ADR 007](../docs/adr/007-react-first-runnable-baseline.md) for the trade-off and supersession of ADR 006.
5. Submit the environment's recorded tool-call log and final `state_hash`.

This outline follows the [benchmark](benchmark.md) and [glossary](../GLOSSARY.md). Accepted model experiments and open implementation choices are recorded in the [technology stack](tech_stack.md).

Development runs must also produce per-sample execution traces under [ADR 009](../docs/adr/009-require-execution-traces-from-first-baseline.md); capture requirements live in [testing guidance](testing.md).

## Trust and data boundaries

The initial pipeline uses the organizer's simulated environment; real-service integrations are deferred. Uploaded Vietnamese catalogs and split-specific simulator source are under `tools/`; the package READMEs in `tools/train/` and `tools/test/` are translated into English. Input samples, audio, and per-sample environments are required before a real benchmark run; the uploaded tool code alone is not a complete dataset.

- Treat the sample input, catalog schemas, and tool results as the available evidence for planning. The set of callable app tools is limited to `context.installed_apps`, plus `sys.ask_missing_info`.
- The simulated app state is owned by `zaic_tools`. Read or change it only by calling tools on the sample's single `ToolEnv`; never read, copy, or parse files under `<split>_environment/`.
- Every attempted call, including a schema-rejected call, is recorded and counts in evaluation. Use the split-matched environment and obtain the submitted state hash from that environment after execution.
- The environment call log and hash are the observable execution result. Organizer replay is authoritative for final scoring.

## Score-oriented design

Optimize for correct final state and matched calls together. Exact state-hash mismatch zeroes a non-empty-gold sample's score; extra or rejected calls reduce precision, and missed gold calls reduce recall. Empty-gold samples require an empty call list. These rules favor constrained tool selection, schema-valid arguments, and preserving the required call sequence for state changes. See the [benchmark reference](benchmark.md) for formulas and qualifications.

## Provisional contracts

Build the Python worker with a direct command-line entry point before connecting the TypeScript harness. First verify the training-transcript path, keeping labels out of planner inputs, then connect ASR for the audio path. These are implementation checkpoints, not substitutes for audio-input submission evaluation.

The module boundaries above are agreed, but detailed interfaces and orchestration contracts remain provisional. Keep ASR, planning, and execution replaceable; agree exact input/output contracts with component owners before implementation depends on them. TypeScript owns the outer harness; Python owns each sample's complete execution loop and single `ToolEnv`. See the [technology stack](tech_stack.md) for model experiments, runtime choices, and unresolved failure behavior. Component ownership and the MVP scenario remain open in the [project context](README.md).

The [team workflow](team.md) defines ownership and shared coordination. Track interface discussions and progress in GitHub issues or pull requests, and update concise project context when a settled choice affects other components.
