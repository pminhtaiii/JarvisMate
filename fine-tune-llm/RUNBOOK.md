# Manual execution

Run from the project root (the folder containing `python/`, `tools/` and this
directory). Every block below is a **separate invocation**, after reviewing the
previous result. Model/data phases shown here require a separate operator request;
writing this runbook does not authorize running them.

## Interpreter and paths

On the current receiving machine the actual project is the nested
`JarvisMate_5/JarvisMate` checkout, not its parent Git directory. From that project:

```powershell
$llmProjectRoot = (Get-Location).Path
$llmPython = Join-Path $llmProjectRoot '.venv-llm/Scripts/python.exe'
$llmConfig = Join-Path $llmProjectRoot '.agent-work/llm-finetune/local-suite.json'
$llmSuite = Join-Path $llmProjectRoot '.agent-work/llm-finetune/suite-01'
```

Create a fresh environment only if it does not exist. Use an actual Python 3.12.10
x64 executable on PATH; do not copy a venv or install into global Python:

```powershell
python -m venv .venv-llm
```

Install exactly the Windows/Python 3.12 lock:

```powershell
& $llmPython -m pip install --require-hashes --no-deps -r ./fine-tune-llm/locks/windows-py312-cu128.lock
```

Install this source using the locked build tools, with no build-isolation download:

```powershell
& $llmPython -m pip install --no-build-isolation --no-deps -e ./python
```

```powershell
& $llmPython -m pip check
```

For another Python/platform, resolve a new complete binary lock in an isolated
venv. This resolves packages, not models/data, and installs nothing:

```powershell
& $llmPython ./fine-tune-llm/scripts/lock_environment.py --requirements ./fine-tune-llm/requirements-qlora.txt --profile windows-py312-cu128 --output ./.agent-work/new-lock/windows-py312-cu128.lock
```

The script records wheel URLs/SHA256, the complete transitive closure and build
tools. Review a changed resolution explicitly; never silently replace the supplied
lock. For offline setup, download its exact wheels with `pip download
--require-hashes --no-deps -r LOCK --dest WHEELHOUSE` on a matching host, then use
`pip install --no-index --find-links WHEELHOUSE --require-hashes -r LOCK` with a
name/version/hash lock generated from those same wheel identities. The supplied
online lock uses direct pinned URLs, so disconnected installation instead uses
local wheel URLs with the same hashes; do not assume `--no-index` disables direct URLs.

Official candidate-build references checked for setup:
[PyTorch 2.9.0 Windows/cu128](https://pytorch.org/get-started/previous-versions/#v290),
[bitsandbytes 0.48.1 Windows/sm120](https://huggingface.co/docs/bitsandbytes/v0.48.1/en/installation),
[PEFT k-bit preparation](https://huggingface.co/docs/peft/v0.17.0/en/developer_guides/quantization).
Documentation support and passing kernels do not establish worst-row training fit.

## Configure and verify visible resources

Copy `configs/suite.json` to an ignored local configuration and set `project_root`
to the real project root. Relative resources resolve from that root. Set data root
to the folder directly containing `train/`; supply the existing grouped split,
complete pinned Qwen snapshot, and an ignored output root. Explicit absolute local
overrides are supported, including paths containing spaces. Source defaults are
project-relative. Do not edit Python to relocate resources.

Qwen identity accepts hash-verified HF download metadata at the exact pinned commit,
or an explicit transfer `snapshot-manifest.json` (schema
`lifemate-pinned-snapshot-v1`, `base_model`, `files` name→SHA256, `license`,
`release_provenance`). An arbitrary qwen3 config is insufficient. Weight hashes and
unquantized safetensors header counts are checked independently of quantization.
No verification code enumerates hidden environment directories.

```powershell
& $llmPython -m lifemate.llm_training verify-resources --config $llmConfig --phase transfer
```

Optional ASR exports/caches are not required by transfer or clean L1/L2 preparation.
ASR resources become required for A/audio/L3 scopes. Existing local resources may be
referenced without copying them; their content hashes remain part of the run.

## Pure checks, CPU proof and native regressions

```powershell
& $llmPython -m unittest discover -s python/tests -p 'test_llm_*.py' -v
```

The default suite skips real-data, actual LMFE and tiny-model scopes. Fake tokenizer
checks are controlled harness tests, not pinned-tokenizer acceptance.

```powershell
& $llmPython -m lifemate.llm_training token-audit --config $llmConfig --scope decoder-poc --output-root ./.agent-work/llm-finetune/decoder-proofs
```

This CPU-only scope opens the existing tokenizer/catalog, never 4B weights. It walks
32 cases across the nine required groups, including EOS after a deadline, and saves
actual IDs/prefix decisions. Pin the exact passed directory as
`native_decoder_proof` in the local configuration. A failed/stale proof blocks
consumers. Rendering/codec/policy/backend/package changes require a new proof.
The native wrapper uses language-preserving LMFE composition shortcuts; there is
no custom-grammar or unconstrained fallback.

```powershell
& $llmPython -m lifemate.llm_training token-audit --config $llmConfig --scope native
```

This independent CPU scope checks history anchors `train_0008`/`train_0069`, native
feedback, recursive schemas/prior arguments/targets, persisted JSONL text/IDs,
masks/EOS and flag equivalence. Set the resulting directory as `native_acceptance`.
It needs no prepared corpus. These fixtures do not establish semantic quality.

```powershell
$env:LIFEMATE_LLM_CPU_BACKEND = '1'
& $llmPython -m unittest discover -s python/tests -p 'test_llm_decoder_backend.py' -v
Remove-Item Env:LIFEMATE_LLM_CPU_BACKEND
```

```powershell
$env:LIFEMATE_LLM_TINY = '1'
& $llmPython -m unittest discover -s python/tests -p 'test_llm_tiny.py' -v
Remove-Item Env:LIFEMATE_LLM_TINY
```

RV003 uses a random tiny Qwen on CPU and hides CUDA before library imports. It tests
analytic gradients, actual adapter updates, partial accumulation, deterministic
remaining-budget resume/NLL ties, corruption rejection and merged offline reload.
It downloads no checkpoint and does not qualify 4B memory.

To preserve command/revision/dirty-source/environment/output evidence for one check:

```powershell
& $llmPython ./fine-tune-llm/scripts/record_check.py --label RV001-pure -- $llmPython -m unittest discover -s python/tests -p 'test_llm_*.py' -v
```

## Explicit GPU kernels and model probes

```powershell
& $llmPython -m lifemate.llm_training gpu-preflight --config $llmConfig --profile windows-py312-cu128
```

```powershell
& $llmPython -m lifemate.llm_training gpu-preflight --config $llmConfig --profile windows-py312-cu128 --nf4
```

These allocate small tensors and run kernels, not 4B models. Physical/free VRAM are
reported in bytes/GB/GiB; RAM/disk, driver, CUDA runtime and nvcc toolkit are separate.

Only after a separate actual-model request, use declared short/long structural
native fixtures (JSONL with `input.messages`, `input.tools`, `target`, `target_type`):

```powershell
& $llmPython -m lifemate.llm_training probe --config $llmConfig --experiment L1 --scope early --smoke-fixtures ./.agent-work/llm-finetune/short-long.jsonl --settings ./fine-tune-llm/configs/training.json
```

Early smoke is independent of full trainer/corpus qualification. No resident ASR is
loaded. A LoRA failure is recorded; selecting `training-nf4.json` is an explicit
operator choice for a common L1–L3 profile, never an automatic fallback.

## Corpus, suite and policy (separately requested)

```powershell
& $llmPython -m lifemate.llm_training prepare --config $llmConfig --suite-dir $llmSuite
```

Review quality/pending/quarantine evidence, including critical transactions and
train_1696. There is no automatic semantic approval. `--draft-without-proof` is an
unsealed diagnostic only and cannot feed evaluation/training.

```powershell
& $llmPython -m lifemate.llm_training seal-selection-policy --suite-dir $llmSuite --policy ./fine-tune-llm/configs/selection-policy.json
```

Seal before any model outcomes. Never edit it retrospectively.

```powershell
& $llmPython -m lifemate.llm_training token-audit --suite-dir $llmSuite --scope clean
```

The resulting sealed accepted-row index and token cache exclude pending/quarantined
and overflowing inputs. Zero support fails. No truncation or reusing old masks.
Multiple accepted audits require an explicitly managed new suite rather than an
implicit latest choice. L0-G needs native acceptance and pinned inputs, not a full
accepted Fit token corpus; teacher-forced diagnostics additionally need that corpus.

```powershell
& $llmPython -m lifemate.llm_training probe --suite-dir $llmSuite --experiment L1 --scope full --settings ./fine-tune-llm/configs/training.json
```

Full scope uses actual accepted worst prompt/completion/total lengths, at least
five updates and accumulation 16, constrained generation and adapter reload. It
requires allocator headroom plus sampled NVML device evidence and available process
metrics. Known Windows WDDM can use the stricter all-device peak as a conservative
process-residency upper bound; exact process peak stays null, with its reason.
This requires the matching GPU UUID, observed own PID, valid samples, unchanged
1GiB headroom, and both allocator/device caps. Unknown drivers or missing device
evidence remain `resource_unverified`; the base37-wheel lock does not install
the optional `pynvml` provider. Obtain and separately lock/verify a provider before
qualification; installing it changes the environment and requires fresh checks.
Never lower rank/context/data to hide OOM. NF4 is a separate explicit common profile.

For the pinned Qwen NF4 loader, k-bit preparation is followed by restoring the
frozen tied embedding/output weight and Qwen3 RMSNorm weights to the configured
BF16/FP16 compute dtype. PEFT otherwise upcasts those weights to FP32, and Qwen's
norm output promotes the residual activations to FP32 as well. RMS normalization
arithmetic and completion cross entropy still run in FP32; LoRA A/B parameters
stay FP32. Genuine double-quantized NF4 matrices and the corpus/context/rank/update
policy are unchanged. The loader records this precision policy in probe metadata;
a fresh full probe is required before training, with the same 1GiB headroom gate.

## Pilot, independent training and checkpoints

The combined entrypoint runs `evaluation-inputs --config ...` before corpus and
Qwen GPU phases. It validates the frozen Validation inputs in audio mode, checks
ToolEnv state-file existence only, and imports/fingerprints the trusted runtime
without constructing environments. Missing assets block immediately. Closed-loop
and full-audio entrypoints repeat the guard before loading models; standalone
G closed-loop preflight uses transcript mode and does not require audio assets.
Benchmark model failures remain scored failures; infrastructure absence is not a
completed benchmark. The local configuration now uses the `_5` dataset after the
explicitly authorized one-time opaque Train-state transfer; see TUNING_LOCAL.md
and `state-transfer-20261102` receipts for verification and authorization scope.

With selected fine-tuned ASR and real audio available:

```powershell
& $llmPython -m lifemate.llm_training latency-pilot --suite-dir $llmSuite --experiment L0 --profile local-rtx5070ti
```

All ten fixed Validation cases are retained. Component/total timing, invocation and
token counts, environment setup/calls and joint memory are recorded. Uncalibrated
prefill/decode separation stays null. This is local screening, not A30 acceptance.

Before full SFT, provide `latency_decision` with schema
`lifemate-audio-latency-decision-v1`, matching `suite_seal`, nonempty `operator` and
`reason`, and `decision` of `pilot_reviewed` or
`proceed_with_unresolved_audio_latency`. No decision is supplied automatically.
Set `resource_qualification` to the exact passed full probe `outcome.json`.

```powershell
& $llmPython -m lifemate.llm_training preflight --suite-dir $llmSuite --experiment L1 --settings ./fine-tune-llm/configs/training.json
```

```powershell
& $llmPython ./fine-tune-llm/scripts/run_l1.py train --suite-dir $llmSuite
```

```powershell
& $llmPython ./fine-tune-llm/scripts/run_l2.py train --suite-dir $llmSuite
```

These are independent invocations/initializations, not an instruction to launch
both. Each uses 500 updates, uniform base visits and actual partial-window m.
Completion CE includes exactly one EOS. The first of 25 linear warmup updates uses
lr/25; the schedule reaches zero after update 500. Save/clean-G unweighted NLL
cadence is 100/final; earliest-step ties win. Final/periodic checkpoints remain.

```powershell
& $llmPython -m lifemate.llm_training train --suite-dir $llmSuite --experiment L1 --resume-from ./.agent-work/llm-finetune/suite-01/L1/RUN/checkpoints/step-000100
```

Resume writes a new run and continues only the remaining budget with all optimizer,
scheduler/scaler/RNG/sampler/view state. It rejects other experiments, exhausted or
corrupt checkpoints, and changed source/config/environment/data/probe identities.

## Export and evaluation

```powershell
& $llmPython -m lifemate.llm_training export --suite-dir $llmSuite --experiment L1 --run-dir ./.agent-work/llm-finetune/suite-01/L1/RUN --checkpoint best
```

```powershell
& $llmPython -m lifemate.llm_training verify-export --suite-dir $llmSuite --experiment L1 --export ./.agent-work/llm-finetune/suite-01/exports/EXPORT
```

Export merges onto a fresh unquantized base and writes one FP16 model/tokenizer/
template directory. Verification uses two fresh outbound-blocked processes. Actual
4B export/verification have not run in this handoff. NF4 training scores cannot
substitute for merged-export scores.

```powershell
& $llmPython ./fine-tune-llm/scripts/run_l0.py evaluate --suite-dir $llmSuite --mode G
```

```powershell
& $llmPython -m lifemate.llm_training evaluate --suite-dir $llmSuite --experiment L1 --mode G --export ./.agent-work/llm-finetune/suite-01/exports/EXPORT
```

Request A independently with `--mode A` and the fixed validated Validation ASR
cache. Use `--protocol teacher_forced` for a separate oracle-prefix diagnostic;
generation and NLL both use the projected ASR current/history. Missing turns never
fall back to gold. `--continue-on-error` explicitly collects scored failures across
all 309 sources; fail-fast remains the default. Unsupported inputs are failed
outcomes, not dropped IDs. Source failures never become successful empty predictions.

## L3 and artifact-only comparison

```powershell
& $llmPython -m lifemate.llm_training compare --suite-dir $llmSuite --runs ./.agent-work/llm-finetune/run-selection.json
```

`run-selection.json` is `{"runs":[{"experiment":"L0","mode":"G","evaluation":"EXACT_DIRECTORY_NAME"}, ...]}`.
Select each experiment/mode explicitly, once. Comparison verifies hashes, schemas,
actual outcome coverage/status/timing supports, source/cache identities and export
status; writes eight rows, deltas, fixed cases, group bootstrap and policy decisions.
It never loads models or reconstructs predictions. Partial runs cannot choose policy;
one fully accounted timeout is not an automatic veto. Save its RV018 report for L3.

```powershell
& $llmPython -m lifemate.llm_training build-asr-views --suite-dir $llmSuite --fit-cache ./.agent-work/llm-finetune/fit-cache.jsonl
```

```powershell
& $llmPython -m lifemate.llm_training token-audit --suite-dir $llmSuite --scope asr --view-dir ./.agent-work/llm-finetune/suite-01/asr-views/VIEW_SET
```

Only surface-equivalent views auto-accept. Non-surface changes require hash-bound
full-original-prefix Fit review. Targets/context/results stay unchanged; no prefix
splicing. Pending/changed semantics are excluded. Noise coverage and actual visits
remain visible, including `limited_noisy_coverage`. If noisy lengths exceed the
qualification, separately run full `probe --include-asr` before L3.

```powershell
& $llmPython ./fine-tune-llm/scripts/run_l3.py train --suite-dir $llmSuite --policy-report ./.agent-work/llm-finetune/suite-01/comparisons/COMPARISON/comparison.json
```

L3 recomputes the saved RV018 decision from the selected compatible artifacts, uses
the same clean corpus/budget/weights, and chooses one approved view per base visit
with independent RNG. Missing/rejected/overlong training views use explicit clean
fallback. That fallback is forbidden in A evaluation.

## Full audio and deployment

```powershell
& $llmPython -m lifemate.llm_training evaluate --suite-dir $llmSuite --experiment L1 --mode A --full-audio --export ./.agent-work/llm-finetune/suite-01/exports/EXPORT --continue-on-error
```

```powershell
& $llmPython -m lifemate.llm_training deployment-check --suite-dir $llmSuite --evidence ./.agent-work/llm-finetune/a30-evidence.json
```

`deployment-check` validates supplied actual A30/container/hard-supervisor evidence;
it does not create a supervisor or Docker image. Evidence schema
`lifemate-a30-acceptance-v1` requires host, offline network/container digest,
hash-bound container/supervisor/repeatability/submission/outcomes assets, logical
counts/context, hard 30-second process-tree cleanup, complete authoritative outcomes
and independent reproducibility. Missing infrastructure keeps RV025 unverified.
Cooperative local deadlines, cached A and a selected winner never grant submission readiness.
