# Implementation handoff — 2026-11-01

**Later transfer update:** ASR E0–E4 artifacts and local Train/base-model resources
are now present; see [ASR transfer](../asr/fine-tuned/TRANSFER.md) and
[current local commands](TUNING_LOCAL.md). Resource locations/absence statements
below describe the earlier implementation snapshot. Full LLM model/data phases
remain unrun; the imported export is not automatically a certified ASR handoff.

**Later explicit orchestration request:** the user requested one command for all
L0–L3, stopping at missing gates/ASR. `CHAY_TUNING_LLM.ps1` / `once.py` implement
that opt-in flow in separate recorded subprocesses. Earlier no-chain statements
below describe the manual CLI and original handoff. No actual model/data workflow
was executed to validate this addition; current missing ASR inputs block it early.

**Subsequent ASR work/integration:** the user explicitly approved provisional E4
selection and genuine Fit/Validation ASR cache inference. That job produced175
successful Fit rows before the user requested stopping it. PID3400 was verified
exited and its stale lock removed; partial bytes remain intact. The combined
entrypoint now prepares/resumes ASR under the recorded approval/source/job hashes,
then proceeds to L0–L3 only on success. It has not been restarted for testing;
see TUNING_LOCAL.md and combined-ASR-L0-L3-delivery.json for the current state.

**Later user execution / OOM fix:** ASR preparation subsequently completed with
4083 Fit and953 Validation turns. The user reached a real LoRA early-probe OOM
at9648 total tokens before update1. The pretrained-base eval-mode/checkpointing
bug was reproduced and fixed with a save/reload tiny regression. A targeted real
LoRA diagnostic was stopped after insufficient device headroom/shared-memory use;
it is not an acceptance pass. WDDM missing per-process NVML values remain null,
with an explicit conservative all-device bound for the unchanged cap/headroom
rules. NF4 remains an explicit common L1–L3 choice needing its own qualification.
See qwen-oom-20261102/diagnosis.json and TUNING_LOCAL.md; no full training was run
by the agent during this fix.

**2026-11-02 NF4 full-probe follow-up:** the user's next run completed five NF4
updates/generation/reload but failed the unchanged resource gate (only36.74MiB
sampled free). PEFT's FP32 frozen embedding/norm weights promoted residual
activations. The loader now restores these weights to the configured compute
dtype, preserving FP32 normalization arithmetic/CE and FP32 adapter A/B. A bounded
real two-row diagnostic reproduced the failure before the fix. The fresh real
full qualification `full-20261102T011304Z-0b5291a4` passed five accumulation16
updates, generation/reload, and sampled minimum free3.43GiB. Default133 LL tests
(124 pass/9 opt-in skip) and5 opt-in tiny CPU tests passed. See
`.agent-work/llm-implementation/qwen-oom-20261102/nf4-followup.json` and
TUNING_LOCAL.md. This qualifies the current worst clean Fit resource probe;
L0, full L1/L2/L3 training, pilot and L3 noisy qualification remain unrun by the
agent. Historical absence/unqualified statements below describe earlier snapshots.

Actual project: `D:\JarvisMate_5\JarvisMate`; branch `fine-tune-llm`; base HEAD
`88bf35e3ab0223caf57da37e7c66287306ba9163`. Source changes are uncommitted.
No push, merge, reset, rebase or PR action. The parent is a different Git worktree
and was not repaired. Work was sequential without agents.

**Later L0 input-asset repair (2026-11-02):** user run
`L0-L3-20261102T025412Z-ab25a190` completed G/A teacher-forced diagnostics but
all309 closed-loop inputs failed with ASSET_MISSING; pilot failed its first input
and marked9 not_attempted. `_5` contained visible labels/catalog/audio but no
ToolEnv state files. The local config now references the original complete `_4`
dataset in place after verifying visible hashes, all309 input projections and both
4083/953-turn ASR caches. One genuine organizer ToolEnv was opened (0 calls, no
reference state hash); the agent did not read/copy hidden state files. New
`evaluation-inputs` guards the combined flow before preparation/Qwen probes, and
closed-loop/audio guard again before model loads. Missing infrastructure no longer
produces a misleading completed score run; behavioral failures retain their
benchmark denominators.143 LL tests:134 passed,9 opt-in skips. See
`.agent-work/llm-implementation/input-preflight-20261102/diagnosis.json` and
TUNING_LOCAL.md. Historical run artifacts were preserved, and no new tuning run
was started by the agent.

**Later explicit state-copy authorization:** the user allowed this one transfer.
All1545 Train state files were copied byte-for-byte from `_4` to `_5` and verified
by SHA-256/size/mtime plus before/after source inventories. No state contents were
parsed or displayed. The local data root is back under `_5`;309 input preflight,
both ASR caches and one genuine local ToolEnv open passed without model loading
or tool execution. `_4` is no longer the current runtime data dependency.
See TUNING_LOCAL.md and `.agent-work/llm-implementation/state-transfer-20261102/`.
This does not authorize future agent access to hidden state contents.

This is an authored implementation with self-review and scoped execution evidence.
It is **not training-qualified, training-complete, evaluated, promoted or
submission-ready**. No real 4B model was loaded. No corpus-wide preparation,
ASR job/cache generation, L0 evaluation, full-audio pilot, L1/L2/L3 training,
real export/evaluation, reference replay or deployment acceptance was executed.

Read [RUNBOOK.md](RUNBOOK.md) for independent commands and
[ASR_HANDOFF.md](ASR_HANDOFF.md) for the external ASR interface. Specs remain
authoritative. Historical reports were preserved. LL/RV checkboxes were not
bulk-ticked. Final file hashes/change inventory and check IDs are in ignored
`.agent-work/llm-implementation/final-source-inventory.json` and
`final-evidence.json` respectively. Each check records its own source snapshot;
documentation edits after an earlier check are not represented as retested code.

## Foundation findings

| Finding | Repair and evidence |
|---|---|
| F1 | Ordered JSON/JSONL preserves recursive schemas and arguments; canonical hashes are separate. Controlled round trips and actual-tokenizer native fixtures compare rendering, IDs and masks, including recursive prior/target calls. |
| F2 | Pre-load readiness binds proof and full native history/render/feedback/mask records to code/tokenizer/backend/packages. L0-G does not require prepared Fit tokens; teacher-forced diagnostics do. Stale evidence fails closed. |
| F3 | Actual dataset/catalog/split and relevant ASR hashes rechecked before model loading/evaluation/scoring and comparison. Relocation uses explicit overrides. |
| F4 | Sealed accepted-row/index/token-cache identities, real nonzero partition support, EOS/mask/budget and quality checks replace a passed flag. All-overflow input fails; pending/quarantine excluded. |
| F5 | Reconcile actual outcomes/predictions/counts/scores/timing supports. Reject all-not-attempted and inconsistent artifacts; keep fully accounted failures/timeouts comparable. Recompute saved RV018 before L3. |
| F6 | Exact snapshot acquisition/transfer provenance plus weight-file hashes and logical safetensors headers; config name alone cannot establish pretrained identity. |
| F7 | A generation and NLL use validated current/history ASR projection; missing turns fail explicitly, no gold fallback. |
| F8 | Strict proof schemas, expected cases/groups/results and hashed token-prefix evidence bind decoder/tokenizer/backend packages. Expired-deadline EOS rejected. |

Language-preserving LMFE composition shortcuts avoid expensive free-text token
walks while retaining the native suffix/grammar. The real-backend character-language
equivalence test passed. There is no unconstrained/custom-grammar fallback.

## LL025–LL048 review ledger

Every row is **authored and self-reviewed** against its task/spec boundary.
Independent reviewer approval is pending. Execution limits below are not missing
command stubs; they are unrun acceptance scopes.

| Task | Deliverable | Executed evidence / pending acceptance |
|---|---|---|
| LL025 | resources.py: host/lock/GPU preflight | Actual BF16/NF4 kernels pass; model memory fit pending. |
| LL026 | models.py/model_identity.py: pinned base, all-layer q/k/v/o LoRA A/B only, genuine NF4/k-bit prep | Tiny injection/update pass and real weights verified; actual 4B load pending. |
| LL027 | qualification.py: independent early and worst-corpus full probes | Guards reviewed; both actual-model scopes not run. Sampled process/device evidence required. |
| LL028 | losses.py: completion mean, one EOS, global mu, actual-window divisor | Pure objective and tiny analytic gradients pass. |
| LL029 | trainer.py: independent base, uniform visits, fixed 500/16, NLL cadence/schedule | Tiny updates/partial windows pass; full training not run. |
| LL030 | checkpoints.py: durable full state/seals/RNG/cursors/best/latest/remaining budget | Tiny deterministic resume, earliest NLL tie and corruption/cross-experiment rejection pass; real interruption pending. |
| LL031 | export.py: selected checkpoint, fresh unquantized base safe merge, FP16 assets | Tiny merge/reload/logical counts pass; real export pending. |
| LL032 | pilot.py: fixed-ten full-audio integration/timing/joint memory | Source reviewed; selected ASR and requested actual pilot pending. |
| LL033 | l0/l1/l2 configs, training settings, thin scripts/PowerShell launcher | Controlled one-phase/manual config tests pass; real invocations pending. |
| LL034 | Training/native/evaluation/checkpoint fixtures and opt-in tiny tests | Controlled and tiny scopes pass; actual-model acceptance pending. |
| LL035 | asr_views.py: selected Fit-only PhoWhisper-large handoff/cache identity | Controlled certificates pass; real selected handoff/caches absent. |
| LL036 | Full-original-prefix noisy acceptance + hash-bound manual review | Controlled surface/changed-semantics/pending cases pass; actual Fit review pending. |
| LL037 | Independent view RNG, one view per base visit, durable state and explicit training fallback | Controlled mixing/resume pass; realized real visits unmeasured. |
| LL038 | Coverage by row/source/type/tool, denominators/reasons/limited-noise flag | Controlled math pass; actual meaningful-noise coverage unknown. |
| LL039 | Independent L3 config/trainer/wrapper + revalidated RV018 | Controlled policy/dependency/tamper tests pass; actual RV018/L3 absent. |
| LL040 | Strict cache-backed ASR/current-history adapter | Controlled A projection/no-fallback pass; actual A not run. |
| LL041 | Logical budgets/assets + two fresh outbound-blocked export reload workers | Missing assets/fake markers rejected; actual 4B workers/repeatability pending. |
| LL042 | Eight-row artifact-only reporting/bootstrap/fixed cases/L0 promotion/ties | Controlled selection/coverage/failure/bootstrap pass; no real winner. |
| LL043 | Explicit full audio through shared agent/runtime, component/total timing/memory | Source reviewed; deployed pair and real audio run pending. |
| LL044 | deployment.py: external hash-bound A30/container/supervisor hooks | Controlled unbound-outcome rejection; actual supervisor/container external and unverified. |
| LL045 | ASR/view/report/export/relocation regressions | Controlled scopes pass; organizer/actual-model scopes separate. |
| LL046 | Separate inputs, full 37-wheel hashed Windows/Python312/cu128 lock/manifest/generator | Fresh venv, pip check, build check/kernels pass; Python311/Linux untested. |
| LL047 | README/RUNBOOK/ASR_HANDOFF/launcher | Individual commands reviewed; real phases intentionally unexecuted. |
| LL048 | This task/gate/evidence ledger + final source inventory/ignored checks | Self-review delivered; independent review pending; no measured experiment claim. |

Organizer ToolEnv/schemas and historical reports were not modified. Hidden
`*_environment/` and `*_enviroment/` files were not read/copied/parsed. Baseline
extraction and controlled relocation exclude them. No rank/context/corpus/budget
change was made to hide OOM; no automatic phase chain or method fallback exists.

## Executed checks

Paths below are relative to ignored `.agent-work/llm-implementation/`. Each
`checks/NAME/` holds exact argv/opt-ins, revision/dirty hash, host/packages,
elapsed/exit and hashed stdout/stderr. Final invocation IDs/counts are also in
`final-evidence.json`. Interrupted/failed earlier attempts remain recorded and
are not counted as passed.

| Scope | Actual result and evidence |
|---|---|
| RV001 final LL | 99 tests: 92 pass, 7 opt-in skips; checks/RV001-handoff-20261101T154153Z-d64e50be. Includes deployment hash-binding regression. |
| RV001 runtime | 56 tests: 54 pass, 2 host symlink skips; checks/RV001-runtime-regressions-20261101T144909Z-0fb8eb79. |
| RV001 expanded core | 124 tests: 110 pass, 9 fail, 2 error, 3 skip; checks/RV001-core-regressions-20261101T145028Z-4e388954. |
| Baseline comparison | Parent 641051a: 122 tests, 108 pass, same 9 fail/2 error/3 skip; checks/baseline-641051a-core-20261101T145108Z-7221a0b8. No introduced failure IDs in this selection. |
| RV002 early decoder | 32/32 actual-tokenizer CPU cases, all nine groups; decoder-proofs/decoder-poc-20261101T150333Z-719ba02a; checks/RV002-package-bound-proof-20261101T150333Z-e39e1184. |
| RV002 real LMFE | Character-language equivalence passes; checks/RV002-backend-language-20261101T143937Z-5d7857d7. |
| RV002 native | Five actual-tokenizer rows incl. two real Fit history anchors, recursive JSONL and masks pass; native-acceptances/native-20261101T153630Z-d45a5af6; checks/RV002-native-handoff-20261101T153627Z-2c99f7a0. |
| RV003 tiny CPU | 3 pass, no CUDA initialization/download; checks/RV003-final-20261101T153615Z-0b9dc1c6. |
| RV004 inventory | Ready; actual visible input/split/tokenizer/weight hashes verified, no model libraries imported; checks/RV004-final-inventory-20261101T153724Z-0f6ed75b. Relocation/spaces evidence is controlled, not a second physical machine. |
| RV005 kernels | BF16 matmul/backward and genuine NF4 linear/input gradient pass; checks/RV005-final-NF4-kernels-20261101T153732Z-d3bb1300. No 4B model smoke/qualification. |

The eleven core failures/errors are in test_arguments (nine) and test_runpaths
(two), reproduced on source extracted from the parent with the same environment.
Exact IDs/traces are in core-regressions.json, baseline-core-regressions.json and
check logs. The expanded core suite is not green. Historical Python313 results
were not reused to qualify this Python312 environment.

Reproduce the expanded selection separately from root:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'python/tests')
& ./.venv-llm/Scripts/python.exe -m unittest -v test_agent test_arguments test_artifacts test_audio test_checkpoint test_cli test_dataset test_inference test_normalization_v2 test_runpaths test_runtime test_selection
Remove-Item Env:PYTHONPATH
```

This selection intentionally exposes baseline failures. RUNBOOK contains all
other scoped commands and the per-invocation evidence wrapper.

## Spec gate ledger

Controlled passes cover fixtures only. They do not pass required real-data/model
acceptance. This ledger updates initial planning statuses without altering requirements.

| Gate | Evidence / remaining scope |
|---|---|
| D01 | Controlled split/labels pass; actual split inventoried; full audit not run. |
| D02 | Controlled expansion pass; real corpus preparation not run. |
| D03 | Controlled prefix/leakage sentinels pass; full audit pending. |
| D04 | Controlled gold-quality checks pass; actual Fit review pending. |
| D05 | Actual-tokenizer fixture masks/budgets pass; full token corpus not run. |
| D06 | Controlled three-level support/quality pass; actual audit pending. |
| P01 | Actual CPU history/render/JSONL fixtures pass; corpus freeze pending. |
| P02 | Actual CPU native serialization fixtures pass. |
| P03 | Passed pinned-tokenizer CPU 32-case/nine-group proof. |
| P04 | Actual-tokenizer fixture masks/tiny updates pass; corpus acceptance pending. |
| P05 | Actual template/flag/hash checks pass; full corpus freeze pending. |
| L01 | Controlled analytic objective + real tiny gradients/update pass. |
| A01 | Controlled approval/review pass; actual noisy rows not built. |
| A02 | Controlled cache/mixing pass; actual caches absent. |
| A03 | Controlled coverage pass; actual meaningful-noise coverage unmeasured. |
| M01 | Real random tiny-Qwen CPU forward/backward/update/reload pass. |
| M02 | Not run: actual 4B worst-corpus qualification. |
| M03 | Tiny deterministic remaining-budget resume pass; actual 4B interruption pending. |
| M04 | Windows inventory/builds/BF16/NF4 kernels pass; real model fit unverified. |
| S01 | Tiny checkpoint/NLL/tie policy pass; real checkpoints absent. |
| E01 | Controlled one-environment/A/failure boundaries pass; real 309-source eval not run. |
| E02 | Controlled scoring/coverage/support pass; no measured model metrics. |
| E03 | Reference permission/trust unresolved; State Match null; no replay. |
| W01 | Controlled manual/config/wrapper/checkpoint scopes pass; real lifecycle pending. |
| W02 | Controlled artifact validity/tolerance/tie/policy pass; actual RV018/RV022 absent. |
| W03 | Fresh lock/inventory + controlled relocation/spaces pass; second host untested. |
| X01 | Tiny merge/reload/export guards pass; actual deployed export pending. |
| X02 | Actual A30/offline/hard supervisor not run. |
| N01 | Controlled catalog + actual CPU conformance fixtures pass. |
| N02 | Actual CPU parser/feedback/EOS rejection proof pass; model diagnostics pending. |
| N03 | Actual CPU initial/post final reachability pass; model termination unmeasured. |
| N04 | Controlled suite/proof/export/comparison bindings pass; actual rebaseline absent. |
| X03 | Actual fixed-ten full-audio latency pilot not run. |

RV006–RV010 and RV012–RV025 remain not_run in real model/data scopes. RV011
export/Fit-cache/Validation-cache resources are absent. RV005 kernel pass does not
pass its early 4B smoke scope. RV004 verifies this receiving host only.

## Receiving host and resources

Fresh `.venv-llm`, Python **3.12.10 AMD64**, Windows 11, explicit
`windows-py312-cu128` profile; no copied venv/global package changes. Python311/Linux
are untested. The lock contains 37 exact wheel hashes, including Torch2.9.0+cu128,
Transformers4.57.1, PEFT0.17.1, Accelerate1.10.1, NumPy2.3.4, LMFE0.11.3 and
bitsandbytes0.48.1. `pip check` passed.

| Measurement | Observed value |
|---|---|
| GPU | NVIDIA GeForce RTX 5070 Ti Laptop GPU, CC12.0; wheel includes sm_120 |
| Torch physical VRAM | 12,820,480,000 bytes = 12.82048 GB = 11.94000244 GiB |
| Operating cap/headroom | min(12GiB, physical) = 12,820,480,000 bytes; proposed 1,073,741,824 bytes headroom |
| Free VRAM after kernel scope | 11,406,409,728 bytes, time-specific snapshot |
| Kernel allocated/reserved peaks | 67,214,848 / 69,206,016 bytes; process/device peaks null |
| Driver/runtime/toolkit | 595.79 / CUDA12.8 / nvcc13.1; cuDNN91002 |
| Physical RAM | 33,690,472,448 bytes = 31.3767 GiB |
| Free disk snapshot | 651,362,123,776 bytes |

`nvidia-smi` MiB rounding differs slightly from Torch bytes. Allocator peaks alone
cannot qualify memory. Optional NVML Python provider is absent from the lock:
obtain/lock/verify it explicitly before full measurement. Windows process-memory
visibility may still fail; qualification must then remain resource_unverified.

Ignored local-suite.json references existing external resources without copying:

- Qwen: `D:/JarvisMate/.agent-work/models/qwen3-4b-instruct-2507`, revision
  cdbee75f17c01a7cc42f958dc650907174af0554; verified identity
  4d8e71077cf77f33999dfcb71157af1240e13278b299c29ecbb72026c410512b;
  logical 4,022,468,096 parameters from headers, no tensor load.
- Data: `D:/JarvisMate_4/DATA_JarvisMate/train+public_test`; Train SHA256
  24c42c79fbe8db932fe9817d041c0d0ca422ac8177b413cc1be0cda1fd8941a8;
  catalog a994984bb580d7e0d60166641858901d428549682ba3614dbf9269037a33cce0.
- Split: `D:/JarvisMate_4/.agent-work/asr-benchmark/split42.json`, SHA256
  ca5b9e4baf678b4fb113ec81bdb47c815fb5970bd40b918fb8db47520c920474.
- Lock SHA256: 49309ffaa9f10091f62ad14f19366d4a9dc63497c11b796645cf683ee5984b08.

The RV004 log records all individual weights/tokenizer hashes. Selected ASR,
caches, latency decision, full accepted corpus and full qualification are absent;
no substitute evidence was manufactured.

## Next separately requested work

Use RUNBOOK's independent blocks: request corpus prepare/review, seal performance
policy before outcomes and accept clean token corpus; request early 4B smoke,
explicitly resolve/lock measurement provider and qualify the common LoRA or NF4
method on actual worst rows. No silent method/rank/context/data change. L0-G can
be requested independently once native readiness is satisfied, without ASR or a
full accepted Fit corpus.

Before full L1/L2 supply selected-ASR pilot review **or an explicit recorded
operator decision** to proceed with unresolved audio latency. No decision has been
made for the user. Request independent L1/L2, each export and G/A scopes; compatible
saved L0/L1/L2 G/A artifacts precede RV018. L3 additionally requires selected Fit
ASR cache, approved full-prefix views, coverage and qualified noisy lengths.

Remaining dependencies: operator latency decision, real 4B qualification, selected
ASR provenance/caches, semantic Fit review, reference permission/trust and actual
A30 Docker/supervision/offline acceptance. Missing ASR blocks A/audio/L3, not clean
L1/L2 source or L0-G. Local success does not grant submission readiness.
