# Native Qwen cross-step KV reuse

Branch `codex/009-cross-step-kv-cache` starts at branch 008 commit
`9ca6ce17fde99eb7a3811f9dab01fa5ccedfec6a`. Baseline checkout/artifacts remain intact.
The optimization is opt in, and has no measured H200 speed or quality result yet.

```toml
[execution]
reuse_kv_cache = false  # OFF: existing full-prefill path (default, including omitted field)
# reuse_kv_cache = true # ON: verified token-prefix reuse within a sample
timeout_seconds = 30
soft_timeout_seconds = 28
max_steps = 16
```

Other required config fields stay as in `configs/integration.example.toml`. The new
boolean is strict, reported by effective config, and included in its fingerprint.
Worker component construction forwards it to NativePlanner. Never mix or resume
branch-008 artifacts with this new code/config identity.

## Exact reuse strategy

Each decision still renders the complete canonical prompt with the existing Qwen
chat template, system text, eligible tools and every executed tool result, then
tokenizes it. Reuse is based on equal token IDs, not text or semantic equality.

The per-sample manager records only IDs actually supplied to model forwards and the
returned KV object. This avoids claiming that the last generated token/EOS was
processed. On the next step, compare those IDs with the canonical prompt's IDs,
crop to their longest common prefix, and leave at least one prompt token uncached
to obtain next-token logits. Canonicalized assistant JSON, EOS delimiters, changed
token boundaries, shorter prompts and repeated prompts can all shorten reuse.

Full `input_ids` and the complete attention mask still go to `generate()`. Set
`past_key_values`, `use_cache=True` and absolute `cache_position=[reused..prompt_len)`
on the supported path. Transformers slices only the model's uncached suffix and
derives positions from the full mask. Thus LMFE and all generation processors see
the full original prompt and generated history, not a shortened conversation.
Greedy settings, generation/context limits, EOS inspection, strict JSON parsing
and eligibility checks remain unchanged. No tool calls execute during reconstruction.

This integration was checked against these pinned primary sources:

- [Transformers 4.57.1 generation preparation and sampling](https://github.com/huggingface/transformers/blob/v4.57.1/src/transformers/generation/utils.py)
- [DynamicCache / DynamicLayer and crop](https://github.com/huggingface/transformers/blob/v4.57.1/src/transformers/cache_utils.py)
- [Qwen3 positions, masks and cache updates](https://github.com/huggingface/transformers/blob/v4.57.1/src/transformers/models/qwen3/modeling_qwen3.py)

Reuse currently supports PyTorch 2.9.0 and Transformers 4.57.1, batch size one,
eval-mode Qwen3 with default RoPE, full-attention DynamicLayers, and ordinary
generation caching. Unsupported versions, sliding/static/quantized cache paths,
dynamic RoPE, disabled model caching, or unverifiable cache shape/length/device/dtype
fall back before generation to normal full prefill. Prefix divergence crops or
invalidates the saved cache. CUDA/model failures propagate as existing failures;
they do not trigger a speculative generation retry or accepted fallback prediction.

The agent starts/reset a sample before ASR and always ends/releases it in `finally`.
Finish, clarification, soft/hard expiry, step limit and errors all release state.
Offload releases cache before moving weights to CPU. A worker recovery builds a new
planner; process death releases memory. Cache storage and token history are bounded
by the existing context reservation; prompt plus output must fit before generation.
OOM still fails explicitly through the existing planner error path. No original
ToolEnv, weights, tool grammar, deadline or supervisor/journal acceptance is changed.

## Measurements

`outcome.metrics.planner` and the accepted journal's worker metrics contain:

- `kv_cache_enabled`, `kv_cache_hits`, `kv_cache_misses`, `kv_cache_invalidations`;
- `kv_cache_reused_tokens`, `kv_cache_new_prefill_tokens`;
- `kv_cache_invalidation_reasons` (including unsupported-path bypass events);
- `planner_prefill_seconds`, `planner_decode_seconds`, `planner_total_seconds`;
- `kv_cache_peak_memory_bytes` when cache tensors are observable.

Prefill is the first model forward of a decision; decode is subsequent forwards.
CPU forward durations use `perf_counter`; GPU forward durations use CUDA events on
the planner device's stream, read after the existing generation synchronization.
Total planner time includes rendering, tokenization, grammar/CPU work, sampling,
validation and instrumentation overhead. These phases are not estimates or an
exhaustive partition of total time. Incomplete forward timing is null, not invented.
Hit/miss and reused/new token counts are recorded after a successful first forward,
so a deadline reached before generation does not count planned reuse as actual work.
Planner total sums decisions; sample time also includes sample entry/cleanup.
Startup/weight loading remains outside sample spans.

The cache byte value is the observed peak retained tensor backing-storage size,
deduplicated by storage, including views after crop. It is not transient allocator
peak or a memory estimate. Worker GPU allocator peak is separately recorded;
the planner device's peak counter resets at sample entry, before ASR. Killed workers
may supply no measured planner timings; staged evidence is never promoted to acceptance.

Per-step metrics include measured prefill/decode, reused/new tokens, generated
token IDs and canonical actions. None are added to submission rows, which retain
exactly `id`, `tool_calls`, `state_hash` from the existing authoritative path.

## UIT paired benchmark (operator runs later)

Use a separate branch-009 checkout and the existing inference Python environment.
Do not switch a checkout used by an active job. The benchmark reads the supplied
base audio TOML and selection only. It requires exactly these 16 IDs, in order:

```text
public_0099 public_0110 public_0187 public_0213 public_0240 public_0287
public_0340 public_0342 public_0356 public_0363 public_0606 public_0391
public_0329 public_0336 public_0699 public_0403
```

The existing UIT file is `configs/lifemate-public-008-smoke16-ids.txt`; reference it
read only from the original checkout. Replace deployment paths and the scheduler's
actual partition/GRES values below (no site-specific resource name is assumed):

```bash
cd /absolute/separate/JarvisMate009
PY=/absolute/existing-inference-env/bin/python
BASE_CONFIG=/absolute/existing-config/integration.toml
IDS=/absolute/JarvisMate008/configs/lifemate-public-008-smoke16-ids.txt
RUN_ROOT=/absolute/new-runs/kv009-smoke16-$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$(dirname "$RUN_ROOT")"
# UIT_PARTITION and UIT_GPU_GRES must name the operator's H200 MIG allocation.
sbatch --job-name=kv009-smoke16 --partition="$UIT_PARTITION" --gres="$UIT_GPU_GRES" \
  --cpus-per-task=16 --mem=64G --time=00:45:00 \
  --output="${RUN_ROOT}.slurm-%j.log" \
  scripts/integration/kv-cache-benchmark.sbatch "$BASE_CONFIG" "$IDS" "$RUN_ROOT" "$PY"
```

This queues one job, running OFF then ON sequentially on the same allocated GPU,
with separate spawned model startups and fresh per-trial ToolEnvs. No cache is
reconstructed by replaying calls. The benchmark writes new `off.toml`, `on.toml`,
selection, `off/`, `on/` and `comparison.json` under a root that must not exist.
Existing inputs and original output roots are protected; no resume or overwrite.
Each trial preserves base models, ASR, precision, prompt/tools, seed and budgets.
This is never a full 634-sample run. Do not launch alongside an existing job on the
same MIG slice; obtain a separate/scheduled allocation.

For an already allocated interactive GPU, the equivalent command is:

```bash
export PYTHONPATH="$PWD/python/src" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
"$PY" -m lifemate.kv_benchmark --config "$BASE_CONFIG" --ids "$IDS" --run-root "$RUN_ROOT"
# Recompute only the comparison from durable journals, with no models/tools:
"$PY" -m lifemate.kv_benchmark --run-root "$RUN_ROOT" --report-only
```

`comparison.json` contains per-step timings/tokens/actions, total planner and sample
latency, reused-token ratio, observed cache and GPU memory peaks, startup evidence,
completed/needs_info/partial/timeout/failed counts and exact output comparisons.
Inputs/model/runtime/code identity and GPU visibility must match. Missing tokens or
unaccepted rows cannot establish equivalence. Any unequal normal terminal token
sequence is listed in `normal_token_mismatches`; investigate before promotion.
Incomplete/different outputs return nonzero and retain both trials' evidence.
Deadline partials can differ with speed; they are visible rather than treated as
normal deterministic equivalence. Full accepted coverage is not prediction quality.

## CPU evidence and remaining gates

CPU tests use random untrained Qwen3 weights with the pinned libraries, not the SFT
checkpoint. Independent fresh-prefill generation and full-forward KV tensors are
the oracle for cache correctness. Native tests use the official Qwen tokenizer
(revision `cdbee75f17c01a7cc42f958dc650907174af0554`) and actual LMFE. Scripted eligible
completions additionally exercise terminal agent/ToolEnv paths; they are not the
sole oracle. No training or model weights were downloaded.

H200/MIG kernels, FP16/SDPA
numerical equivalence, GPU event timing, GPU offload/allocator behavior, real-model
latency/quality and actual Slurm execution remain untested. Incremental prefill can
change floating-point operation shapes; strict CPU equality is not a GPU guarantee.
Keep the switch OFF until the paired real-checkpoint run establishes equivalence
and measures performance. No speedup or rescued-sample count is claimed here.

Recorded on 2026-11-10, Windows, isolated CPython 3.11.9 / PyTorch 2.9.0+cpu /
Transformers 4.57.1 / NumPy 2.3.4 / LM Format Enforcer 0.11.3:

```powershell
$env:PYTHONPATH='python/src;python/tests'
$env:LIFEMATE_NATIVE_TOKENIZER='C:\Users\Windows\Downloads\Fix_limit\qwen3-tokenizer'
& ..\.python311\python.exe -m unittest test_qwen_kv test_qwen_native test_kv_benchmark -v
# 30 tests, 88.232s: OK, no skips.
& ..\.python311\python.exe -m unittest discover -s python/tests -p 'test_integration*.py' -v
# 104 tests, 83.604s: OK, no skips (process-recovery tests outside sandbox).
& ..\.python311\python.exe -m unittest test_agent test_cli test_artifacts test_inference test_asr_once test_dataset test_runtime test_audio -v
# 80 tests, 2.453s: OK, skipped=2 (Windows symlink permissions); 78 passed.
```

Additional focused checks covered strict config/fingerprints, worker component
forwarding of the flag, prefix corruption and refusing an over-budget retained
cache. CPU comparison used identical weights, complete canonical prompts, responses
and decoding settings, checking generated token IDs, actions, actual ToolEnv logs
and hashes. Normal finish, needs_info, 16-step partial, soft stop and hard expiry
all released sample caches. Existing EOS/JSON/eligibility/grammar checks passed.
`git diff --check` and context checks also passed. These tests establish the exercised
CPU behavior; none are measurements of the user's SFT checkpoint on H200.
