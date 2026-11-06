# Runtime Contract

## ASR preparation

Prepare current/historical user text once before planning. Transcribe each distinct
required audio content at most once/sample; repeated references and every LLM turn
reuse it. ASR-empty text is not an instruction to finish. Preserve it for planner
behavior or report malformed input explicitly. No silent ASR retry/voting or ASR
inside the tool loop. Record distinct clips, calls and reuse counts.

## Native Qwen boundary

Use the checkpoint's `apply_chat_template(..., tools=...)`, exposing eligible function
names/descriptions/schemas; disable thinking where supported. Preserve tokenizer and
template identity. Initial request contains prepared text/context/history, never gold
or future observations. Executed observations become assistant native `tool_calls`
followed by matching `tool` JSON result messages in order. Let the tokenizer own
wrappers and call identifiers; never fabricate tool results.

Accept one EOS-terminated native block per decision:

```text
<tool_call>
{"name":"contacts.search","arguments":{"query":"Lan"}}
</tool_call>
```

Or EOS-terminated neutral assistant text `Mình hiểu.` with no tool block, mapped to
canonical finish. This is an explicit constrained control policy compatible with a
native assistant message, not proof of success. Validate it against each selected
fine-tuned checkpoint. Additional finish policies need a versioned contract; do not
treat arbitrary text as success.

Permit only template-compatible outer whitespace. Reject multiple calls, prose,
extra/duplicate JSON keys, nonfinite values, non-object arguments and unfinished
blocks. Never extract the first plausible call or repair JSON. Inspect actual token
termination before special-token removal. Timeout remains timeout; token exhaustion
without EOS is output-limit failure, even if decoded text looks complete.

Reuse existing constrained-decoding dependency where compatible. Actual tokenizer
checks must prove native delimiters, name/schema binding, EOS and no-tool branch.
No unconstrained fallback. Map to the existing canonical call/finish executor boundary.
Eligible well-formed calls with schema-invalid arguments still reach `env.call` and
remain in its authoritative attempted-call log.

## Execution and clarification

One sample, one split-matched ToolEnv in its worker. Code checks eligibility and
dispatches one call before asking for another decision. Never replay historical calls.
Stop on finish or clarification returning `ok: true, waiting_for_user: true`. Other
results remain observations subject to time/steps and existing no-progress bounds.

Submit only `get_tool_calls()`/`get_state_hash()` results. Valid no-tool completion
still creates the environment and obtains its empty log/actual hash. No error path
manufactures a successful empty prediction.

## Supervisor / worker protocol

Use spawned workers and bounded framed IPC validated on receipt. Load models once,
then send `ready`; supervisor owns generation/attempt identities and allows one active
attempt. Hold exclusive run ownership. Before dispatch, append and fsync a reservation
binding sample ID, attempt ID, worker generation and configuration identity. Dispatch
nothing until reservation durability is confirmed; failure stops the run nonzero.
Reservation persistence is scheduling bookkeeping, separately measured in run wall
time, and must perform no sample input preparation, ASR or tool work. Start one
monotonic clock immediately before dispatch and send the absolute deadline.
The shared budget includes preparation, ASR, environment creation, every generation/
tool call, collection, trace closure, serialization and durable per-sample staging.

Worker writes unique staged artifacts, flushes/fsyncs/closes them, then sends
`result_ready(attempt_id, generation, paths, status)`. Accept only a matching message
received strictly before expiry after required artifacts are durable. Bound metadata
and constrain paths to the attempt staging root. Check remaining time immediately
before every tool dispatch and on return.

Supervisor waits with the remaining budget, never an unbounded IPC read. Expiry/crash
makes the attempt terminal: terminate its process group, quarantine unaccepted files
and reject late/stale-generation messages. Record OS scheduling/termination overshoot;
do not claim instantaneous GPU cancellation or rollback. Already-dispatched mutations
can have uncertain effects and must never be replayed. If termination cannot be
established, stop the batch/container instead of dispatching another sample.

All IPC operations, including dispatch writes and partial-frame reads, must remain
interruptible by the supervisor deadline. Bound frame sizes, drain worker logs without
blocking, and test a worker that never reads its request or emits only part of a frame.
Journal persistence must not overlap an active sample attempt or block its watchdog.

Recover at most once for subsequent distinct samples with a finite configurable
startup/recovery timeout. Record reload cost separately. Recovery failure stops
nonzero; prior accepted rows remain intact. Never create a new environment for the
failed sample, including through resume. Legacy runner defaults remain unchanged.

After supervisor death, reacquire exclusive run ownership and establish prior worker
termination before any new dispatch. If that cannot be established, stop. Validate
the durable reservation/acceptance journal: every reserved ID without durable
acceptance is uncertain and never redispatched, regardless of whether a tool call,
staged artifact or completion acknowledgement is visible. A corrupt/truncated journal
blocks resume. Never treat an unknown in-flight ID as unattempted or reconstruct its
state by opening another ToolEnv.

## Output and publication

Durable per-sample staging is within sample latency; timely supervisor receipt is
the success boundary. Acceptance-ledger persistence/final JSONL assembly is separately
timed batch bookkeeping and performs no inference/tool work or content alteration.
An uncertain/lost acceptance acknowledgement fails closed; staged files alone cannot
establish success after a parent crash.
Persist acceptance against the original durable reservation before dispatching the
next sample. If that write fails or is lost, retain the reservation as uncertain;
do not retry the sample or claim complete coverage. Batch finalization may retain
already durable acceptance only; it cannot promote unaccepted staging after a crash.

Publish only accepted configuration-compatible rows. Any failure, timeout or missing
selected ID blocks complete publication and exits nonzero, retaining partial evidence.
Failure-format and startup-accounting details remain organizer acceptance gates.

## Timing and evidence

Record full attempt elapsed and component spans for clips/decisions/tools/output/IPC.
Account for synchronized CUDA work where needed and disclose instrumentation overhead.
Report max, p50/p95, timeout counts/denominators, hardware, precision, memory and tokens.
Startup/recovery/packaging and total wall time remain visible. A fast average or a
different GPU is insufficient evidence of competition deadline compliance.
