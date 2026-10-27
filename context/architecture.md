# LifeMate runtime architecture

## Agreed outline

Keep speech recognition, request/tool planning, and tool execution behind separate interfaces. The MVP path is:

1. Receive the sample audio and its provided context, conversation history, installed-app list, and tool definitions.
2. Run ASR to produce request text for planning.
3. Create exactly one `ToolEnv` for the sample. Produce a structured plan with explicit dependencies using the request, sample context, and installed-app tools. Deterministic code executes resolved steps through that environment and binds returned values only through explicit validated rules. Use `sys.ask_missing_info` when required information is missing, and produce no calls for unsupported requests.
4. Pause for selective replanning when a required decision remains unresolved or observed results invalidate the remaining plan. Give the planner completed calls and observed results; revise remaining work without blindly repeating completed effects. Bound the loop and preserve the no-automatic-retry policy for uncertain executions. Every attempted call goes through the same environment; completing a plan requires no extra model pass solely for a closing message. See [ADR 006](../docs/adr/006-plan-execute-with-selective-replanning.md) for the trade-off.
5. Submit the environment's recorded tool-call log and final `state_hash`.

This outline follows the [benchmark](benchmark.md) and [glossary](../GLOSSARY.md). Accepted model experiments and open implementation choices are recorded in the [technology stack](tech_stack.md).

## Trust and data boundaries

- Treat the sample input, catalog schemas, and tool results as the available evidence for planning. The set of callable app tools is limited to `context.installed_apps`, plus `sys.ask_missing_info`.
- The simulated app state is owned by `zaic_tools`. Read or change it only by calling tools on the sample's single `ToolEnv`; never read, copy, or parse files under `<split>_environment/`.
- Every attempted call, including a schema-rejected call, is recorded and counts in evaluation. Use the split-matched environment and obtain the submitted state hash from that environment after execution.
- The environment call log and hash are the observable execution result. Organizer replay is authoritative for final scoring.

## Score-oriented design

Optimize for correct final state and matched calls together. Exact state-hash mismatch zeroes a non-empty-gold sample's score; extra or rejected calls reduce precision, and missed gold calls reduce recall. Empty-gold samples require an empty call list. These rules favor constrained tool selection, schema-valid arguments, and preserving the required call sequence for state changes. See the [benchmark reference](benchmark.md) for formulas and qualifications.

## Provisional contracts

The module boundaries above are agreed, but detailed interfaces and orchestration contracts remain provisional. Keep ASR, planning, and execution replaceable; agree exact input/output contracts with component owners before implementation depends on them. TypeScript owns the outer harness; Python owns each sample's complete execution loop and single `ToolEnv`. See the [technology stack](tech_stack.md) for model experiments, runtime choices, and unresolved failure behavior. Component ownership and the MVP scenario remain open in the [project context](README.md).

The [team workflow](team.md) defines ownership and shared coordination. Track interface discussions and progress in GitHub issues or pull requests, and update concise project context when a settled choice affects other components.
