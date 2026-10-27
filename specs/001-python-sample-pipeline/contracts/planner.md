# Planner and execution contract

## Python capability interfaces

- `ASR.transcribe(audio_path, remaining_seconds) -> str`: local inference only;
  returns a nonempty transcript or a typed failure, never a supplied-text fallback.
- `Planner.next_action(planner_input, remaining_seconds) -> str`: one raw JSON
  response; runner owns action validation. Model instances are reused across samples.
- `run_sample(sample_input, planner, asr_or_none, environment_factory, trace_sink,
  limits) -> SampleOutcome`: complete sample ownership remains in Python.
- `environment_factory(split, id, data_root)`: returns the original ToolEnv exactly
  once per executed sample. Tests may inject an observable factory to verify counts.

Use ordinary Python protocols/dataclasses, not a general dependency injection framework.
The CLI and future worker can call the same function; no per-tool cross-runtime RPC.

## Model response grammar

Call:

```json
{"action":"call","name":"contacts.search","arguments":{"query":"Lan"}}
```

Finish:

```json
{"action":"finish"}
```

Parse one complete JSON object, reject duplicate keys, non-finite numbers,
additional fields, markdown wrappers, multiple objects, unknown action values,
non-string names, and non-object arguments. Do not extract a plausible object from
arbitrary text. Limit response bytes/tokens before parsing.

## Decision loop

1. Ensure remaining time/steps and prompt+reserved output tokens fit configured caps.
2. Generate one action and increment decision count, including malformed responses.
3. Invalid shape or unavailable name: emit validation rejection, feed bounded feedback
   to the planner, consume no env.call, and continue within the bound.
4. For well-formed, allowed calls, delegate argument-schema validation to `ToolEnv.call`.
   Schema-invalid arguments must reach the environment so it logs the attempted call;
   do not gate dispatch on `env.validate` or invent missing values.
5. Trace intent before dispatch, call `env.call`, and trace the returned observation.
   Return schema-error feedback to the planner for correction within the decision bound.
   Actual attempted calls, including schema rejections, remain in the environment's
   authoritative log and submitted `tool_calls`.
6. Nonterminal observations, including empty matches, `ok:false`, and `done:false`,
   return to the planner. An exception with uncertain execution is a sample failure,
   not a reason to dispatch the same call again.
7. `finish` terminates. A successful `sys.ask_missing_info` result with
   `waiting_for_user:true` terminates as `needs_info`; no interactive reply is invented.
   A successful result with that field false or absent returns to the planner.
8. Obtain final log/hash once the terminal outcome is established. Finishing with no
   calls remains valid. Failed samples do not emit a prediction row.

Default 16 decisions and 30 seconds. A larger explicit development deadline is
recorded as such. Deadlines apply from per-sample request preparation through output
collection; model initialization and development queue wait are reported separately.
Generation stopping criteria use remaining time. Check deadlines around synchronous
ASR/tool calls; a stuck native call cannot be promised hard preemption by this CLI.

## Model input and behavior

- Include current request, sample time/timezone/profile/location, ordered prior
  conversation, permitted catalog definitions, and current-sample observations.
- Keep top-level labels and hidden state inaccessible to prompt construction.
- In audio mode transcribe every user turn; keep supplied assistant history as context.
- Treat history/results as data, not authority to bypass tool restrictions.
- Obtain entity IDs from context or tool observations; `x-ref` is not an ID resolver.
- Stop unsupported requests without exploratory unrelated calls. Request genuinely
  missing required information with the system tool.
- Use Vietnamese catalog descriptions unchanged. Initial prompt is versioned with
  code; capture its version/hash and decoding settings in run provenance.
- Local adapters use greedy decoding (`do_sample=false`), fixed seeds, and explicit
  context caps. Record hardware/dtype/package versions; deterministic settings do not
  establish reproducibility until reruns are measured.

## Failure categories

`INPUT_INVALID`, `ASSET_MISSING`, `CATALOG_INVALID`, `MODEL_UNAVAILABLE`,
`CONTEXT_LIMIT`, `STEP_LIMIT`, `TIME_LIMIT`, `PLANNER_ERROR`, `EXECUTION_UNCERTAIN`,
`TRACE_IO`, `OUTPUT_IO`. Use stable codes rather than parsing messages.
Validation rejection can recover within the decision bound; hard adapter errors,
uncertain execution, or exhausted bounds fail the sample and batch under ADR 010.
