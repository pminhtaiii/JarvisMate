# Data model

These are proposed Python/dataclass and JSON contracts, not new glossary terms or
persisted database entities. Validate all external JSON before constructing them.

## RunConfig

- `split`: `train` or `public_test`; one split/runtime per invocation.
- `data_root`, `runtime_dir`: resolved paths; organizer inputs are read-only to execution code.
- `input_mode`: `transcript` (train only) or `audio`.
- `selected_ids`: distinct nonempty list, or explicit all-selection; execution uses
  dataset order. Unknown IDs and simultaneous ID/all selection are errors.
- `planner_model_path`, `asr_model_path`: local directories for real inference.
  ASR path required only in audio mode; snapshot identities recorded in manifest.
- `device`: explicit `cpu` or `cuda`; no silent device substitution.
- `max_steps`: positive integer, default 16; `sample_timeout_seconds`: positive,
  default 30. `context_limit`: at most 16,384 including reserved output tokens.
- `run_dir`: fresh directory under ignored local artifacts; collisions are errors.
- `trace_payloads`: false by default; true in the detailed baseline quickstart.

## SampleInput and RequestContext

- `id`: nonempty string safe for use as an artifact identifier (no separators/traversal).
- `audio`: split-relative path; resolve and require containment, including symlinks.
- `audio_text`: training-only supplied transcript; never carried into audio-mode planner input.
- `context`: validated `current_time`, `timezone`, location, profile, installed apps.
- `history`: ordered user/assistant entries; preserve text and historical calls/results.
- `label`: deliberately absent from SampleInput. Dataset evaluation references are
  separate data and not passed to the planner or ASR adapters.

Audio mode resolves current and user-history paths and transcribes them before
planning. Transcript mode takes current and user-history `audio_text` values.
Assistant history may include optional `tool_calls`/`tool_results`; these are
observations from the past, not dispatch instructions.

## ToolSpec and PlannerInput

ToolSpec is the original catalog definition. Build available definitions by exact
declared names/app membership plus the system tool. Unknown references fail preflight.
Descriptions stay Vietnamese. `x-ref` does not supply a resolved entity ID.

PlannerInput combines context, normalized request/history, available definitions,
completed current-sample calls/results, and validation feedback. It contains neither
training labels nor hidden app state. Count the serialized prompt before generation.

## PlannerAction

Discriminated union documented in [planner contract](contracts/planner.md):
`call` with `name/arguments`, or `finish`. Strict field/type validation; one action
per response. Every response counts toward max_steps, even if rejected.

## Observation

- `step`: one-based model decision index.
- `kind`: `validation_rejection` or `tool_result`.
- Validation rejection: machine category plus bounded organizer/schema feedback;
  no env.call took place.
- Tool result: dispatched `name/arguments` and exact returned result for in-memory
  reasoning. Traces may bound/redact payloads; never substitute the trace copy as the
  authoritative in-memory observation.

## SampleOutcome

- `status`: `completed`, `needs_info`, or `failed`.
- `id`, timing, model/tool decision counts, trace path, stop reason.
- Successful/needs-info result: `id`, `tool_calls`, `state_hash` only.
- Failure: `error_code`, bounded message, stage, last known step, and optional
  diagnostic environment log/hash if still safely obtainable. No successful row.
- `completed` with no calls is valid, not an exception. `needs_info` preserves prior calls.

State transitions:

```text
selected -> preflighted -> preparing_request -> environment_open -> planning
planning -> validation_rejection -> planning
planning -> dispatch -> observation -> planning
planning -> completed
dispatch(sys.ask_missing_info) -> needs_info
any active stage -> failed -> batch_stopped
```

Model loading is run-level; per-sample request preparation includes ASR and is timed.
Preflight failure opens zero environments. After environment_open, the sample is
never reset/retried by the runner. A trace-storage failure follows the same stop rule.

## TraceEvent and RunManifest

See [artifact contract](contracts/artifacts.md) for the canonical fields and file lifecycle.
Traces are observational records; manifests describe a run, not benchmark accuracy.

Run states: `running -> completed` or `running -> failed`; externally killed runs can
remain `running` and are treated as incomplete. Completion scope is `subset` or `full_split`;
neither alone asserts final competition compliance. Output paths are unique per run.
