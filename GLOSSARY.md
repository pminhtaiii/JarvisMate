# LifeMate glossary

## Sample
One competition case: a spoken request, user context, installed apps, optional conversation history, and an isolated simulated app environment.

## Installed app
An app listed in a sample's context. Its catalog tools are available to that sample.

## Tool catalog
The split's definitions of tool names, parameter schemas, kinds, and returned fields. A sample may use only the tools of its installed apps, plus `sys.ask_missing_info`.

## ToolEnv
The `zaic_tools` environment created once for a sample. It executes and logs tool calls and provides the final state hash.

## Tool call
A named tool invocation with arguments. Every attempted call is logged, including one rejected by schema validation.

## Gold calls
The reference tool-call list supplied with labeled training samples or held by the evaluator for test samples.

## State hash
The value returned by `ToolEnv.get_state_hash()` after a sample's calls. It represents the final simulated app state for scoring; fuzzy free-text fields do not affect it.

## Missing-information call
`sys.ask_missing_info`, the meta tool used when required arguments are unavailable. It is scored as a tool call.

## Component owner
A teammate responsible for a bounded part of the solution end to end: its implementation, tests, integration, and any UI needed for that part. Exact ownership assignments are tracked in GitHub issues and PRs.

## MVP slice
A small, real, runnable path through audio interpretation, planning, tool execution, and measurement. It establishes an observable starting point without claiming reliable model accuracy.
