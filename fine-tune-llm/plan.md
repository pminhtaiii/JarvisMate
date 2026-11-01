# Implementation Plan: Qwen3-4B Next-Action SFT

**Project:** JarvisMate / LifeMate 2026. **Date:** 2026-11-01.
**Status:** planning only; no LLM implementation, environment setup, model execution,
or training is delivered by this document.
**Authority:** [specs.md](specs.md), version 1.1; implementation checklist:
[tasks.md](tasks.md). The specification takes precedence if these documents diverge.

This plan turns the accepted specification into three implementation increments.
It does not change the experiments, authorize their execution, or claim hardware
compatibility. All new module, test, configuration, lock, and command paths below
are future deliverables. Existing modules are linked explicitly.

## 1. Fixed scope and architecture

```text
Current + historical user audio
  -> selected frozen fine-tuned PhoWhisper-large
  -> one transcript view + supplied context/history/tools
  -> shared Structured Prompt P1
  -> Qwen/Qwen3-4B-Instruct-2507
  -> one call/finish JSON
  -> existing deterministic dispatch -> original ToolEnv
  -> actual observation -> P1 -> next call/finish
```

Implement offline Next-Action SFT with LoRA. QLoRA is a resource-probe-driven
fallback, selected consistently for L1–L3 before full comparable runs. No Request
Decomposition, explicit CoT, full-trajectory prediction, fabricated observations,
counterfactual relabeling, extra experiments, or warm-start between experiments.

| Experiment | Initialization and treatment |
|---|---|
| L0 | Pinned pretrained base; no optimizer updates |
| L1 | Same pretrained base; audited clean Fit rows using gold audio_text; weights all 1 |
| L2 | Independent same base; exact L1 corpus/order/budget; normal/ask/post-finish/initial-finish weights 1/2/1/2 |
| L3 | Independent same base; selected L1/L2 weighting policy; same clean base rows with approved Fit ASR views; proposed p_noisy=0.5 |

Use the pinned revision and identities in specs §2/§9, not floating model main.
Keep the audited grouped seed-42 split: 1,236 Fit and 309 Validation sources, with
3,920/949 raw candidate next-action rows before filtering. Seed alone is insufficient
to recreate membership. The 309-source closed-loop denominator never shrinks when
teacher-forced references or training rows fail audits. Initial finish and finish
after calls are separate types; a terminal successful ask has no following finish.

## 2. Existing integration boundaries

| Existing boundary | Planned use / permitted change |
|---|---|
| [dataset.py](../python/src/lifemate/dataset.py) | Extract/share pure visible projection and whitelist behavior; do not run audio/environment preflight from SFT export |
| [prompting.py](../python/src/lifemate/prompting.py) | Own shared P1 messages/rendering and canonical prior-action serialization; avoid a trainer-only prompt copy |
| [planner.py](../python/src/lifemate/adapters/planner.py) | Consume the shared renderer; retain greedy local inference and Planner interface |
| [constrained.py](../python/src/lifemate/adapters/constrained.py) | Reuse actual tool-bound grammar/schema order and tokenizer-prefix checks |
| [agent.py](../python/src/lifemate/agent.py), [runtime.py](../python/src/lifemate/runtime.py) | Reuse complete-sample ownership, one ToolEnv, actual logs/hashes, bounds and failure handling |
| [jsonio.py](../python/src/lifemate/jsonio.py) | Reuse strict JSON, visible-path guard, contained paths and file hashing; keep generic sorted-key encoding separate from completion encoding |
| [model_budget.py](../python/src/lifemate/model_budget.py) | Verify logical model counts, including quantized bases/adapters; never equate bytes with parameter count |
| [asr_training](../python/src/lifemate/asr_training) and [ASR runbook](../asr/fine-tuned/RUNBOOK.md) | Inspect export/cache provenance contracts; reuse suitable pure helpers only, without importing ASR orchestration or launching ASR jobs |
| [organizer validation](../tools/train/validate.py) | Pure schema checks only in export/audit; no exporter ToolEnv construction or hidden-state access |

Shared changes require existing pipeline regression coverage. Preserve installed-app
eligibility, custom action grammar, rejected-attempt logging, terminal ask semantics,
no uncertain mutation retry, and authoritative env.get_tool_calls()/get_state_hash().
Do not change organizer source. Python still owns each sample; the TypeScript
harness boundary remains as specified. Avoid importing training dependencies from
the normal inference entry point.

## 3. Implementation structure and dependency direction

Use the proposed layout in specs §11.2. Keep one shared implementation behind
thin per-experiment wrappers, not four copies of training/evaluation logic.

| Module group under python/src/lifemate/llm_training/ | Responsibility |
|---|---|
| config.py, storage.py, cli.py | Strict configuration, portable roots, immutable identities, atomic artifacts, explicit command dispatch and statuses |
| data.py, audit.py | Visible projection, frozen split, strict-prefix expansion, deterministic/risk/manual audit, quarantine and review records |
| tokenization.py | Import shared production rendering; exact supervised boundaries/masks, token audit and cache identity |
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

## 4. Phase I — Data & Prompt Foundation

**Authoring tasks:** LL001–LL020. **Execution evidence:** RV001, RV002, RV006, RV007.

1. Define strict configs, resource inventory, portable paths, stable provenance,
   artifact schemas and sealed-suite storage. Validate the existing split, source
   hashes and complete membership; missing manifest is a dependency failure.
2. Build a pure projection of request/context/history/permitted tools. Read labels
   only in the exporter/reference reader. Expand gold pairs into exact strict-prefix
   rows. Never expose R[k] to decision k or use final_state as evidence.
3. Implement the three audit levels: deterministic validation, semantic risk
   screening, and recorded manual review. High-risk/ambiguous rows stay needs_review
   until resolved. Preserve gold; quarantine train_1696 k=2 and dependent finish k=3.
   Accept earlier rows only after independent checks; no prefix splicing.
4. Implement the action serializer at the shared prompt boundary: envelope order
   action -> name -> arguments, recursively matching decoder schema order. Generic
   sorted-key JSON remains appropriate for bodies/results, not action completions.
5. Implement P1 and migrate inference to the same rendering contract. For the pinned
   non-thinking tokenizer, omit enable_thinking only after verifying exact rendered
   text/token equivalence to the installed adapter call on contract fixtures.
6. Construct prompt+completion sequences with exactly one final <|im_end|>. Labels
   cover the target JSON/EOS only; history/prompt/observations/padding are -100.
   Verify exact inference-prefix IDs, joint token boundaries and grammar acceptance.
7. Token-audit separately using the local pinned tokenizer; cap prompt+512 at
   16,384 and completion at 512 including EOS. Quarantine overflow without truncation.
   Freeze P1 version/hashes only after acceptance, then seal the accepted corpus.
8. Prepare focused evaluation fixtures before real predictions: duplicate/fuzzy
   matching, empty gold, strict ask, invalid outputs, failure accounting, unavailable
   state references, and the existing ten fixed diagnostic IDs.

**Exit:** data, audit, prompt, serialization, mask and metric-fixture source is
reviewable. Executed acceptance is separate. A valid L0-G baseline does not depend
on L3, exhaustive semantic automation, bootstrap reporting or trusted state hashes.
Full training still requires an audited accepted Fit corpus and actual token checks.

## 5. Phase II — L0/L1/L2

**Authoring tasks:** LL021–LL034, plus shared handoff LL046–LL048.
**Execution evidence:** RV003–RV018 as dependencies permit.

### Evaluation and the first baseline

Implement G and cache-backed A as separate evaluation runs using the same sample
loop. The reference reader stays outside planner inputs. Teacher-forced diagnostics
use supplied strict prefixes; closed-loop runs use only predicted calls and actual
observations. Preserve outcomes for all 309 sources even when fail-fast leaves
not_attempted cases. An explicit continue-on-error profile collects failures without
retry; never exclude failures to improve the mean or promote an incomplete run.

Build minimal metrics/reports before L0-G: per-source local ungated F1, ask/no-action
confusion counts, teacher-forced accuracy/NLL, statuses, scope-aware timings and null
state metrics. Keep the local matcher unverified until conformance evidence exists.
L0-G may proceed while ASR/A-mode is blocked. Preserve the fixed ten cases from
specs §10.5; do not turn their Validation content into training or few-shot input.

### Actual GPU preflight and training probes

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

**Exit:** all L0–L3 authoring deliverables can be handed off with unrun/blocked evidence.
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
Phase I -> minimal evaluation + pinned local model path -> L0-G
Phase I -> loss/trainer/checkpoints + verified target GPU -> L1/L2
Selected ASR + real audio -> explicit L0 pilot (review before full SFT)
Selected ASR + fixed Validation cache -> L0/L1/L2 A evaluation
Complete compatible L1/L2 G/A comparison -> explicit L3 policy
Fit ASR cache + approved full-prefix views -> independent L3
Actual exports + full comparisons -> candidate promotion
Trusted state references -> State-Verified claim
Offline real audio on A30 + supervision -> submission acceptance
```

Source for all three phases may be completed before any GPU execution. Dependencies
govern execution, not permission to author later modules. A blocker in A/L3 must not
prevent a correct clean baseline; unavailable evidence remains visible.

Open decisions remain those in specs §14: exact host/stack and LoRA fit, selected
ASR/caches, review capacity and noisy coverage, trusted references/matcher, manifest
availability, deterministic kernels, full-pipeline latency and final supervision.
Record resolving evidence with dataset, command, host, identities and outcome.
Do not silently change the architecture, model, split, labels or experiment policy.

## 10. Definition of handoff

Deliver authored L0–L3 source/configuration/tests, future manual entrypoints, locks
or clearly blocked lock verification, README/RUNBOOK, resource inventory and an
honest task/evidence ledger. Identify exact missing resources and unrun commands.
Implementation handoff may precede training; executed-training completion requires
the full update budget and durable checkpoint, and winner/submission claims require
their separate measured gates. Creating this plan does not close any implementation
or execution checkbox in tasks.md.
