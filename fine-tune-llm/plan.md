# Implementation Plan: Native Qwen3-4B Next-Action SFT

**Project:** JarvisMate / LifeMate 2026. **Date:** 2026-11-01.
**Status:** planning only; no LLM implementation, environment setup, model execution,
or training is delivered by this document.
**Authority:** [specs.md](specs.md), version 1.3; implementation checklist:
[tasks.md](tasks.md). The specification takes precedence if these documents diverge.

This plan turns the accepted specification into three implementation increments.
It adopts the approved native model-facing protocol, keeps L0–L3 treatments, and
does not authorize execution or claim hardware/native-tokenizer compatibility. All new module, test, configuration, lock, and command paths below
are future deliverables. Existing modules are linked explicitly.

## 1. Fixed scope and architecture

```text
Current + historical user audio -> selected fine-tuned PhoWhisper-large
  -> selected transcript + supplied context/history
  -> catalog-to-native-functions + shared pinned Qwen messages/tools template
  -> Qwen/Qwen3-4B-Instruct-2507
  -> one native assistant tool call OR ordinary assistant final content
  -> native parser -> internal normalized Python decision -> original ToolEnv
  -> actual role=tool result -> native template -> next call/final
```

Keep iterative Next-Action SFT + LoRA, one general planner and at most one new call
per decision. QLoRA NF4 remains an explicitly selected resource fallback for L1–L3.
No decomposition, explicit CoT, full-trajectory generation, extra experiments,
fabricated observations, gold repair or cross-experiment warm-start.

The old model-facing action/finish JSON is superseded. Internal Python decisions
may remain compatible with agent.parse_action; they are never Qwen targets,
assistant history or native template instructions. No fake finish tool.

| Experiment | Initialization and treatment |
|---|---|
| L0 | Pinned pretrained; fresh native baseline, no optimizer updates |
| L1 | Independent same pretrained; audited gold audio_text native next-action rows; weights all 1 |
| L2 | Independent same pretrained; exact L1 corpus/order/budget; normal/ask/post-final/initial-final weights 1/2/1/2 |
| L3 | Independent same pretrained; selected L1/L2 policy, clean plus approved Fit ASR native views; proposed p_noisy=.5 |

All use the identical native renderer/catalog adapter/parser/decoder/terminal policy.
Create a new native suite and native L0; do not compare old custom L0 with native
L1–L3, reuse old token masks/accepted-format hashes, or warm-start a custom adapter.
Raw dataset/catalog/split identities, the same pinned pretrained Qwen/tokenizer
files, and verified compatible ASR assets may be reused as inputs, not as evidence
that the native format has passed.

Preserve grouped seed-42 membership: 1,236 Fit/309 Validation sources, raw
3,920/949 next-action candidates. Recompute native accepted/token-length counts.
Historical turns remain context only, current prefixes remain strict j<k, and
successful terminal ask has no extra final target. Closed-loop expected stays 309.

## 2. Existing integration boundaries

| Existing boundary | Planned use / permitted change |
|---|---|
| [dataset.py](../python/src/lifemate/dataset.py) | Extract/share pure visible projection and whitelist behavior; do not run audio/environment preflight from SFT export |
| [prompting.py](../python/src/lifemate/prompting.py) | Migrate custom SYSTEM/messages to shared native messages and tools= rendering; no trainer-only template copy |
| [planner.py](../python/src/lifemate/adapters/planner.py) | Use native renderer, raw token/EOS-aware parser and internal normalization; retain local greedy inference/Planner interface |
| [constrained.py](../python/src/lifemate/adapters/constrained.py) | Replace custom ActionConstraint for native wrappers plus tool-bound args and ordinary-final branch; prove pinned-tokenizer acceptance |
| [agent.py](../python/src/lifemate/agent.py), [runtime.py](../python/src/lifemate/runtime.py) | Reuse complete-sample ownership, one ToolEnv, actual logs/hashes, bounds and failure handling |
| [jsonio.py](../python/src/lifemate/jsonio.py) | Reuse strict JSON, visible-path guard, contained paths and file hashing; keep generic sorted-key encoding separate from completion encoding |
| [model_budget.py](../python/src/lifemate/model_budget.py) | Verify logical model counts, including quantized bases/adapters; never equate bytes with parameter count |
| [asr_training](../python/src/lifemate/asr_training) and [ASR runbook](../asr/fine-tuned/RUNBOOK.md) | Inspect export/cache provenance contracts; reuse suitable pure helpers only, without importing ASR orchestration or launching ASR jobs |
| [organizer validation](../tools/train/validate.py) | Pure schema checks only in export/audit; no exporter ToolEnv construction or hidden-state access |

Shared changes require existing pipeline regression coverage. Preserve installed-app
eligibility, internal normalized decisions, authoritative rejected-attempt logging, terminal ask semantics,
no uncertain mutation retry, and authoritative env.get_tool_calls()/get_state_hash().
Do not change organizer source. Python still owns each sample; the TypeScript
harness boundary remains as specified. Avoid importing training dependencies from
the normal inference entry point.

Native catalog/codec interfaces are future shared modules native_tools.py and
adapters/qwen_native.py. Preserve original organizer schemas/extensions and do not
modify ToolEnv. Current LL001–LL024 training modules/tests are absent; the exact
source migration audit is in specs §2.4. Existing review reports describe the prior
custom protocol and are historical evidence, not the native implementation contract.

## 3. Implementation structure and dependency direction

Use the proposed layout in specs §11.2. Keep one shared implementation behind
thin per-experiment wrappers, not four copies of training/evaluation logic.

| Module group under python/src/lifemate/llm_training/ | Responsibility |
|---|---|
| config.py, storage.py, cli.py | Strict configuration, portable roots, immutable identities, atomic artifacts, explicit command dispatch and statuses |
| data.py, audit.py | Visible projection, frozen split, strict-prefix expansion, deterministic/risk/manual audit, quarantine and review records |
| native_tools.py and adapters/qwen_native.py (shared runtime modules) | Pure catalog-to-functions adapter; native serializer/parser/EOS completion; normalized executor decision; bounded rejection feedback |
| tokenization.py | Shared native rendering; exact boundaries/masks, tools/EOS acceptance and new token-cache identity |
| models.py, resources.py | Local pinned Qwen, adapter scope, actual CUDA/kernel/resource evidence, LoRA/NF4 probes |
| losses.py, trainer.py | Completion-mean weighted objective, uniform base-row order, fixed update budget and explicit within-experiment validation |
| checkpoints.py, export.py | Durable state/resume, common NLL selection, merge and fresh offline reload |
| evaluation.py, metrics.py, pilot.py | Teacher-forced and closed-loop separation, local scoring, explicit full-audio L0 timing |
| asr_views.py | Read pre-existing caches, approve row/full-prefix views, deterministic mixing and coverage |
| reporting.py | Read-only artifact comparison, null/status handling, fixed cases, uncertainty and winner evidence level |

Dependency direction is CLI -> validated configuration -> pure data/contracts ->
explicit capability loader. Import Torch/Transformers/PEFT/bitsandbytes only inside
commands that need them. Model-free commands must work with those packages absent;
token-audit may load the local tokenizer on CPU but not weights or CUDA. Keep initial
model-free metadata separate from observed environment/package evidence so reading
status does not import Torch to collect it.

For v1, prefer a small explicit PyTorch training loop to make §7.1 accumulation and
checkpoint state auditable. This is an implementation choice within the specification,
not a new method. Do not add TRL or a general orchestration framework merely for
the first baseline. Any alternative trainer must prove the identical objective.

The CLI implements specs §11.3, including model-free status. Every invocation chooses
one phase and experiment/mode where applicable. No --all or hidden dependency runs.
Training alone performs its declared periodic teacher-forced validation; it does not
trigger probes, ASR, export, closed-loop evaluation, or another experiment.

## 4. Phase I — CPU native proof, then Data & Prompt Foundation

**Authoring tasks:** LL001–LL020. **Execution evidence:** RV001, RV002, RV006, RV007.

Implement in the following dependency order; each execution is manual and this
documentation does not run it:

1. Author core config/storage and minimal pure catalog/codec/P1/token-mask helpers
   (LL001–LL005, adapter portion of LL007, minimal LL013–LL016 and LL019 POC fixtures).
   Full Train projection, exporter, sealed suite, ASR and model weights are unnecessary
   for this prototype. Unrelated split/audit helper authoring may proceed independently.
2. Select the Vietnamese P1 text from specs §4.2 and exact ordinary final policy
   lifemate-native-final-vi-v1: NFC "Đã kết thúc.", no extra whitespace/content, followed
   by one real assistant EOS. This is a design choice, not a measured language gain
   or runtime modification. New prompt identity is lifemate-native-p1-vi-v1.
3. Explicitly run the early CPU native decoder proof (P03, RV002/decoder_poc) using
   the actual pinned local tokenizer/LMFE. Token-walk all nine fixture groups from
   specs §4.4.1: call, empty args, ask, initial/post-tool final with tools, invalid/
   multiple/partial, tag-like strings, EOS/stop boundaries and nested/array/x-one-of.
   Include backend-failure injection; do not force every decision to be a call.
   No inference/weights/GPU/ToolEnv or full corpus export is involved.
4. Only after the proof passes, integrate the full strict-prefix exporter/audits
   and full native rendering/token cache. A failed/missing proof blocks that rollout,
   P1 acceptance freeze and native L0; no custom/unconstrained fallback. Replacing
   the decoder requires reviewed new identity and the same proof, not auto-switching.
5. Implement frozen split/source hashes and pure visible projection. Expand only
   G/R pairs j<k into native input messages/tools; never R[k]/final_state. Keep
   terminal ask/initial/post-final classes and gold values unchanged. Audit and
   quarantine train_1696 k=2/dependent final k=3; retain earlier rows independently.
6. Implement all three audit levels and lossless historical conversion. Preserve
   assistant text plus the supplied multi-call array, then corresponding ordered
   tool results; do not invent interleaving, missing observations or current targets.
   Real Fit fixture anchors are train_0008/history[1] and train_0069/history[5]/[9];
   unsupported order/pairing stays needs_review or a recorded Validation failure.
7. Implement canonical native_rejection user feedback (specs §4.3.2): step/code/
   Vietnamese policy message, UTF-8-bounded quoted raw preview, stop/EOS metadata
   and Python repairability. Preserve every previous actual call/result. No fake
   role=tool, successful-call replay or custom-output instructions. Total two repair
   generations per source within existing step/time bounds; truncated/unknown stops
   and uncertain ToolEnv execution never silently retry.
8. Complete shared native renderer, exact full-template prompt-prefix/mask/EOS
   alignment and catalog/extension conformance. Mask all prior roles/tools/header/
   padding; supervise one native call/final plus EOS only. Reaudit native lengths
   at 16,384 total/512 reserved, without truncation/packing. Freeze acceptance hashes
   after the early proof and full regressions; no accepted custom masks/probes.
9. Complete focused metric/runner fixtures: native validity versus semantic accuracy,
   teacher-forced versus closed loop, all-source failure accounting, trusted-state
   availability, fixed ten diagnostic IDs and no reference leakage into Fit.

**Exit:** authored Phase I is reviewable; accepted Phase I additionally needs the
matching P03 early proof and full data/token evidence. Missing local tokenizer
resources leave the CPU proof not_run/blocked, not fake success; core/independent
source work may continue. Full exporter integration does not precede that proof.
Native L0-G still does not need L3/ASR/bootstrap/trusted state. This gate ordering
requires no GPU on the authoring machine.

## 5. Phase II — L0/L1/L2

**Authoring tasks:** LL021–LL034, plus shared handoff LL046–LL048.
**Execution evidence:** RV003–RV018 as dependencies permit.

### Evaluation and the first baseline

L0 means a freshly measured native L0. Parse native output to semantic decisions,
not exact wrapper text matching. Bind comparisons to new native protocol/catalog-
adapter/parser/decoder/terminal/template identities and report format validity/EOS
separately from semantic and final-state correctness.

Implement G and cache-backed A as separate evaluation runs using the same sample
loop. The reference reader stays outside planner inputs. Teacher-forced diagnostics
use supplied strict prefixes; closed-loop runs use only predicted calls and actual
observations. Preserve outcomes for all 309 sources even when fail-fast leaves
not_attempted cases. An explicit continue-on-error profile collects failures without
retry; never exclude failures to improve the mean. Full evaluated coverage means
309 attempted/valid outcomes and no not_attempted, not 309 successes. Timed-out is
a subset of failed; failures remain zero-scored. Partial runs cannot supply complete
selection evidence. Comparison/selection hard validity is separate from performance:
failed full-coverage runs may be ranked/selected under the predeclared tolerances
in specs §10.5. One timeout or one lost minority TP is not an automatic whole-run
veto. Metric/profile/evidence defects remain hard blockers.

Build minimal metrics/reports before L0-G: per-source local ungated F1, ask/no-action
confusion counts, teacher-forced accuracy/NLL, statuses, scope-aware timings and null
state metrics. Keep the local matcher unverified until conformance evidence exists.
L0-G may proceed after P03/P1 acceptance while ASR/A-mode is blocked. Preserve the fixed ten cases from
specs §10.5; do not turn their Validation content into training or few-shot input.

### Validity, selection and deployment evidence

Author LL024 minimal comparison with hard protocol/data/identity/export/evaluator/
coverage gates separate from performance policy. Freeze the policy hash and its
primary A criterion, reference availability, controls, regression tolerances, supports,
null handling and ties before viewing outcomes. Use trusted state-gated score if
available, otherwise provisional ungated F1; also report minority TP/FP/FN/precision,
critical arguments, failure/timeout rates, G regressions and scope-matched latency.
The proposed nonzero tolerances are specified once in specs §10.5.2; do not silently
replace them with zero-failure/zero-TP-loss requirements or post-hoc waivers.

RV018 compares L2 against L1 and ties to L1. Final promotion compares candidates
against native L0; no improvement retains L0, while passing SFT ties prefer L1/L2/L3
in that order. Optional missing diagnostic evidence stays unverified; required
missing evidence leaves selection pending. State-Verified needs trusted state,
and all submission-ready claims still need actual offline A30/full-audio acceptance.

### Actual GPU preflight and training probes

An early explicit smoke may run after minimum model/LoRA/loss/native-mask code:
short/long-prompt memory, forward/backward and one update. No final-handoff/trainer/
reporting dependency. RV008 still needs accepted native worst rows and five or
more updates; NF4 fallback qualifies separately. Hardware may remain not_run until
source-first delivery is complete.

Author compatibility/probe commands on the current machine; run them explicitly
only on the receiving local RTX 5070 Ti machine. Use specs §9 candidate versions
and primary references as the starting profile, not a validated installation claim.
Record actual SKU/GB/GiB, RAM/disk, OS, Python/driver/CUDA wheel, architecture coverage,
real kernels, attention and precision. Keep native Windows first; conditional
WSL/Linux requires a documented blocker and a separately locked/retested profile.

Probe actual longest accepted rows, finite forward/backward/update, constrained
generation and save/reload, with at least five updates under real accumulation.
Measure allocated/reserved and available device/process peaks, operating cap and
1-GiB headroom. Do not keep ASR resident during Qwen training. If LoRA fails resources,
record the failure, select genuine NF4 QLoRA explicitly, and rerun its full probe.
If neither passes, stop as unsupported/needs_decision; no silent rank/context changes.

### Objective, trainer, checkpoints and export

Implement specs §7.1 exactly: per-row completion-token mean including EOS; global
Fit mu_w; uniform base-row order; backpropagate (w_i/mu_w)*ell_i/m for actual window
size m. No extra accumulation division, weighted sampling or per-row normalization
that cancels w_i. Analytic gradient tests precede actual training claims.

Freeze common defaults in configuration: 500 updates, micro-batch 1/accumulation 16,
rank 8/alpha 16/dropout .05, q/k/v/o self-attention only, optimizer/schedule/precision
from specs §9.2. Record actual tokens/compute; equal updates do not imply equal FLOPs.
Each experiment starts from the same pinned pretrained base independently.

Save checkpoints every 100 updates and at the final step. Select the lowest
unweighted clean-G Validation completion-mean NLL, earliest-step tie. Retain periodic
and final-step checkpoints. Any fixed-step secondary comparison must be preregistered
symmetrically for L1–L3; no extra L3 search or retrospective winner selection.
Disclose that clean-G NLL may under-select L3 noise robustness.

Persist optimizer/scheduler/scaler, RNG, sampler cursor, view state, budget and
identities atomically. Resume is explicit, compatible and remaining-budget only.
Implement basic merge/export/reload now so L1/L2 comparisons score actual exported
checkpoints, including any native-NF4 versus merged-FP16 difference. Phase III adds
deployment acceptance; export validity cannot be postponed until after L1/L2 scoring.

### Early latency feasibility

Native tools injection/history/wrappers change prompt lengths and decode cost.
Reaudit tokens/resources/timings; old custom-format evidence is not native acceptance.

Implement an explicitly invoked L0 pilot using real current/history audio and the
selected fine-tuned ASR. Record per-turn ASR, per-decision prompt tokens and Qwen
calls, prefill/decode where measurable, ToolEnv setup/calls, total time and joint
VRAM/offload. Unavailable components stay null. Use the ten frozen cases; report
local feasibility separately from A30 acceptance. Cached-ASR timings are not E2E.

Missing ASR blocks the pilot, not Phase I or L0-G. Before full SFT, require the
pilot review or an explicitly recorded operator decision to proceed with unresolved
feasibility, as specified in §10.6. No preparation/training command launches it.

**Exit:** L0/L1/L2 source and controlled tests are delivered. Execution exit additionally
requires compatible complete results and actual resource evidence; writing the
trainer or obtaining low NLL does not pass those gates.

## 6. Phase III — L3 & Deployment

**Authoring tasks:** LL035–LL045, plus LL046–LL048.
**Execution evidence:** RV011–RV013 and RV018–RV025.

1. Validate the selected fine-tuned PhoWhisper-large export and Fit-only training
   membership against the ASR selection protocol. Integrate existing transcript
   caches through an explicit handoff; this pipeline must not launch ASR training
   or generate caches as an implicit prerequisite. Fit views and Validation A caches
   are separate resources. Current/historical user turns need identity/alignment;
   supplied assistant history remains unchanged. A cache miss never falls back to gold.
2. Build noisy views per next-action row, validating the entire original strict
   prefix. Require tested semantic checks or manual Fit review for non-surface
   changes; similarity/WER/LLM judgments alone cannot certify validity. Preserve
   unaffected lookup rows only when justified; reject changed transfers/conditions
   and dependent finishes. Keep needs_review excluded and never edit gold labels.
3. Use one deterministic view per uniform base-row visit, proposed p_noisy=.5 when
   an approved view exists, clean otherwise. Separate view RNG from sampler RNG;
   preserve visit budget, weights and base corpus. Persist view state for resume.
4. Report all §8.5 coverage: clean base rows, generated/assessed/approved/rejected/
   pending views, type/tool denominators, semantic-change/non-surface categories,
   meaningful errors, realized ratios and fallback reasons. Apply the proposed
   limited_noisy_coverage flag; sparse data does not authorize looser filtering.
5. Bind L3 to the saved compatible L1/L2 comparison and selected weighting policy,
   then initialize independently. Missing policy/cache/evidence is blocked_dependency.
6. Complete read-only comparisons, saved-artifact paired group bootstrap, regressions
   and winner reporting. Final promotion uses G/A closed-loop results of the actual
   export. Provisional Winner and State-Verified Winner are distinct evidence levels;
   no unrun experiment is a winner. Retain L0 if improvement/compliance is unproven.
7. Verify merged local exports, logical budgets, tokenizer/template completeness,
   fresh-process offline loading, deterministic reruns and actual full-audio results.
   Integrate with the existing container/supervision boundary; track hard timeout
   enforcement as an explicit dependency if unavailable. Do not claim A30/30-second
   acceptance from local training, a cache-backed run, or cooperative deadlines alone.

**Exit:** all native L0–L3 authoring deliverables can be handed off with unrun/blocked evidence.
Training, state verification and deployment each retain their own acceptance status.

## 7. Two-machine portability and resource handoff

Write the complete implementation on the current authoring machine without assuming
a training GPU. Transfer the repository revision plus the resource inventory in
specs §11.6 to a separate local RTX 5070 Ti host. Do not assume cloud/Colab/SSH.

| Resource class | Required boundary |
|---|---|
| Source/config/tests/docs | Exact revision and declared dirty-source patch if needed; no machine-specific defaults |
| Visible dataset/catalog and split | Original hashes, complete frozen manifest, relative source/audio references; never resplit on transfer |
| Qwen snapshot/tokenizer | Full pinned weights/shards, tokenizer/template/config/license; tokenizer can be verified independently on CPU |
| ASR checkpoint/audio/caches | Needed for the pilot/full audio or L3/A as applicable, not for clean text-only training; separate Fit/Validation provenance |
| Official ToolEnv bundle | Normally provisioned for valid runtime execution; exporter/resource hashing must not enumerate hidden environment contents |
| Environment and artifacts | Platform-specific hashed locks/wheels; optional compatible derived rows/checkpoints; measured metadata stays separate from portable content hashes |

Recreate a venv on the receiving machine; never copy a venv, CUDA DLLs or drivers.
Prepare a reproducible Windows/Python/CUDA lock and optional matching offline
wheelhouse. A conditional Linux profile gets its own lock. Specs §11.6 contains
future PowerShell examples; implementation README/RUNBOOK will document exact
working invocations once authored and tested. No setup command may start GPU work.

All resource/output paths are configurable, project-relative by default, with CLI
overrides and project-root resolution. Test relocation, spaces and non-ASCII paths.
Transfer requires root remapping and content verification, not Python source edits.
Measure actual GPU VRAM independently from host RAM; copied authoring-machine
evidence never proves target-host kernel support or fit.

## 8. Validation, artifacts and acceptance

Store generated artifacts under ignored .agent-work/llm-finetune/<suite-id>/ using
specs §11.4. Seal immutable core suite inputs; append independent run/export/report
directories, never mutate the suite to insert L3 selection evidence. Use stable
content hashes, durable manifests, bounded logs and explicit input/resource/error
statuses. All unmeasured metrics are null with reasons, not invented zeros.

| Evidence layer | What it establishes |
|---|---|
| Authored source/tests/docs | Reviewable implementation and intended checks; not executed success |
| Pure/controlled CPU checks | Covered data, serialization, masking, objective and failure contracts |
| Local tokenizer/tiny-model checks | Pinned token behavior and small real-model training mechanics; not 4B fit or quality |
| Actual RTX 5070 Ti probes/runs | Only the tested stack, profile, rows and resource/quality outcomes |
| Trusted state evaluation | State-dependent metrics for verified references and coverage; not inferred from final_state |
| Actual A30 offline full-audio acceptance | Submission-profile budget, repeatability, deadline and authoritative output evidence |

The gate-to-task matrix in [tasks.md](tasks.md#acceptance-gate-coverage) covers every
specs §13 gate. Tests are focused on behavioral risks, including existing pipeline
regressions, rather than mirroring implementation. Controlled tests must not import
ToolEnv or load weights implicitly; organizer integration, tiny-model and real-GPU
checks are explicitly selected separately. No tests or GPU jobs run as part of
writing these planning documents.

## 9. Dependencies and implementation order

```text
Minimal native helpers -> CPU decoder-poc -> full Phase I exporter/acceptance
Phase I -> minimal evaluation + pinned local model path -> L0-G
Phase I -> loss/trainer/checkpoints + verified target GPU -> L1/L2
Selected ASR + real audio -> explicit L0 pilot (review before full SFT)
Selected ASR + fixed Validation cache -> L0/L1/L2 A evaluation
Complete compatible L1/L2 G/A comparison -> explicit L3 policy
Fit ASR cache + approved full-prefix views -> independent L3
Actual exports + full comparisons -> candidate promotion
Hard validity + predeclared performance policy -> conditional candidate selection
Trusted state references -> State-Verified claim
Offline real audio on A30 + supervision -> submission acceptance
```

Source for all three phases may be completed before any GPU execution. Dependencies
govern execution, not permission to author later modules. A blocker in A/L3 must not
prevent a correct clean baseline; unavailable evidence remains visible.

Open execution dependencies remain those in specs §14: actual early CPU native
proof, selected Vietnamese P1/final token acceptance, historical order/pairing
coverage, exact host/stack and LoRA fit, selected
ASR/caches, review capacity and noisy coverage, trusted references/matcher, manifest
availability, deterministic kernels, full-pipeline latency and final supervision.
Record resolving evidence with dataset, command, host, identities and outcome.
The native protocol is the newly approved architecture contract. Do not silently
replace it with custom grammar, another model/split, edited labels or new experiments.

### Minimal dependency paths

- Minimal codec/catalog/Vietnamese P1/token fixtures -> RV002 early CPU decoder proof.
- Passed proof -> full exporter integration -> remaining render/mask/token checks
  -> P1 acceptance freeze -> native L0-G; no proof/full-export circular dependency.
- LL003–LL006 + LL046 + minimum LL047 -> RV004 transfer; not LL048.
- Minimum model/loss/mask code -> RV005 early smoke; full path -> RV008/RV009.
- Gold-text L1/L2 need full data/resource checks and audio-pilot review or explicit
  unresolved-latency decision; missing ASR alone does not block clean training.
- Saved native L0/L1/L2 G/A + LL024 -> RV018 policy; no LL042 prerequisite.
- Fit ASR cache + approved full-prefix views + RV018 -> independent native L3.

## 10. Definition of handoff

Deliver authored L0–L3 source/configuration/tests, future manual entrypoints, locks
or clearly blocked lock verification, README/RUNBOOK, resource inventory and an
honest task/evidence ledger. Identify exact missing resources and unrun commands.
Implementation handoff may precede training; executed-training completion requires
the full update budget and durable checkpoint, and winner/submission claims require
their separate measured gates. Creating this plan does not close any implementation
or execution checkbox in tasks.md.
