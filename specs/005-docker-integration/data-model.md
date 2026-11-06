# Data Model

## IntegrationConfig

- Schema version, local ASR/planner paths and backend/protocol identifiers.
- Per-model device, precision and explicit offload; context/output limits.
- Sample deadline `(0,30]` seconds, max steps and bounded startup/recovery.
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
- State: `running -> completed | needs_info | timeout | failed`.
- Per-stage time, tokens, ASR counts, stop/error code and bounded diagnostic paths.
- Unique staged prediction/trace paths and output durability acknowledgement.

Success requires authoritative validated output, durable sample artifacts and timely
supervisor receipt. At/after expiry is timeout. Terminal states are immutable. One
sample has one attempt/run; recovery/resume cannot replay failed/uncertain samples.
Only configuration-compatible previously accepted rows may be retained by resume.

## RunManifest / Report

Manifest records code/image/dependency/model/template identity, effective settings,
GPU/CPU/RAM/CUDA, dataset hashes/selection and terminal states. Startup/recovery/final
packaging are separately timed and included in run wall time. Denominators include
every selected sample, including failures/timeouts.

Prediction rows retain exactly `id`, `tool_calls`, `state_hash`. No invented failure
row or guessed hash. Incorrect completed predictions remain runtime results assessed
by evaluation. Failures are separate and block complete-submission publication.

Offline evaluation joins Train references only after inference. Report empty-gold
correctness, false empty decisions, clarification presence precision/recall, exact
intended-tool/missing-parameter correctness, unnecessary clarification and failure/time
counts. Missing-info can overlap multi-call/history categories. Use supplied-runtime
scoring when available; never reconstruct hidden state or invent aggregate scores.
