# Research and resolved decisions

Repository inspection only, 2026-10-29. No inference, benchmark evaluation or hidden
environment-state access was performed for planning.

## T001 confirmation (2026-10-29, post-merge, before any new code)

Re-read `contracts.py`, `cli.py`, `artifacts.py`, and `checkpoint.py` against the
actual merged `python/lifemate` source, not just this document. First ran
`python -m unittest discover -s python/tests -p 'test_*.py'` against that source:
**84 tests, all passing, 3 skipped** (2 need host symlink privilege, 1 is the
opt-in real-dataset smoke). The findings below are confirmed against that passing
baseline.

- `SampleOutcome.timings` (`contracts.py`) is today a flat `dict[str, float]` with
  exactly the keys `request`/`planner`/`tools`, populated in `agent.run_sample`.
  FR-007 requires legacy `elapsed`/`timings` semantics to keep meaning agent-loop
  time; the new per-stage/per-generation data must land in a **new** field
  (`measurements`, additive), never by reshaping `timings` itself.
- `artifacts.py: Trace.emit(kind, *, step=None, payload=None, **metadata)` already
  accepts arbitrary event kinds and metadata kwargs. New span/generation events
  (`asr_clip_started`, `generation_finished`, etc.) need **no change to `Trace`
  itself** — they are just additional `emit()` calls with new `kind` values. Only
  `RunStore` (`manifest["samples"]` entries, and a new top-level
  `metrics_schema_version` key) needs additive extension for T003.
- `RunStore.restore()` already tags an imported sample's manifest record with
  `source_run_id`/`trace_path` when absent from the previous run's own `samples`
  list — i.e. an `executed` vs. `imported` distinction already exists implicitly.
  T003 should make this explicit (`"source": "executed"|"imported"`) rather than
  inferring it from field presence, per `data-model.md`'s Sample attempt entity.
- `checkpoint.read_checkpoint()` has an explicit list of manifest keys that must
  match exactly for strict resume (`execution_identity`, `prompt_sha256`, `limits`,
  `seed`, `device`, `selection_filter`, `model_offload`, ...) or the import is
  flagged `development_composite`. The new `metrics_schema_version`/`measurements`
  fields must **not** be added to that comparison list — they are diagnostic-only
  and must not turn an otherwise-compatible resume into a flagged mixed one.

No contradictions were found between this document's earlier claims and the real
source; the notes above sharpen exactly where T002/T003 attach.

## Local files and optional adapter telemetry

**Decision**: Extend Trace/RunStore; add JSON/Markdown reports and optional adapter
telemetry while preserving ASR/planner string-returning protocols.
**Rationale**: `artifacts.py` already persists bounded metadata, manifests, output,
initialization, provenance and checkpoint imports. `agent.py` already measures broad
request/planner/tools buckets. Count actual token IDs within local adapters and each
filter/corrective generation separately. Monotonic host wall spans include CPU,
transfers and work needed to obtain completed outputs.
**Alternatives**: Remote telemetry, a daemon/database, CUDA-kernel-only timing,
text-based token estimates and per-token synchronization add cost or hide bottlenecks.

## Failure and resume populations

**Decision**: Preserve available failed-outcome metrics; separate current attempts,
imports, not-started IDs and incomplete evidence.
**Rationale**: CLI supports checkpoint reuse, mixed-development resume and selected
continue-on-error paths. Current `sample_failed` does not persist the whole returned
outcome, so success-only aggregation loses failures.
**Alternatives**: Successful-row averages and merged resume timings conceal timeout
cost and hardware/configuration differences. No automatic replay is introduced.

## Prompt profiles and examples

**Decision**: Preserve existing `lifemate-react-v4` as baseline; add opt-in precise-v1
instructions and treat optional few-shot as a separate experimental factor.
**Rationale**: `prompting.py` already has role messages, a top-level input allowlist
and observation turns. LocalPlanner uses deterministic constrained generation and
context reservation. Reuse that grammar and deterministic eligibility boundary.
**Alternatives**: Reflection, semantic retrieval, optimizer/SFT and observation
truncation are outside this slice.

## Partition and checkpoint safety

**Decision**: Require source/group IDs, a frozen partition manifest and fit-only
example artifacts; hash profiles, bundles and partitions into execution identity.
**Rationale**: Roadmap/testing rules exclude validation from prompt banks. Existing
checkpoint compatibility must detect selected prompt content rather than relying
only on the module-level baseline prompt hash. No frozen partition is assumed to exist.
**Alternatives**: File names or a bare train label cannot establish fit eligibility.

## Controlled evaluation

**Decision**: Freeze an instrumented baseline and compare harness-only,
instruction-only and few-shot-only factors separately before combining them.
**Rationale**: Transcript runs isolate planner behavior; audio runs assess full
latency. Simultaneous model/ASR/prompt changes cannot identify the cause of improvement.
**Alternatives**: Do not infer an official aggregate score from the supplied brief.

## External uncertainty

Startup accounting and A30/data access cannot be resolved locally. Record startup
separately and disclose hardware/coverage limits. These block final compliance
claims, not implementation of the defined metrics. Hard process supervision is
deferred; cooperative deadline checks do not guarantee termination of stuck calls.
