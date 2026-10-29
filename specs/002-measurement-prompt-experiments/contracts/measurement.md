# Measurement and reporting contract

These are proposed interfaces, not currently implemented commands.

## Integration

Keep `Planner.next_action(...) -> str` and `ASR.transcribe(...) -> str`. Local adapters
accept an optional metadata sink; each actual generation emits a start and terminal
record through it, including on exceptions where observable. The sample orchestrator
owns the sink and IDs. Adapters without this optional capability retain orchestration
wall timing and explicitly unavailable generation details. Never reuse stale detail
records from a prior decision or clip. Fake sinks/clocks enable deterministic tests.

Trace metadata carries versioned span/generation records, independent of
`--trace-payloads`. Continue existing bounds and sanitization. Token counts, stage
names and durations do not require logging raw prompts or audio. Preserve existing
trace I/O failures; instrumentation must not suppress an execution error.

## Timing boundaries

- `agent_loop_seconds`: existing run_sample boundary, starting before request
  preparation and ending after final authoritative collection or failed outcome.
- All new span offsets use one attempt origin immediately before trace creation;
  preserve existing trace elapsed offsets as legacy fields, not this new origin.
- `sample_total_seconds`: CLI wall interval immediately before trace creation until
  prediction row validation/write/flush/fsync and trace close have completed, or
  failure cleanup has returned. This is the conservative under-30-second metric.
  On failure without a row, stop after trace close/available cleanup, before terminal
  failure-summary bookkeeping. Do not wait for that summary write inside this interval.
- Persist terminal attempt summary after measuring that interval. Report its write
  cost, run-manifest publication, offline reports, preflight/fingerprinting and model
  initialization separately as run overhead; these exclusions must be visible.
  Do not equate a successful agent loop with durable successful output. Existing
  `sample_finished` means agent-loop completion only; preserve `agent_loop_status`
  separately from `attempt_status`. An output failure after loop success is a failed
  attempt with `agent_loop_status=completed`, not an inference retry.
- `request` includes per-clip transcription and preparation; classify clips as
  historical/current without exposing file content. `environment_open` includes
  creation of the sample's single ToolEnv. Time every planner decision, generation,
  env call and authoritative log/hash collection, including attempted rejects/errors.
- Model offload/onload during the sample belongs to sample time, even if it is
  outside a generation span. Overlapping subspans are diagnostic, not additive.
  Report unattributed time instead of forcing all spans to sum to total.

Use the same injectable monotonic host clock for offsets/durations. Local CUDA
adapters wait for required device work before reading generation boundaries (device
synchronization before/after the generation, once per call, never per token).
Record this protocol; compare candidates with identical instrumentation. CPU uses
the same wall boundaries. Full-attempt time is diagnostic in this measurement slice:
preserve the existing cooperative agent-loop timer, starting inside run_sample after
CLI trace creation and ending before CLI output publication. Instrumentation inside
that loop consumes its existing budget; do not increase the configured loop timeout.
Trace creation/output time is included in the separate full-attempt measurement but
is not newly enforced by that loop timer. A completed attempt with total >=30 seconds
remains completed for existing persistence/resume semantics and is independently
flagged over budget in the report. Do not retroactively raise TIME_LIMIT or discard
a committed row. Absolute full-attempt deadline enforcement and hard termination are
separate follow-up work; neither is delivered by this measurement feature.

An error/process loss can prevent a final time from being persisted. Keep last
observable elapsed as a lower bound and mark total unknown; never claim that it met
the deadline. Old manifests' `elapsed` is agent-loop time, not full sample time.

## Tokens and rates

Input tokens: actual model input sequence length, including template/examples for
planner generations. Output tokens: returned generated suffix IDs, excluding prompt
and padding, including emitted EOS/special tokens; document that convention in the
report. For ASR use decoder-generated token count where available; audio features
are not text input tokens. Unknown input counts remain null.

Generation duration spans the completed model generation call, excluding prompt
render/tokenization. Rate is output tokens / generation seconds when both are known
and duration >0; otherwise null with a reason. Aggregate rate is sum(tokens)/sum(time)
over the same complete eligible records, never a mean of individual rates. Keep
ASR, action, and selection-filter populations separate. Record actual termination
where observable; lack of EOS alone does not prove the deadline caused termination.

## Persistence and compatibility

Keep predictions exactly `{id, tool_calls, state_hash}`. Extend manifests with
versioned `measurements`; existing `samples` timing keys retain their meaning.
Persist failed SampleOutcome timings/steps through both continued and fatal paths.
Do not alter continuation/retry/import behavior. Imported metrics retain original
identity and are excluded from current-run timing distributions.

Write derived canonical `report.json` and its presentation `report.md` beside the run manifest after completion
or handled failure, atomically per file. A report failure is separately visible and
must not overwrite the original inference error, invalidate durable predictions or
claim the batch completed. Standalone report commands return nonzero on invalid
artifacts/write failures. Existing trace limits apply; exceeded capacity is explicit.

## CLI

```text
lifemate report --run-dir PATH [--evaluation-file PATH]
lifemate compare-runs --baseline-run PATH --candidate-run PATH
    --factor harness|instructions|few-shot
    [--baseline-evaluation PATH --candidate-evaluation PATH]
    --output-dir NEW_PATH
```

Both commands are offline artifact readers; they never load models or create ToolEnv.
`report` regenerates derived files without overwriting input traces/manifests or
predictions. `compare-runs` creates a new output directory and writes comparison
JSON/Markdown; it never overwrites source runs. Reject output under organizer input
paths when known from manifests. For compare-runs, reject overlap between its output
directory and either source run. Report regeneration explicitly allows replacing
only report.json/report.md inside its own run directory; never replace source
manifest/traces/predictions or an evaluation sidecar at those reserved output paths.
Validate persisted
schema, finite values, IDs, duplicate/terminal conflicts and source-run consistency.
Preflight/model-load failures produce run-level evidence, not sample time zero.

## Distributions and evidence

Use nearest-rank `sorted_values[ceil(p*n)-1]` for p=.50,.95,.99. Empty population
values are null. Include every newly started attempt with known total, including
failed attempts. Also show success-only distributions explicitly labeled. Stage
distributions use observed per-sample stage totals; per-invocation views carry their
own counts. Missing/incomplete stages are not filled with zero. Not-started and
imports stay outside current timing populations. Flag p95/p99 as descriptive tails
at small n (below 20/100 respectively); show slowest IDs.

Count separately: failed, TIME_LIMIT, known total >=30s, unknown total, configured
timeout (which may exceed 30 in development), imported and not-started. At exactly
30 seconds the strict target is missed. A configured 30-second timer does not prove
compliance. Include non-A30, transcript-mode, incomplete and mixed-resume limitations.

Correctness defaults to `not_evaluated`. Optional evaluation file v1 identifies run
ID, prediction SHA-256, selected IDs and evaluator provenance; rows identify sample,
`gold_empty` (boolean), `sample_score` (number in [0,1]), state-hash match,
call precision/recall/F1 where defined, empty-gold result, and available error counts.
`sample_score` is supplied by the separate evaluator under the benchmark's two cases:

- Nonempty gold: call F1 when state hashes match, otherwise zero.
- Empty gold: one exactly when the submitted call list is empty, otherwise zero;
  do not apply the nonempty-gold hash gate or fabricate call F1 for this case.

Reports may show partial evaluation with unavailable fields explicitly marked.
Acceptance requires one evaluator-provided gold_empty/sample_score row for every
selected ID, including failures when the evaluator can establish a score; missing
rows cannot be dropped or assumed zero to manufacture full coverage. Validate
ranges, uniqueness, identity and consistency with available predictions/hash/call
metrics. This feature consumes evaluation evidence; it never reads gold labels or
environment files to fill missing scores and implements no new scoring algorithm.
