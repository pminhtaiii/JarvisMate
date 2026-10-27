# LifeMate competition benchmark

Use this page as the compact benchmark reference. The [full supplied brief](../docs/reference/lifemate-competition.md) is the source for the requirements below; it has not been independently verified against an organizer release. Team scope is summarized in the [context entry](README.md).

## Requirements in the supplied brief

### Task and sample inputs

The agent receives a spoken Vietnamese request (possibly mixed with common English), user context, available apps/tools, and earlier conversation turns. Context includes current time, timezone, location, user profile, and installed apps. Audio requests cover everyday digital services and voices from Northern, Central, and Southern Vietnam.

The agent must turn the request into ordered tool calls that leave app data in the requested state. It may ask for missing information using `sys.ask_missing_info`, including after earlier calls; return no calls (`[]`) when no installed app can handle the request.

### Tools and environment

- App tools are defined by each split's tools catalog. A sample may use only tools belonging to its `context.installed_apps`, plus `sys.ask_missing_info`.
- Tool parameters use JSON Schema; catalog extensions include `x-ref` (valid app-data ID), `x-match: "fuzzy"` (free-text match), and `x-one-of` (at least one parameter group required).
- Run each sample in exactly one `ToolEnv`, created once. Call tools through that environment; every attempted call, successful or failed, is recorded and must appear in the submitted call log. The environment validates schemas, executes calls, updates simulated app data, and returns results for subsequent reasoning.
- Read or change simulated app data only through `zaic_tools` calls. Never read, copy, or parse files under `<split>_environment/`, including `state.json`.
- Use the split-matched `zaic_tools` version. Obtain the final `state_hash` from `env.get_state_hash()` after the calls. Organizers replay calls with the matching environment version; their replay result is authoritative.

### Submission and scoring

Submit one JSON object per sample in `submission.jsonl`, with `id`, ordered `tool_calls` (`name` and `arguments`), and `state_hash`. The environment's tool-call log and final hash form the submission.

For a non-empty gold call list, a submitted call matches at most one gold call when its tool name matches, all non-fuzzy arguments are identical, and every fuzzy argument has token-F1 **greater than 0.6** after lowercasing and Unicode NFC normalization. Call order is not used for matching.

Let `M` be matched calls, `G` the number of gold calls, and `U` unmatched submitted calls, including schema-rejected calls:

- Precision `P = M / (M + U)`; recall `R = M / |G|`.
- `F1 = 2PR / (P + R)`, but the sample receives zero if its submitted `state_hash` differs from gold.
- If the gold list is empty, score is 1 only when the submitted call list is also empty; otherwise it is 0.
- `sys.ask_missing_info` is matched and scored like any other tool.
- State hash equality is exact. Free-text/fuzzy fields do not affect the hash.

The brief gives train (~1,600 labeled samples), public test (~600), and private test (~600, available after the final Docker solution is frozen). It does not state how per-sample scores are aggregated; do not infer an aggregate formula from the `N` notation.

### Submission constraints

- The final solution is a Docker image that runs fully offline; each sample has a 30-second limit on the specified A30 GPU, 16-core CPU, and 64 GB RAM.
- All models together must have fewer than 6B parameters. The LLM must have fewer than 5B parameters and at most 16,384 context tokens.
- Use only permitted public data and open-source models released before 26 October 2026; confirm license eligibility. Synthetic development data may use other services, but inference may not.
- Do not label public or private test samples for training or tuning. Fix random seeds and use deterministic decoding so organizer replay can reproduce submissions.

These constraints are described by the supplied brief. Check the actual data package and final organizer instructions before submission.

## Evidence limits

This page records the supplied benchmark description. It is not evidence that a local implementation, dataset split, Docker submission, or runtime behavior has been verified. Only execution against the supplied split-matched environment and organizer replay can establish sample results. Keep claims about capability within the runs and cases actually exercised.
