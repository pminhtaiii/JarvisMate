# LifeMate runtime architecture

## Agreed outline

Keep speech recognition, request/tool planning, and tool execution behind separate interfaces. The MVP path is:

1. Receive the sample audio and its provided context, conversation history, installed-app list, and tool definitions.
2. Run ASR to produce request text for planning.
3. Create exactly one `ToolEnv` for the sample. Plan and execute calls through it using the request, sample context, installed-app tools, and results from earlier calls. Use `sys.ask_missing_info` when required information is missing, and produce no calls for unsupported requests.
4. Continue planning only as needed after observed tool results; every attempted call goes through that same environment.
5. Submit the environment's recorded tool-call log and final `state_hash`.

This outline follows the [benchmark](benchmark.md) and [glossary](../GLOSSARY.md). Exact model, framework, and implementation stack are undecided.

## Trust and data boundaries

- Treat the sample input, catalog schemas, and tool results as the available evidence for planning. The set of callable app tools is limited to `context.installed_apps`, plus `sys.ask_missing_info`.
- The simulated app state is owned by `zaic_tools`. Read or change it only by calling tools on the sample's single `ToolEnv`; never read, copy, or parse files under `<split>_environment/`.
- Every attempted call, including a schema-rejected call, is recorded and counts in evaluation. Use the split-matched environment and obtain the submitted state hash from that environment after execution.
- The environment call log and hash are the observable execution result. Organizer replay is authoritative for final scoring.

## Score-oriented design

Optimize for correct final state and matched calls together. Exact state-hash mismatch zeroes a non-empty-gold sample's score; extra or rejected calls reduce precision, and missed gold calls reduce recall. Empty-gold samples require an empty call list. These rules favor constrained tool selection, schema-valid arguments, and preserving the required call sequence for state changes. See the [benchmark reference](benchmark.md) for formulas and qualifications.

## Provisional contracts

The module boundaries above are agreed, but detailed interfaces and orchestration contracts remain provisional. Keep ASR, planning, and execution replaceable; agree exact input/output contracts with component owners before implementation depends on them. Model choice, component ownership, frontend timing, and the MVP scenario remain open in the [project context](README.md). No specific model, framework, service, or runtime stack is established here.

The [team workflow](team.md) defines ownership and shared coordination. Track interface discussions and progress in GitHub issues or pull requests, and update concise project context when a settled choice affects other components.
