# Artifact and evidence contract

## Run directory

Create a fresh explicitly named directory under `.agent-work/lifemate-runs/`:

```text
<run>/
  manifest.json
  predictions.partial.jsonl
  predictions.jsonl           # appears only after successful selected coverage
  traces/<sample-id>.jsonl
```

Do not overwrite/resume earlier runs. Use UTF-8, finite JSON values, and stable
serialization. A subset filename is intentionally `predictions.jsonl`; the manifest
must not present it as a complete competition submission.

## Prediction rows

```json
{"id":"train_1748","tool_calls":[{"name":"contacts.search","arguments":{"query":"Lan"}}],"state_hash":"<environment-provided hash>"}
```

Exactly those three top-level fields. Preserve call order and exact argument values
from `env.get_tool_calls()`, and use `env.get_state_hash()` unchanged. Never create
a hash from hand-built app data or append trace/model/error fields to prediction rows.
Do not emit a successful row for failed execution; a legitimate empty call list or
missing-information outcome can have a successful row.

## Manifest

- `schema_version`, unique run identity, start/end times, `status`:
  `running`, `completed`, or `failed`.
- Dataset split, dataset/catalog identity, total record count, selected IDs and mode,
  `coverage_scope`: `subset` or `full_split`, completed/failed/not-started IDs.
- Code revision and dirty-working-tree indicator, Python/package versions,
  model paths/snapshot identities and parameter counts, device/dtype, seed,
  decoding settings, prompt version/hash, context/generation/step/deadline settings.
- Phase and per-sample timing, model initialization separately from sample execution.
- Trace capture mode and bounds, result/trace paths, error code/stage/message if failed.
- `submission_ready`: false for this feature's subset and transcript runs. Even a
  full audio run is not declared ready until final organizer checks are separately recorded.

Update the manifest using a sibling temporary file and atomic replacement. Completion
is not inferred from file existence or exit code alone. Hard-crashed `running` manifests
are incomplete; recovery is manual and never recreates an environment automatically.

## Trace events

Every event includes schema version, run/sample identity, increasing per-sample
sequence, event kind, elapsed monotonic time, and step index when applicable.
Required kinds: `sample_started`, `request_prepared`, `planner_action`,
`validation_result`, `tool_call_started`, `tool_call_result`, `sample_finished`,
and `sample_failed` when a failure occurs. Trace run-level preflight/model-load failures
in the manifest even when no sample has started.

Metadata traces include tool names, argument/result field names, availability names,
counts/timing/status, and explicit `payload_omitted` markers. With `--trace-payloads`,
record sanitized request/transcript text, planner action content, proposed/actual
arguments, and observed results for dataset debugging. Preserve the full in-memory
tool observation for planning; trace truncation must not alter behavior.

Baseline-validation runs require `--trace-payloads`. Metadata-only runs remain useful
operational checks but cannot fulfill the baseline's detailed evidence acceptance.

Default serialized payload cap: 64 KiB per event; total trace cap: 8 MiB per sample.
Mark truncation/redaction and original size explicitly. Redact credential/token-like
fields and avoid duplicating irrelevant profile data. Reserve enough trace capacity
for terminal metadata: exceeding the total cap fails the sample rather than silently
dropping future action evidence. Never include raw hidden files or hidden reasoning.

Flush `tool_call_started` before dispatch. Flush outcomes/terminal events so a crash
does not turn a recorded call into apparent absence. If a trace write fails, stop
before the next effect, surface `TRACE_IO`, and make a best-effort manifest error
update; do not claim evidence was saved when storage prevented it.

## Output lifecycle

1. Preflight selection, create a fresh run manifest, and load models. Failure summary
   is still visible if directory creation itself fails.
2. Open each sample trace before preparing that sample. A completed sample must have
   a terminal trace event, then append/flush its authoritative prediction row to
   `predictions.partial.jsonl`, then update completion progress in the manifest.
3. On any failure, stop; keep partial rows and traces. Failed-sample log/hash, when
   retrievable, are diagnostic trace data only.
4. Once all selected samples succeed, validate exact row count/order/IDs/schema,
   atomically rename the partial file to `predictions.jsonl`, then mark the manifest
   completed. A publication/manifest failure returns nonzero; require the completed
   manifest as well as the final file before treating the artifact as complete.

## Evaluation scope

Compare actual tool paths against training references in a separate evaluation/inspection
step; no label enters inference. Report differences and available organizer metrics,
not an invented aggregate score. Controlled tests, real-runtime smoke tests, real-model
transcript runs, and real-model audio runs are distinct evidence classes.
