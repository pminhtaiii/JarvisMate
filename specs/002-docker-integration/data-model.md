# Data Model

## IntegrationConfig

- Schema version, local ASR/planner paths and backend/protocol identifiers.
- Per-model device, precision and explicit offload; context/output limits.
- Hard sample deadline `(0,30]`, soft deadline `(0,hard)` (default 28 seconds), max
  steps and bounded startup/recovery.
- Data root/split/catalog identity, input mode, explicit selection, seed and output policy.

Reject unknown keys, invalid limits, missing snapshots and incompatible devices,
dtypes/templates before dispatch. CLI overrides only known TOML fields. Hash resolved
configuration and model/template identities for provenance/resume compatibility.
Hardware identity is evidence, not a submission field.

## PreparedRequest / ClipTranscript

PreparedRequest holds current text, ordered history/context and eligible schemas.
A per-sample map keyed by audio-content digest plus effective ASR settings maps to
one transcript/ASR event. Hash only permitted audio bytes, never environment data.
Digest/preprocessing counts toward latency. Repeated references reuse text; distinct
clips remain distinct. Preserve supplied historical text; supplied Train transcript
mode is explicitly diagnostic. The map dies with its sample; cross-run caching is
excluded so it cannot silently improve reported audio latency.

## NativeDecision / Observation

NativeDecision is canonical `call(name, arguments)` or `finish`, after native parsing.
Observation pairs an attempted call with its actual result in order. Render these as
native call/tool messages; supplied historical calls remain untrusted context. The
model cannot construct authoritative state, results or submission logs.

## SampleAttempt

- Attempt/source IDs, worker generation, configuration identity.
- Supervisor monotonic dispatch time, deadline and acceptance time.
- State: `running -> completed | needs_info | partial | timeout | failed`.
- Per-stage time, tokens, ASR counts, stop/error code and bounded diagnostic paths.
- Partial stop reasons: `soft_deadline` or `step_limit` (default 16 decisions),
  preserved in traces, metrics and report `partial_stop_reasons` counts.
- Unique staged prediction/trace paths and output durability acknowledgement.

Before dispatch, persist a reservation binding source ID, attempt ID, worker
generation and configuration identity. A reservation may exist before `running`;
after unclean supervisor exit, any reservation without durable acceptance becomes
`failed` with reason `EXECUTION_UNCERTAIN`, including when dispatch itself is unknown.
The reservation is append-only evidence: absence of staged output never clears it.

Success requires authoritative validated output, durable sample artifacts and timely
supervisor receipt and acceptance decision after a durable `accept_pending` candidate.
Only the final `accept` confirms it; a candidate alone remains unresolved. At/after
expiry is timeout. Terminal states are immutable. One
sample has one attempt/run; recovery/resume cannot replay failed/uncertain samples.
Only configuration-compatible previously accepted rows may be retained by resume.

## RunManifest / Report

Manifest records code/image/dependency/model/template identity, effective settings,
GPU/CPU/RAM/CUDA, dataset hashes/selection and terminal states. Startup/recovery/final
packaging are separately timed and included in run wall time. Denominators include
every selected sample, including failures/timeouts.

The run journal stores durable pre-dispatch reservations and accepted/failed records.
Only one supervisor owns a run at a time. Recovery validates journal records, retains
only durably accepted compatible rows, and treats all remaining reservations as
uncertain. An unreadable/truncated reservation journal blocks resume rather than
classifying affected IDs as fresh. Prior workers must be confirmed terminated first.

Prediction rows retain exactly `id`, `tool_calls`, `state_hash`. No invented failure
row or guessed hash. Incorrect completed predictions remain runtime results assessed
by evaluation. Failures are separate and block complete-submission publication.

Offline evaluation joins Train references only after inference. Report empty-gold
correctness, false empty decisions, clarification presence precision/recall, exact
intended-tool/missing-parameter correctness, unnecessary clarification and failure/time
counts. Missing-info can overlap multi-call/history categories. Use supplied-runtime
scoring when available; never reconstruct hidden state or invent aggregate scores.
