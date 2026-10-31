# Native Qwen protocol contract

## Selection and identity

Proposed run option: `--planner-protocol structured-v1|qwen-native-v1`.
Default remains structured during comparison. Store protocol, prompt content,
constraint version, tokenizer/chat-template hash and final-text policy in provenance
and resume compatibility. An unknown protocol or incompatible instruction/few-shot
profile fails preflight. Existing feature 002 baseline rendering stays byte-identical
for structured control. Never reuse mixed-protocol completed rows for acceptance.

The inference API remains `Planner.next_action(input, remaining_seconds) -> str`
returning canonical call/finish JSON. Native model output is interpreted inside the
adapter; the runner independently validates canonical shape and eligibility.

## Input rendering

- Use the selected checkpoint's `apply_chat_template` and exact tokenizer. Pass
  eligible tools through `tools=` as `{type:"function", function:{name,description,parameters}}`.
  Keep exact names/descriptions/parameters including extension metadata. Preserve
  app/kind constraints as model-visible metadata/descriptions where needed; executor
  eligibility remains deterministic. Do not send the whole split catalog.
- Initial system content retains ID grounding, relative-time, missing-info,
  no-extra-call and untrusted-data rules, expressed for native calls and neutral finish.
- Initial user content has request/context/history. Supplied history remains data
  and is not replayed; current-sample tool schemas are not duplicated in user content.
- Each executed observation becomes an assistant call with native `tool_calls`
  and a following `tool` message containing the exact result object serialized as JSON.
  Call name/arguments/result order is preserved. Let the tokenizer add wrappers.
- A local validation rejection is correction data, explicitly marking no execution;
  it cannot be encoded as a successful tool result. Avoid re-inserting malformed
  output as executable native call structure. Selection-filter JSON stays separate.
- Keep labels, final_state, sample provenance and future observations out of inputs.
  Count rendered tokens plus reserved output before generation, max 16,384.

## Accepted model completions

One complete native block with precisely name and object-valued arguments:

```text
<tool_call>
{"name":"contacts.search","arguments":{"query":"Lan"}}
</tool_call>
```

Or the exact final assistant content `Mình hiểu.`. Both require normal termination
at tokenizer EOS (`<|im_end|>` for this checkpoint), not merely valid-looking text.
Allow only template-compatible insignificant whitespace around the call block;
reject prose, extra blocks/keys, markdown, duplicate JSON keys, non-finite values,
non-object arguments, unknown names and unfinished delimiters. Preserve JSON values
exactly; never repair, extract a plausible inner object, or select only the first call.

After validation the adapter returns one canonical decision:

```json
{"action":"call","name":"contacts.search","arguments":{"query":"Lan"}}
```

Or `{"action":"finish"}`. The neutral text is a declared control policy, not proof
of task success, not an organizer tool, and not part of submission JSONL.

## Constraints, termination and failures

Reuse LMFE 0.11.3 to compose literal prefix/suffix and per-tool argument schemas,
with existing x-one-of branch handling and name/schema binding. Union with the exact
final-text branch. EOS is admitted only once a branch can end; do not include EOS
in the literal character grammar. Prove this with actual tokenizer/LMFE tests.
No unconstrained fallback is allowed.

Inspect generated token IDs before `skip_special_tokens` decoding loses EOS evidence.
Deadline expiration is TIME_LIMIT even if decoded text looks complete. Exhaustion
without terminal EOS is OUTPUT_LIMIT, including a syntactically complete call that
used its full output budget. Malformed/ambiguous completed output is PLANNER_FORMAT.
No such response dispatches a tool or maps to finish. Preserve current hard local
adapter failure policy; fake/custom planner canonical rejection behavior stays unchanged.

ToolEnv remains the final argument validator. Well-formed eligible calls with invalid
arguments still go through `env.call` and remain logged; grammar constrains normal
generation but parsing must not introduce a new pre-dispatch schema rejection policy.
Uncertain execution is never retried. Successful `sys.ask_missing_info` terminates
only for `ok:true` and `waiting_for_user:true`; otherwise its real result is observed.

## Verification

Cover native rendering, eligible catalog and extension preservation, literal delimiters,
actual EOS, zero-argument tools, Unicode, malformed/multiple output, no-call finish,
token/time cuts, schema rejection logging, clarification and filter feedback.
Record bounded opt-in native output/stop evidence and canonical action. Routine logs
stay metadata-only; authoritative calls and hashes are unchanged.
