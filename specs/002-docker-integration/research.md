# Research and Decisions

Research is complete for the design boundary; runtime acceptance remains pending.
Repository exploration was read-only, including a user-requested Luna/Max sub-agent.

## 1. Extend the existing runner, preserve its comparison path

**Decision**: Add a separate integration command within `lifemate`, reuse the executor
and model/session boundaries, and retain legacy `run` defaults.

**Rationale**: `python/src/lifemate/agent.py` already owns request preparation, one
ToolEnv, iterative observations and authoritative collection. `adapters/asr.py` loads
local Whisper-family snapshots. `adapters/planner.py` currently loads Qwen3 but uses
custom constrained JSON, not native messages. No Docker implementation was found.

**Alternatives considered**: A second pipeline tree duplicates execution policy;
changing the existing default removes a useful baseline; HTTP/multi-container services
add deployment/latency work outside the agreed one-container topology.

## 2. Transcribe distinct clips once per sample

**Decision**: Resolve/deduplicate permitted audio content during request preparation;
retain a sample-local transcript map, then reuse prepared text through the tool loop.

**Rationale**: `dataset.py:prepare_request` currently transcribes historical user WAVs
and the current WAV; `agent.py` invokes it once before planning. Five ASR calls can
therefore be five distinct clips, not five iterations. Repeated clip references still
need deduplication. History is required context, so dropping it silently is incorrect.

**Alternatives considered**: Re-ASR each decision wastes budget; transcribing only the
current clip loses historical evidence; cross-run caching complicates honest timing
and model identity and is deferred. Count every required clip inside the deadline.

## 3. Native Qwen messages with a one-call execution policy

**Decision**: Use the selected checkpoint's tools-aware chat template; accept exactly
one native call or a declared EOS-terminated neutral no-tool completion. Map into
canonical executor actions. Reject ambiguous/truncated output before dispatch.

**Rationale**: Official Qwen supports Hermes-style tool blocks and tool-result messages,
including multiple calls/extra text. One-call-only is our execution policy, not a
limitation claimed for Qwen. It preserves result-dependent planning. The existing
native-protocol proposal informed the explicit neutral-finish policy recorded in this
feature's runtime contract; no training stages are required. The example 2507 checkpoint is non-thinking;
other checkpoints must validate thinking/template/EOS configuration independently.

**Sources**:

- [Qwen function calling](https://qwen.readthedocs.io/en/latest/framework/function_call.html)
- [Qwen tool-use concepts](https://qwen.readthedocs.io/en/latest/getting_started/concepts.html)
- [Qwen3-4B-Instruct-2507 tokenizer snapshot](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/blob/f50518eb58dfc750271b273fc113bdfc16ec2280/tokenizer_config.json)
- [Qwen model card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)

**Alternatives considered**: Whole-chain generation cannot consume future live lookup
results; salvaging the first of several calls changes meaning; accepting arbitrary
assistant prose as finish hides malformed output. An extra routing LLM adds latency.

## 4. Independent watchdog, persistent spawned worker

**Decision**: Supervisor starts the attempt timer before dispatch; worker retains
loaded models and owns sample execution/durable staging. Supervisor accepts only
timely acknowledgements, terminates a stalled process group and never retries that
sample. Recover only for later distinct samples with bounded startup/recovery.

**Rationale**: `contracts.py:Deadline` is cooperative. Existing CLI model init and
output persistence lie outside `run_sample` timing. A blocked native/tool call cannot
be preempted merely by checking time afterward. Separate supervision addresses
worker liveness, while strict timestamp checks prevent late success. Termination is
subject to OS/GPU scheduling; record overshoot and stop if worker death is uncertain.

**Sources**:

- [Python subprocess timeouts and process sessions](https://docs.python.org/3/library/subprocess.html)
- [Python process-group termination](https://docs.python.org/3/library/os.html#os.killpg)

**Alternatives considered**: Threads cannot reliably terminate blocked native calls;
loading models per sample wastes latency; retrying/recreating a failed environment
risks duplicate effects. Parent-side unbounded output writes would undermine the
watchdog, so durable sample staging is worker-owned before result acknowledgement.

## 5. Configurable local snapshots and GPU deployment

**Decision**: Strict stdlib TOML plus known CLI overrides. Mount complete snapshots;
select host GPU at Docker launch, then use the visible container device. Device,
precision and explicit offload are settings, not model-specific source edits.

**Rationale**: Existing local-only adapters and parameter/context checks are reusable.
Whisper/PhoWhisper and Qwen3 are the initial compatible families. Unknown formats
fail preflight; adapter merging/training belongs elsewhere. GPU driver compatibility,
CUDA digest and memory fit are actual-build/run gates, not assumed by this plan.

**Sources**:

- [NVIDIA GPU selection in Docker](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/docker-specialized.html)
- [Docker GPU access](https://docs.docker.com/engine/containers/gpu/)

**Alternatives considered**: Baking checkpoints into the image complicates swapping;
fixed GPU names contradict infrastructure flexibility; sharding/remote serving adds
unmeasured complexity. Existing inference pins are the starting point, not a claim
that any chosen CUDA base is already compatible.

## 6. Diagnostics first, training separately

**Decision**: Add empty-gold/clarification diagnostics and paired transcript/audio
evaluation; no rebalancing, synthesis or training in this feature.

**Rationale**: [Benchmark rules](../../context/benchmark.md) distinguish unsupported
requests (`[]`) from missing information (`sys.ask_missing_info`), including after
earlier calls. Measure actual frequency/errors before changing training distributions.
The [SFT design](../../docs/design/train-to-sft.md) preserves finish and clarification
targets and grouped train/validation separation. No dataset counts were measured here.

**Alternatives considered**: Treating all uncertainty as no-call gives wrong empty
outputs; indiscriminate clarification adds false calls; immediate balancing can alter
decision rates without demonstrating a real error source.

## 7. Timing/accounting and failed-row external gates

**Decision**: Count input dispatch through durable per-sample artifacts and timely
supervisor receipt. Separately expose startup/recovery/packaging and total wall time.
Failed samples remain in a ledger; incomplete runs cannot publish a complete submission.

**Rationale**: The supplied brief specifies 30 seconds/sample and A30 scoring hardware,
but does not settle all initialization or failed-row formatting details. Avoid
fabricated empty rows/hashes and document the uncertainty instead of inventing rules.
Hardware remains configurable; development measurements do not establish A30 results.

**Alternatives considered**: Hiding cold start/packaging misrepresents runtime; declaring
every deployment A30-only prevents local use; reconstructing state after a killed
worker violates single-environment/no-retry policy.

## 8. Crash-safe reservation before dispatch

**Decision**: Fsync an immutable sample/attempt/worker/config reservation under
exclusive run ownership before dispatch. After supervisor death, reserved IDs without
durable acceptance are uncertain and never replayed. Confirm old-worker termination
before continuing other IDs; invalid journals block resume. Require acceptance
durability before the next dispatch and fail closed on bookkeeping write failure.

**Rationale**: The initial design recorded terminal acceptance but omitted durable
evidence before tool effects. A crash after mutation could otherwise make resume
mistake that sample for unattempted. Three independent P0/P1 reviews identified this
same P1 gap. Reservations are separately timed scheduling bookkeeping, include no
sample processing, and count in total wall time; attempt timing starts before dispatch.

**Alternatives considered**: Inferring attempts from staging loses pre-staging effects;
creating a fresh environment to inspect state violates no-replay; accepting staged
output after a lost acknowledgement can admit an over-deadline result.

## 9. Runtime dependency layout and CUDA build inputs (T002)

**Decision**: The image installs only `jarvismate-lifemate[inference]` (PyTorch 2.9.0,
Transformers 4.57.1, NumPy 2.3.4, LM Format Enforcer 0.11.3) plus the organizer
runtimes copied from `tools/train` and `tools/test` with their split catalogs. No
training, PEFT, dataset or notebook dependency is added; the integration code itself
uses only the standard library (`tomllib`, `subprocess`, `threading`, `hashlib`).

**Evidence**: Every import in `tools/train` and `tools/test` is standard library or
`zaic_tools` itself, so organizer runtimes need no extra packages. `runtime.py` expects
`<tools>/<split>_tools_catalog.json` beside `<tools>/train|test`, so the image keeps
that layout under `/opt/lifemate/tools`.

**CUDA inputs**: Use a slim CPython 3.11 base and PyTorch's CUDA wheel index rather
than a CUDA base image; the wheels bundle the CUDA user-space libraries and the NVIDIA
Container Toolkit injects the host driver. Default index `cu128` targets both Ampere
(A30, `sm_80`) and newer consumer GPUs; it needs a host driver supporting CUDA 12.8.
Both are build arguments. The `python:3.11-slim-bookworm` index digest
`sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39` was read from
Docker Hub on 2026-11-06; no image has been built with it here. The resolved dependency
set and built image digest are recorded by T024 on the GPU server.

## Branch cleanup and preservation

Base `fine-tuned-asr` remains available. On this integration branch remove tracked
`asr/fine-tuned/`, `python/src/lifemate/asr_training/` and training-only test/support
files. The root `asr/` experiment folder was subsequently removed at the user's
request. Preserve the runtime ASR adapter and generic planner-SFT designs.
The pre-existing untracked 004 augmentation draft was preserved under ignored
`.agent-work/preserved-asr-planning/004-asr-acoustic-augmentation/`. The unrelated
untracked measurement, native/SFT and latency drafts were subsequently removed at
the user's request; this planning package is self-contained.
