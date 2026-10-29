# Data model

All new persisted records have `metrics_schema_version: 1`; existing trace/manifest
schema fields remain unchanged. Additive fields must not invalidate legacy readers.
The new reader supports legacy records with explicit unavailable metrics and rejects
unknown metric versions. All numbers are finite and durations/counts nonnegative.

## Run measurement identity

`run_id`, revision/dirty state and existing execution identity; hardware (device,
GPU name when observable, CPU/platform), package/model/tokenizer identities,
input mode, selected IDs, split/partition identity, seed, decoding and limits;
resolved prompt identity; measurement protocol version; initialization/setup seconds.
Missing hardware fields carry an availability reason. Paths alone are not identities.

## Sample attempt

Key: `(run_id, sample_id, attempt_id)`; initial implementation has at most one newly
executed attempt per ID per run. Store source `executed|imported`, source run/attempt
for imports, status `completed|failed|incomplete`, error code/stage, steps, stop reason,
agent-loop seconds, full-attempt seconds, timing completeness and availability.
Preserve separate `agent_loop_status` and `attempt_status` for output failures after
loop success. Legacy elapsed fields mean agent-loop time, never full-attempt time.
Existing loop status `needs_info` is a successful loop outcome, mapped to completed
attempt status when durable output succeeds; retain its original loop status and
waiting-for-user stop reason rather than classifying it as failure.

Transitions: selected -> started -> completed/failed. A start without terminal
evidence is incomplete when inspected; imported completed rows do not start a new
attempt. Not-started IDs are coverage entries, not fabricated attempts. An attempt
can fail after ToolEnv completion while persisting output; retain that distinction.

## Timing span

`span_id`, `parent_span_id`, sample/attempt identity, stage, sequence/step or clip
index, start/end offsets, duration seconds, status, and availability reason.
Stages: `request`, `asr_clip`, `environment_open`, `planner_decision`,
`generation`, `tool_call`, `final_collection`, `prediction_output`, `trace_close`.
An unfinished span has null end/duration and optional observed lower-bound duration.
Nested spans overlap: ASR belongs to request; generation belongs to planner decision.
They must not be summed again into the parent's time or total.

## Generation measurement

Links to one generation span; model role `planner_action|selection_filter|asr`,
decision/clip index, input tokens, output tokens, generation seconds, rate,
stop reason `eos|max_tokens|deadline|error|unknown`, and per-field availability.
Counts may be null, never estimated from decoded text. Retain a separate
planner-decision span because rendering, tokenization and validation take time too.

## Prompt profile and resolved identity

Profile: `baseline|precise-v1`, version, instruction text, serializer version,
SHA-256 of UTF-8 content. Resolved identity additionally includes tokenizer/chat
template identity, ordered example content/bundle hash, partition hash and budget.
Keep the old baseline version/hash fields for compatibility and add the complete
effective identity rather than redefining their historical meaning.

## Partition manifest and example bundle

Proposed partition manifest v1: dataset fingerprint, seed/grouping method, and
`members` rows containing `id`, `group_id`, partition `fit|validation`, and source
sample hash. IDs are unique; an entire group belongs to one partition. An adapter
may normalize a future roadmap manifest to this contract; it must not repartition.

Bundle v1: bundle ID, partition-manifest SHA-256, split `train`, catalog fingerprint,
ordered `examples` (1-3), source/group IDs and hashes, prefix index, rationale,
`input` and `target`. Input has only request/context/history/available_tools and
strictly prior observations. Target is one call or finish, not a future observation
or final state. Provenance is outside model-visible demonstration content.
An audited bundle additionally records audit/conversion version and source dataset,
catalog and partition hashes, after exact source-prefix/target verification offline.

## Report and comparison

Report v1: source run/artifact digests, configuration, coverage categories, per-ID
attempt measurements, distributions, generation aggregates, errors, correctness
availability and limitations. Each distribution contains `n`, `missing_count`,
population label, p50/p95/p99/max (null for empty populations), and method.

Comparison v1: two report identities, declared changed factor, compatibility result,
paired IDs/counts, per-ID latency/correctness deltas, aggregate diagnostic deltas,
regression IDs, acceptance result and reasons. Evaluation evidence is attached
offline by run/prediction/selection identity; it never enters inference inputs.
