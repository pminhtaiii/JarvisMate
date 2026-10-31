# Train gold trajectories to planner SFT

**Status**: design only, 2026-10-27. No converter, SFT files, training dependency,
training run, or tuned model is implemented by this document. Implementation is a
later feature, conditional on the [roadmap's error-analysis gate](../../context/roadmap.md).

The accepted [native Qwen and SFT plan](../../specs/003-native-qwen-planner-sft/plan.md)
defines the model-facing protocol and training method for that feature. JSON call/
finish examples below describe canonical executor decisions; its exporter renders
them as native Qwen calls or the declared native final response. Conversion and
leakage invariants on this page remain authoritative.

## Objective and architectural boundary

Train the single general planner to predict one next action from information available
at that decision point:

```text
User Request + Context + Available Tools + Previous Observations -> Next Tool Call
```

Here, User Request includes the normalized current request and ordered conversation
history. Previous Observations contains ordered **previous calls paired with their
results**, not results detached from the calls that produced them. The complete target
space also includes the existing `finish` action so the model learns when to stop.

Preserve the [planner contract](../../specs/001-python-sample-pipeline/contracts/planner.md):

```json
{"action":"call","name":"contacts.search","arguments":{"query":"Lan"}}
```

```json
{"action":"finish"}
```

The model predicts an action, not a state mutation, a tool result, a state hash, or
executable Python. The Python sample loop retains eligibility/shape validation,
organizer argument validation and attempted-call logging, execution limits, termination,
and authoritative calls/hash collection. SFT does not change the TypeScript/Python
whole-sample boundary, the one-planner ReAct design, or the ASR interface.

## Permitted source data

Read only the official Train JSONL and Train catalog for the initial exporter:

| Train field | Export-time use | Planner-visible content |
|---|---|---|
| `id` | Provenance, partition/group ownership, row identity | Keep out of the prompt unless a future runtime contract explicitly needs it |
| `audio_text` | Current request text | Supplied transcript in transcript-mode examples |
| `context` | Validated time/timezone/location/profile/installed tools | Same whitelist as inference |
| `history` | Normalize user transcripts and preserve assistant text/calls/results in order | Historical context only; never replay its actions |
| Catalog | Resolve exact installed-tool definitions plus `sys.ask_missing_info` | Original Vietnamese schemas/descriptions, identifiers and constraints |
| `label.tool_calls` | Targets and prior action prefixes | Only calls strictly before the target become observations |
| `label.tool_results` | Pair results with their gold calls by index | Only results strictly before the target are visible |
| `label.final_state` | Excluded from conversion inputs and targets | Never exposed to planner |

Reading supplied Train labels in an offline development exporter is distinct from
feeding labels to the inference pipeline. Do not pass the raw labeled record to a
shared prompt builder. The exporter constructs an explicit whitelist and target;
the inference data boundary continues to exclude `label` entirely.

No file under `*_environment/` may be read, copied, parsed, or indexed by the exporter.
Conversion needs no `ToolEnv`, execution, reference replay, hidden-state snapshot,
or `get_state()` call: the supplied Train gold results already contain its observations.
State hashes are not SFT targets. Do not use public/private test records, catalog-derived
test task labels, test audio transcripts, or predictions from test as tuning examples.

## Partition before expanding trajectories

Apply the frozen fit/validation source-sample and duplicate-group assignment from the
[roadmap](../../context/roadmap.md#stage-2-evaluation-on-a-held-out-part-of-train).
Every row from a source sample and its conversation/history belongs to the same
partition. Never randomly split expanded steps or history audio files.

- The SFT fit file contains only fit-partition source IDs.
- If exporting teacher-forced validation rows for checkpoint diagnostics, keep them
  in a separate file; they never enter gradient updates, augmentation, few-shot
  prompts, retrieval stores, or fit-derived preprocessing statistics.
- Keep raw validation trajectories for independent closed-loop evaluation. Gold
  observations in a teacher-forced validation row are not a valid live-agent input.
- Audit cross-partition sample IDs, source/group identity, exact duplicate inputs,
  and related conversations/templates before making any training claim.

Do not repair weak validation coverage by moving inspected failing examples into fit.
A deliberate new partition is a new experiment and requires rerunning its baseline;
it must not be compared as though it retained the original held-out set.

## Stepwise conversion algorithm

For a selected Train sample, let `G = label.tool_calls`, `R = label.tool_results`,
and `n = len(G)`. The sample's normalized request, context, history, and permitted
tool definitions form `B`. A proposed canonical row contains separate `provenance`,
`input`, and `target` objects; only input/target are rendered for the trainer.

1. Validate JSON/record/history/catalog shape and the frozen partition. Require
   `len(G) == len(R)`, finite JSON values, and an object result for each call.
2. Resolve available tools using exact names in `context.installed_apps[app].tools`,
   verify app/catalog membership, and add `sys.ask_missing_info`. Keep full parameter
   schemas and Vietnamese descriptions; do not substitute the entire split catalog.
3. For each `k` from `0` to `n - 1`, emit:

   ```text
   input  = B + observations[(G[0], R[0]), ..., (G[k-1], R[k-1])]
   target = {"action": "call", "name": G[k].name, "arguments": G[k].arguments}
   ```

   At `k = 0`, current-sample observations are empty; supplied conversation history
   may still be nonempty. Never include `R[k]`, a future call/result, the complete
   current gold trajectory, `final_state`, or a gold-derived answer summary in input.
4. After an ordinary completed trajectory, emit a final row with all prior paired
   observations and target `{"action":"finish"}`. For `n = 0`, emit exactly one
   finish row with empty current observations; preserve its actual request/context/tools.
5. A gold `sys.ask_missing_info` call is supervised as an ordinary call with exact
   `tool_name` and `params`. If its corresponding result has `ok: true` and
   `waiting_for_user: true`, the runner terminates automatically: emit the call target,
   then stop conversion without an extra finish row. Earlier partial actions remain.
   Success with this field false/absent and `ok: false` are nonterminal observations,
   following the current contract. Quarantine a trajectory that continues after a
   terminal waiting result instead of inventing a user reply or dropping later gold.
6. Preserve read calls, empty searches, schema-error results, and `done: false`
   observations in their original order. Do not remove a call merely because it did
   not change state. Flag schema-invalid gold actions for review rather than turning
   them into unreviewed positive targets; runtime error-handling tests remain separate.

Validate target grammar, exact tool eligibility, parameter types/constraints and
observable ID grounding. `x-ref` describes a source, not an ID resolver; no ID is
looked up from hidden state or inferred from a future result. If a target depends on
information absent from B and the prefix, flag the sample for review. Do not silently
invent an ID, rewrite arguments, reorder gold, or replace a gold action with a guess.

### Illustrative lookup-to-action trajectory

This is an explanatory example, not an exported Train record. Assume the request is
“Nhắn Lan rằng tôi đến trễ 10 phút”, the matching context/history is included, and
the full installed schemas include `contacts.search`, `sms.send`, and the system tool.

| Decision row | Current-sample prefix visible in input | Supervised target |
|---|---|---|
| 0 | No calls/results yet | `{"action":"call","name":"contacts.search","arguments":{"query":"Lan"}}` |
| 1 | Prior search call and its result containing contact `c_07`, named Lan | `{"action":"call","name":"sms.send","arguments":{"contact_id":"c_07","content":"Tôi đến trễ 10 phút."}}` |
| 2 | Search/result, then send/result | `{"action":"finish"}` |

Row 0 must not expose `c_07` from the later lookup result. Row 1 contains no result
of the message it is about to send. At inference, the lookup result comes from the
actual environment, and may differ from a gold prefix; the planner must use that
live result. Historical calls are context, never additional current-sample targets.

## Rendering and supervision

Reuse the runtime prompt content and action grammar through a versioned, explicit
serialization contract. Preserve context time/timezone, the ordered conversation,
available tool definitions, and ordered current-sample observations. Keep provenance
outside the model input; do not expose source labels through debug summaries.

The future trainer renders each row with the selected checkpoint's chat template:

- Apply loss only to the **final next-action completion**, including its terminal
  token(s). Mask system/request/tool schemas, history, prior assistant actions, and
  previous tool results. An assistant-only mask that also trains on historical
  assistant text is insufficient for this stepwise objective.
- Treat tool results as observations, not assistant-generated answers. Do not train
  the model to fabricate them or require hidden chain-of-thought/rationale labels.
- Preserve exact strings, numbers, array order and argument keys, including enum,
  `x-one-of`, `x-ref`, and fuzzy content. Fuzzy scoring is not permission to corrupt
  gold arguments. Do not translate identifiers or replace them with tool aliases.
- Count the final rendered prompt plus reserved action-output tokens against the
  16,384-token cap. Report over-budget rows and quarantine them unless a reviewed,
  shared runtime/training compaction policy preserves required evidence. Never
  truncate away the lookup that supplies a target ID or part of the target silently.
- Preserve row boundaries and reset attention/loss boundaries if packing is later
  used. Packing, balancing and any weighting policy must be recorded and tested;
  long trajectories otherwise contribute more rows than short ones.

The initial design uses supplied Train transcripts. ASR-noise augmentation, synthetic
fit examples, or training on observed failure prefixes are separate later experiments,
restricted to fit data with provenance and reviewed targets. Do not pair a changed
ASR request with unchanged gold automatically when the meaning has changed. Gold
tool-call SFT does not train the ASR model.

## Export artifacts and planned acceptance checks

Use ignored local experiment storage, for example:

```text
.agent-work/lifemate-runs/<experiment>/sft/
  partition.json
  fit.jsonl
  validation.next_action.jsonl
  export_manifest.json
  exclusions.jsonl
```

These are proposed artifacts, not files created by this update. The validation rows
are optional teacher-forced diagnostics, not the end-to-end validation prediction file.

The manifest records source JSONL/catalog hashes and versions, split/group manifest
identity, exporter revision, prompt/template/tokenizer/base snapshot identities,
partition and row counts, per-tool/finish/missing-info distributions, token lengths,
weighting policy, quality exclusions, and any externally generated data provenance.
Track experiment configuration and concise reports; do not publish competition data,
derived examples containing it, raw traces, or model weights through the source repo.

Future exporter tests must establish:

- Every target matches its original gold call; previous observations equal the exact
  strict prefix, and current/future results never enter the corresponding input.
- Source-sample/conversation groups are disjoint across fit/validation after expansion.
- Missing-info, empty-gold, read-only, multi-app, long-history, and ordinary finish
  cases follow the specified grammar and terminal rules.
- No exporter reads hidden files or creates environments; inference still rejects
  labels and uses actual tool results. A future-result sentinel is absent from the
  input at its own action step.
- Malformed pairings, unavailable tools, unexplained ID dependencies, schema-invalid
  targets, terminal inconsistencies, and context overflow receive explicit audit entries.
- Target-only token loss masks, UTF-8/exact arguments, reproducible row identities,
  and context budgets hold after the real tokenizer/chat template is applied.

## Evaluation and checkpoint promotion

After the roadmap gate, start from the same eligible pretrained planner baseline.
Use all-linear LoRA, or QLoRA when measured training memory requires it, following
the native Qwen feature's training contract. Exact package locks and numerical
settings require its compatibility smoke and controlled experiments; this document
does not implement a trainer. Record base snapshot, trainable and deployed parameter counts,
method, seeds, data identity, hyperparameters, packages, checkpoint selection, and export.

Keep the validation partition out of fitting. Compare candidates with the unchanged
baseline on the same split/runtime/prompt/ASR configuration; report both teacher-forced
next-action diagnostics and **closed-loop** transcript/audio execution. In closed-loop
evaluation use predicted actions and actual environment observations, never gold
prefixes. This checks behavior after a model deviates from the gold trajectory.

Predeclare target metrics/regression tolerances, inspect error categories, and measure
latency and memory before promoting a candidate. Reject changes supported only by
lower training loss or memorized next-call accuracy. Keep the pretrained baseline as
the fallback when gains, reproducibility, or competition eligibility are unproven.

## Technical-rule checklist

These planned checks follow the supplied [LifeMate 2026 technical rules](../reference/lifemate-competition.md#technical-requirements--rules)
and [benchmark reference](../../context/benchmark.md); consult final organizer
instructions before submission. This is not a claim that a future checkpoint complies.

| Rule | Planned enforcement/evidence |
|---|---|
| Permitted data/models | Use licensed public data/open-source base resources released before 26 October 2026; document eligibility and any permitted development-only synthetic sources |
| No test labeling for tuning | Source exporter restricted to Train fit; no manual/external-service/model labeling of public/private test for training or tuning |
| State access | No direct environment-file access in conversion or inference; only the original split-matched tools access app state |
| One environment and full log | One `ToolEnv` per sample in each independent inference run; retain every actual attempted call and its environment-generated hash; no automatic reset/retry of uncertain execution |
| Whole-system size | Fewer than 6B deployed parameters including ASR, planner and any other component; the LLM itself has fewer than 5B |
| Adapters and quantization | Count base plus any unmerged adapter/other deployed weights conservatively; quantization does not reduce parameter count; merging does not justify removing the base from accounting |
| Context | At most 16,384 tokens including reserved generation, measured with the actual inference template/tokenizer |
| Offline execution | Package local checkpoint/tokenizer/ASR/runtime; no teacher, download, external model/API or training service at inference |
| Deadline/hardware | Measure the complete audio-to-tools sample within 30 seconds on the specified A30/16-core CPU/64 GB RAM setup; slower development runs do not establish compliance |
| Reproducibility | Fixed Python/NumPy/PyTorch seeds, deterministic ASR/LLM decoding, pinned provenance and measured reruns of the deployed export |
| Submission | Exact environment `tool_calls` and `state_hash` in one JSONL row per sample, offline Docker and full coverage checked separately from validation/training |

Only the selected ASR/planner configuration should be deployed and counted as that
candidate system. Training infrastructure, held-out references, and the SFT exporter
do not become extra inference capabilities. The model still has no authority to
bypass deterministic execution controls or read hidden state.
