# Tasks: Qwen3-4B Next-Action SFT

**Project:** JarvisMate / LifeMate 2026. **Date:** 2026-11-01.
**Status:** planned; all implementation and execution items below remain open.
**References:** [specs.md](specs.md), version 1.1, and [plan.md](plan.md).
The specification is authoritative. New paths/commands are future deliverables.
This revision changes checklist dependencies and evidence definitions only; it
does not select new prompt text, modify runtime code or execute any task.

## How to use this checklist

- LL tasks describe source/configuration/test/document authoring. Check them only
  after the stated deliverables exist and are reviewed. An authored test is not a
  passing test; record execution separately under RV and the acceptance ledger.
- RV tasks describe explicitly requested execution on a suitable machine. Record
  command, revision, input/model/config identities, host/environment, exit/status,
  artifact paths/hashes and measured outcomes. An attempted run with a failure
  record does not pass its acceptance gate. Blocked/unrun tasks remain open.
- Work sequentially by dependency; this checklist does not request parallel agents.
  All source may be written on the current machine before transfer. Execution
  dependencies must not force training on the authoring machine.
- No training, inference, package installation, GPU probe/pilot, cache generation,
  or experiment chain is authorized by creating these documents. Each future run
  is manual and separate; no import/setup/prepare side effects.
- No implementation or execution task is checked merely because the specification,
  plan and checklist have been written. Unmeasured metrics stay null with reasons.
- LL dependencies govern authored interfaces; RV dependencies govern execution.
  Authoring a probe or its tests never requires first running that probe. Hardware
  RV items may remain not_run until all source is transferred; that is not an
  implementation failure. A staged RV record must identify its scope explicitly.

## Evaluation coverage contract

Use this contract in LL021–LL024 and RV010/RV013/RV015/RV017/RV021/RV022:

- `expected=309`; every expected ID has exactly one validated outcome record.
- `attempted + not_attempted = 309`; `completed + failed = attempted`.
  `completed` includes successful `needs_info`; `timed_out` is a reported subset
  of `failed`, not an additional disjoint count. Normalize runner statuses to this
  convention and record the mapping.
- Full evaluated coverage means `attempted=309` and `not_attempted=0`, with valid
  outcomes for all IDs. It does **not** mean `completed=309`. A fully evaluated run
  with failures/timeouts is scoreable and comparable under the same profile:
  failures score zero under specs §10.3 and remain in the 309 denominator, never
  successful empty predictions. Preserve available attempted calls and failures.
- Any `not_attempted>0`, missing/duplicate outcome, or invalid artifact makes the
  evaluation partial/incomplete. Fail-fast placeholders do not make it complete;
  report coverage/status and withhold complete-run deltas/selection. Never invent
  timing, successful empty output or state hashes for unattempted cases.
- Report evaluated coverage (`attempted/309`) separately from successful completion
  coverage (`completed/309`), failure/timeout counts and measured timing supports.
- Scoreability/comparability is separate from promotion. Specs §10.5 currently
  proposes `309 completed` and no timeouts for promotion. Keep that stricter gate
  explicit: a fully evaluated failed run may be compared or inform L1/L2 policy
  selection, but must not be promoted by silently weakening the gate.

## Phase I — Data & Prompt Foundation

Dependencies within this phase: LL001–LL005 establish IO/config boundaries;
LL006–LL012 establish data/audit; LL013–LL017 establish shared prompt/tokens;
LL018–LL020 author the corresponding behavioral checks. The shared renderer is
required for both training and inference, not a second trainer-specific prompt.

- [ ] LL001 Create lazy `lifemate.llm_training` package/CLI entrypoints with explicit command dispatch, including model-free status. Keep model-free commands usable without Torch/Transformers/PEFT/bitsandbytes. Reject L0 training, implicit all-experiments execution, and hidden dependency runs. Add import/no-side-effect fixtures.
- [ ] LL002 Implement strict configuration and versioned artifact schemas in `config.py`: L0–L3 treatments, pinned Qwen revision, seed-42 split/training versus inference seed 20261027, fixed limits, method and policy identities. Reject unknown fields, invalid values, floating revisions and unsupported treatment changes.
- [ ] LL003 Implement project-root path resolution and CLI overrides for data/model/ASR/split/cache/output/suite paths. Use relative defaults, contained writable roots and visible-path guards. Handle spaces/non-ASCII paths and reject traversal; exclude machine-specific absolute paths from portable content identity.
- [ ] LL004 Implement `storage.py` stable hashes, atomic writes, immutable core suite sealing and unique run/export/report directories. Record source revision/dirty-patch identity, status and error provenance; do not overwrite durable checkpoints or scan hidden environment files.
- [ ] LL005 Implement model-free `verify-resources` and `preflight`: phase-specific inventory, visible source/model-file/cache hashes and missing-resource reports without model-library imports. Distinguish source, data/audio, weights, tokenizer, ASR exports, caches, split, environment locks and generated artifacts; optional ASR must not block clean preparation.
- [ ] LL006 Validate the existing grouped seed-42 manifest against exact specs §2 source/catalog/split hashes, membership and group disjointness. Map manifest train to Fit; preserve 1,236/309 sources and Fit smoke IDs. Missing/mismatched identity fails rather than resplitting.
- [ ] LL007 Implement a pure visible projection in `data.py`, sharing appropriate dataset whitelist logic. Preserve chronological user/assistant history and exact installed tools plus sys. Separate gold/reference reading from planner input; exclude labels, final_state, provenance and audio/cache metadata from rendered inputs. Do not invoke full inference/audio/environment preflight.
- [ ] LL008 Implement next-action expansion with exact G/R pairing and j<k observations. Emit normal calls, terminal asks, initial finish and valid post-tool finish distinctly. Reject continuation after successful terminal ask and never append finish after it. Preserve complete results and read/empty-search calls; do not reorder gold or use R[k] as input to row k.
- [ ] LL009 Implement Level 1 deterministic audit using pure organizer schema checks and decoder contract checks: JSON shape, tool availability, pairing, strict prefixes, terminal consistency, canonical format and leakage. Add token-audit integration points without loading tokenizer/weights during model-free export.
- [ ] LL010 Implement Level 2 semantic-risk records and Level 3 manual-review ingestion in `audit.py`: stable reasons, evidence paths/slot bindings, reviewer/policy identity and original-target hash. Screen amount/currency, entity/ID, phone/time, negation/correction, conditions, grounding and finish. Critical transactions/flagged ambiguity require review; unresolved rows stay needs_review and excluded. Never claim heuristic whole-corpus semantic proof.
- [ ] LL011 Implement dependent-prefix/finish disposition. Quarantine train_1696 k=2 and dependent finish k=3 without ID/label repair; retain k=0/1 only after their own audits. Require full original-prefix validity for every later accepted row; do not splice out rejected calls/results.
- [ ] LL012 Write specs §5.5 data/audit artifacts atomically, with accepted/needs_review/quarantined statuses, stable multi-reason codes, source/type/tool/risk/level coverage, manual backlog and row identities. Keep L1/L2 clean corpus identical; report filtered teacher-forced supports without changing 309 closed-loop membership.
- [ ] LL013 Implement the canonical action serializer at the shared prompt boundary. Enforce compact action/name/arguments envelope order, recursive actual decoder-schema key order/x-one-of selection, exact values/arrays/Unicode/leading zeros, empty arguments and exact finish. Keep generic sorted-key body/result serialization separate.
- [ ] LL014 Implement shared P1 messages/rendering in the existing prompting boundary, preserving chronological roles, complete observations and bounded rejection feedback. Before freezing, record the exact system content/language and its decision basis. The least-change preference is Vietnamese `lifemate-react-v4` plus missing rules; specs §4.2 instead instructs an English draft, so resolve `P1_LANGUAGE_ALIGNMENT` explicitly before choosing/finalizing text. Do not silently substitute either language. Keep action-only custom grammar, no native tools/XML, decomposition or CoT; record the complete contract, not just a system-string hash.
- [ ] LL015 Migrate `LocalPlanner` to the same P1 renderer, canonical prior-action serializer and pinned tokenizer/chat template used by SFT. Test omission of `enable_thinking` against the prior flag-enabled call using the **same selected P1 messages**; exact text/token equality tests flag behavior, not equivalence between old Vietnamese and new English prompts. Preserve Planner interface, greedy settings, tool eligibility, bounds and `selection_filter=false` comparison profile.
- [ ] LL016 Implement `tokenization.py` exact prompt-prefix/completion alignment using the shared renderer and canonical `action → name → arguments` serializer. Supervise final action plus exactly one pinned `<|im_end|>`; mask assistant header, prompt, prior assistant actions, observations and padding. Validate joint boundaries rather than trusting independent fragment tokenization.
- [ ] LL017 Implement explicit CPU `token-audit`, prompt-contract freeze and token-cache identity. Require resolved P1 content/language, pinned tokenizer/template/grammar, exact rendered IDs across SFT/inference, parser/token-prefix/EOS acceptance, prompt+512 <=16384 and completion <=512. Freeze version and all content/renderer/template/serializer/token hashes only after acceptance tests pass; unresolved language blocks freeze/L0, not authoring the renderer or other Phase I code. Quarantine overflow without truncation/packing.
- [ ] LL018 Author `test_llm_data.py` and `test_llm_audit.py` behavioral fixtures for split/hash drift, pairing, source expansion counts, both finishes, terminal ask, future-result/final_state sentinels, no hidden-state access, risk/manual status, train_1696 and dependent suffixes. Deny ToolEnv/weight access from pure exporter tests.
- [ ] LL019 Author `test_llm_prompting.py` and `test_llm_tokenization.py` checks for exact shared rendering, canonical recursive order, sorted-key negative example, phone/Unicode/array round trips, same-message template flag equivalence, tokenizer boundaries/EOS/padding and context overflow. Test that unresolved P1 language/content cannot be frozen. Include existing prompt/planner regression cases; keep pinned-tokenizer checks explicitly separate from pure fixtures.
- [ ] LL020 Implement pure metric fixtures/core `metrics.py`: maximum one-to-one duplicate/fuzzy matching with strict >0.6 boundary, failure-aware empty gold, ask strict ordered params, no-action, invalid outputs/four classes, undefined supports and missing trusted references. Preserve the ten fixed Validation diagnostic IDs as evaluation fixtures, never Fit/few-shot input.

**Phase I authored exit:** LL001–LL020 deliver reviewable data/P1/fixture code.
**Executed exit:** relevant RV001/RV002/RV006/RV007 evidence and gates below; no
checkbox here establishes 4B training feasibility or model quality.

## Phase II — L0/L1/L2

Start a correct L0-G path after Phase I core contracts and LL021–LL024; it need not
wait for L3, exhaustive reporting automation or trusted state references. Trainer
authoring can proceed independently of access to the eventual GPU host. Full
training needs actual data/token/resource evidence and the latency review policy.

- [ ] LL021 Implement `evaluation.py` closed-loop runner using existing run_sample/RuntimeFactory. Support separate G/A invocations, one ToolEnv per sample/run, label-free planner inputs and actual calls/hash. Enforce the evaluation coverage contract above, no uncertain retries and explicit fail-fast/continue-on-error policy. L0-G and its planner/tools timing use gold transcripts without ASR/checkpoints/caches; preserve scope labels and never call that audio end-to-end timing.
- [ ] LL022 Implement teacher-forced G/A diagnostics with strict gold prefixes, completion-mean unweighted NLL, exact next-action/argument/type supports and invalid/unusable reference accounting. Keep this distinct from closed loop; mark noisy semantic-change strata as diagnostic, never silently filter full A evaluation.
- [ ] LL023 Connect all specs §10.3 metrics and prediction/outcome/report schemas, including coverage invariants and failure=0 scoring without dropping sources. Preserve authoritative arguments, local matcher trust, supports, status/reasons and timing scopes. Investigate whether organizer rules/runtime permit a **separate reference-only run** of Train gold calls through ToolEnv to obtain trusted reference hashes; document eligibility, isolation, exact dataset/runtime/catalog/canonicalization identities, expected outcomes and trust/conformance checks before any implementation/execution of that path. Do not assume gold replay is valid. No second ToolEnv in a prediction run, direct hidden-state reads or `label.final_state` hashing; state metrics stay null pending trusted evidence. Investigation must not block ungated local scoring.
- [ ] LL024 Implement minimal read-only comparison/status and fixed-ten-case reporting sufficient for saved L0/L1/L2 results **and L3 weighting-policy selection at RV018**. Require explicit run/checkpoint selection and shared-control compatibility while permitting intended model/weight/view differences and L0 zero updates. Use the coverage contract: fully evaluated failed runs remain scoreable/comparable with zero-scored failures; partial/missing/incompatible runs give null complete-run deltas and cannot supply policy evidence. Implement the existing A criterion/tie rule and a saved policy record here; no LL042/full-eight-row/bootstrap dependency. Compare imports no model/device dependencies and never runs replay.
- [ ] LL025 Implement `resources.py` explicit GPU preflight for actual local RTX 5070 Ti: SKU/physical/free VRAM in bytes/GB/GiB, RAM/disk, Windows/Python/driver/CUDA wheel, architecture coverage and allocation/matmul/backward. Keep CUDA-runtime/toolkit labels distinct; record actual kernels/precision. Document conditional WSL only for reproduced native blockers.
- [ ] LL026 Implement `models.py` pinned local Qwen/config/tokenizer loading and LoRA scope assertions: q/k/v/o projections in every decoder self-attention layer, rank/alpha/dropout from config, base frozen and only adapter A/B trainable. Implement genuine NF4/double-quantization fallback with k-bit preparation and explicit version/build validation; no silent int8 or CPU substitution.
- [ ] LL027 Implement two explicit probe scopes without a new experiment: an early feasibility smoke after minimum model/adapter/loss code exists, and full resource qualification for RV008. Early smoke tests local model/tokenizer loading, LoRA injection, masked forward/backward, one optimizer update and memory for short and representative long prompts; it need not wait for final trainer/checkpoint/report infrastructure or a sealed full corpus. Use LL028 for the loss/update helper; record fixture provenance/lengths and that this is not worst-corpus qualification. Full scope tests actual accepted worst-length/completion rows, at least five updates with real accumulation, finite gradients, generation and save/reload. Capture memory scopes/headroom and overhead; ASR is not resident. NF4 is an explicitly chosen fallback with its own smoke/full evidence, never an automatic rank/context/data/method change.
- [ ] LL028 Implement `losses.py` exact specs §7.1 objective: row completion mean including EOS, global Fit mu_w, uniform base visits, per-window (w_i/mu_w)*ell_i/m and actual partial m. Prevent double division or micro-batch weight cancellation; no weighted sampling/oversampling. Author analytic loss/gradient fixtures including relative ask weight 2.
- [ ] LL029 Implement explicit fixed-budget trainer: independent pretrained initialization, deterministic uniform epoch shuffling, 500 updates/16 accumulated rows, AdamW/schedule/clipping/checkpointing and probed precision. Log actual tokens/type visits and finite/update failures. Use common clean-G unweighted teacher-forced NLL every 100 updates/final; no experiment-specific early stopping or implicit extra phases.
- [ ] LL030 Implement `checkpoints.py` durable periodic/final checkpoints and best/latest pointers; save optimizer/scheduler/scaler, all RNGs, sampler/view state, identities, completed/remaining budget and NLL selection history. Earliest-step NLL tie, retained final step, symmetric preregistered secondary step analyses only. Explicit compatible resume rejects corrupt/probe/cross-experiment/cross-method checkpoints.
- [ ] LL031 Implement basic export/verify-export now for actual L1/L2 evaluation: verified selected adapter plus fresh correct base, merged FP16 local directory containing weights/tokenizer/template, logical parameter counts and fresh offline reload. Record merge/native quantization differences; export failure cannot silently substitute native checkpoint scores.
- [ ] LL032 Implement separately invoked L0 full-audio latency pilot on the ten fixed cases. Capture current/history ASR, per-decision Qwen prompt/generated tokens and call counts, measured prefill/decode or explicit null separation, ToolEnv and total time, joint memory/offload. Persist pilot status and host/profile; no setup/prepare/train auto-trigger or cached-ASR/A30 equivalence claim.
- [ ] LL033 Add explicit common/L1/L2 configurations and thin run_l0/run_l1/run_l2 wrappers plus all Phase II CLI commands in specs §11.3. Require matching full probe/token evidence for training, one experiment/phase/mode per invocation and explicit resume/export/evaluation. Gold `audio_text` L1/L2 training requires no ASR resources: accept a recorded completed full-audio pilot review **or** explicit operator decision to proceed with unresolved full-audio latency under specs §10.6. Planner-only timing cannot satisfy the audio pilot. No automatic dependency execution.
- [ ] LL034 Author `test_llm_training.py`, `test_llm_checkpoints.py`, `test_llm_evaluation.py` and `test_llm_manual.py`: weighted accumulation, scope/frozen state, invalid config/resource evidence, interruption/resume, NLL selection, one environment/real observations, coverage and model-free compare. Add separately enabled random tiny-Qwen update/save/reload tests without downloads; author actual-GPU checks separately and retain baseline regression coverage.

**Phase II authored exit:** source for baseline, L1/L2 and actual-export evaluation
is ready for review/handoff, with locks/runbook in LL046–LL048.
**Executed exit:** RV003–RV018 outcomes as applicable; L0-G may stand alone while
A/pilot is blocked, but L3 policy cannot be selected from incomplete comparisons.

## Phase III — L3 & Deployment

LL035–LL045 can be authored before training, using controlled fixtures. Executing
L3 additionally requires selected-ASR provenance, approved Fit views and a saved
compatible L1/L2 G/A policy comparison. Never warm-start L3 from a winner adapter.

- [ ] LL035 Implement strict ASR export/cache manifest validation and explicit handoff integration: selected fine-tuned PhoWhisper-large, Fit-only training membership, base/export/processor/decoding/package hashes and selection evidence. Separate Fit/Validation current/history turn caches and audio identity/alignment. Missing resources block dependent phases; do not run ASR to manufacture them.
- [ ] LL036 Implement `asr_views.py` row/full-original-prefix acceptance with certificates/review decisions for semantic slots, conditional branches and downstream finish. Initially auto-accept only tested meaning-preserving transformations; non-surface changes need validated semantic checks/manual Fit review. Test unaffected lookup versus changed transfer, recipient/time/negation errors and dependent finish; never splice prefixes or relabel gold.
- [ ] LL037 Implement deterministic proposed p_noisy=.5 per-base visit mixing with an independent view RNG, same base order/weights/visit budget and resume state. Record approved/noisy/clean choices and explicit clean fallback for missing/rejected/overlong training views. Never concatenate clean+ASR or use this fallback in A evaluation.
- [ ] LL038 Implement mandatory §8.5 coverage artifacts: total clean bases, generated/assessed/approved views and distinct rows/sources, approval by type/tool with both denominators, rejection/pending/cache/unassessed reasons, surface/non-surface/semantic-change categories, realized visit ratios and meaningful-error coverage. Apply preregistered limited_noisy_coverage reporting thresholds without loosening acceptance or fabricating noise.
- [ ] LL039 Add L3 config/wrapper/trainer integration with an explicit hashed compatible L1/L2 policy report, independent pretrained initialization and inherited common objective/budget. Keep sealed core suite unchanged; missing comparison/ASR/certificates fail as blocked_dependency. Sparse augmentation remains visibly limited or blocked under declared policy.
- [ ] LL040 Implement the cache-backed ASR adapter for A evaluation using the existing ASR protocol, source/turn/audio/checkpoint validation and no reference access/gold fallback. Preserve complete-sample ownership and supplied assistant history. Cache-backed timing is planner/tools scope; absent/mismatched turns fail explicitly.
- [ ] LL041 Complete offline export/reload and budget acceptance hooks: complete tokenizer/config/template, correct logical counts for merged/unmerged/quantized forms, fresh-process network-disabled loading/generation, target-host repeatability, missing-file and mismatched-contract failures. Keep training infrastructure out of deployed models and total parameter accounting.
- [ ] LL042 Extend LL024 to final artifact-only CSV/JSON/Markdown comparison for all eight L0–L3 x G/A rows, deltas versus L0 and selected policy, fixed cases/regressions and paired group bootstrap (1,000 resamples, seed 42). Compare fully evaluated runs with correctly scored failures; mark partial runs explicitly and withhold complete-run selection/deltas. Separately apply the stricter preregistered specs §10.5 promotion gates; failed/timed-out full-coverage runs are not automatically promotion-eligible. Distinguish provisional ranking, Provisional Winner, State-Verified Winner and deployment acceptance. Retain L0/no promoted winner when evidence or gates are insufficient. LL042 is required by RV022, not RV018.
- [ ] LL043 Implement explicitly invoked full-audio evaluation integration with selected ASR/Qwen, actual export identities, complete current/history timing, authoritative results, failure accounting and joint-memory measurements. Measure initialization/warmup separately; no cached-A substitution for full audio or automatic ASR training/export selection.
- [ ] LL044 Define A30/Docker acceptance hooks and the interface to existing process supervision: offline assets, <5B LLM/<6B total, <=16384 context, hard sample deadlines, cleanup and failure/output accounting. Reuse the submission boundary; disclose missing supervisor/container support as a dependency rather than treating cooperative timeout as solved or building unrelated infrastructure.
- [ ] LL045 Author `test_llm_asr_views.py`, `test_llm_reporting.py` and export/portability extensions covering cache separation/provenance, strict prefixes, semantic-risk views, RNG/resume, meaningful-noise coverage, limited flag, treatment compatibility, null metrics and winner evidence. Keep full-audio/organizer/actual-GPU tests explicitly enabled and separate from pure fixtures.

## Cross-phase delivery — Portability & Runbook

Start these during Phase I; complete them before claiming an implementation handoff.

- [ ] LL046 Author separate training/QLoRA dependency inputs, a platform-specific full hashed Windows/Python/CUDA lock-generation/verification procedure, resource manifest and optional matching offline-wheelhouse instructions. Pin candidate versions/builds from specs §9, with observed compatibility status separate. Never mark an unverified lock as tested or copy a venv; add a separate Linux lock only if the conditional profile is actually needed.
- [ ] LL047 Write `fine-tune-llm/README.md` and `RUNBOOK.md` incrementally. Deliver a minimum setup/transfer/resource-inventory section early for RV004; later complete project-root CLI overrides, manual L0/L1/L2/L3/probe/pilot/evaluate/export/compare/resume commands, blocked states and reproducibility. Distinguish VRAM from RAM, native Windows evidence from conditional WSL, early smoke from full qualification, planner-only from audio latency and local feasibility from A30 acceptance. No final-runbook dependency for early transfer/probes.
- [ ] LL048 Perform the **final implementation review/handoff** after LL001–LL047 authoring, not as a prerequisite to RV004/RV005/RV008 or L1/L2. Prepare the gate ledger, source revision, resource locations/hashes, exact manual commands and unresolved dependencies. Review authored portability checks and record actual relocation evidence if available; hardware RV tasks may all remain not_run when the user chooses source-first delivery. Verify ignored data/weights/caches and bounded logs; do not claim unrun gates or modify old reports into results.

## Execution checklist — Receiving machine and acceptance evidence

These are future manual tasks, not instructions to run now. RV IDs identify evidence
collection, while the acceptance ledger below determines whether each gate passed.
Source authoring may finish even when execution dependencies are unavailable.

### CPU, data and pinned-tokenizer evidence

- [ ] RV001 Run focused pure/controlled Phase I tests and relevant existing pipeline regressions, proving model-free CLI/imports do not load model libraries, weights, ToolEnv or CUDA implicitly. **Phase I prerequisites: LL018–LL020 and their Phase I code only; no LL034/LL045 dependency.** This Phase I run may complete RV001's initial scope. Append separately identified Phase II/III test-run records when LL034/LL045 are authored, with exact revision/test selection/results and gate scope; an earlier Phase I pass cannot stand for those later checks. Never overwrite earlier evidence or wait for later phases to test Phase I.
- [ ] RV002 Run explicit CPU tests using the pinned local tokenizer/template/LMFE stack: exact P1 text/IDs across paths, flag equivalence, action-prefix/EOS acceptance and completion masks. Freeze P1 hashes only after acceptance. Dependencies: LL013–LL019 and tokenizer resources; no inference/weight loading.
- [ ] RV003 Run separately enabled random tiny-Qwen forward/backward/update/save/reload and interruption/resume tests. Verify only adapters update, objective/masks and deterministic remaining-budget behavior. No checkpoint downloads; this does not establish actual 4B memory fit. Dependencies: LL026–LL031, LL034.
- [ ] RV004 On the receiving local machine verify transferred source, visible dataset/catalog/split, local model/tokenizer and phase-required resource inventory. Recreate the venv from the correct platform lock and record relocation/paths-with-spaces checks; never copy the authoring venv. **Prerequisites: LL003–LL006, LL046 and only LL047's minimum setup/resource-inventory section. LL048 and the final runbook are not prerequisites.** Verify optional ASR/caches only for requesting phases. An early transfer may carry the minimum viable training path; final source delivery may occur later without Python path edits.
- [ ] RV005 Execute explicitly selected actual-device checks on the local RTX 5070 Ti, with scoped records: first kernel/platform preflight (LL025 + RV004), then early training feasibility when LL026/LL028 and LL027's small probe path are authored and local token-mask fixtures are verified. Early smoke checks model/tokenizer load, LoRA injection, masked forward/backward, one optimizer update and short/long-prompt memory; explicitly probe genuine NF4 if LoRA fails and the operator selects that fallback. No LL029–LL034, RV003, sealed worst-corpus qualification or LL048 prerequisite for this early smoke. Record actual SKU/VRAM/RAM/disk/binaries and limited scope; it does not pass RV008/M02. A reproduced native blocker may lead to an explicitly selected/retested WSL profile, never automatic configuration changes. Source-first users may defer both scopes as not_run without implementation failure.
- [ ] RV006 Run visible-data quality audit on the original Train partition, resolve required manual reviews and record accepted/pending/quarantined coverage. Verify train_1696 disposition and identical L1/L2 corpus; do not modify gold/source/reports or inspect hidden state. Dependencies: LL006–LL012, RV001.
- [ ] RV007 Explicitly prepare/export/token-audit accepted rows, validate hashes and exact split identity, and seal the core suite with P1/corpus/token evidence. Record filtered counts separately from raw 3,920/949 candidates; closed-loop Validation stays 309. Dependencies: RV002, RV006 and preparation source.

### L0/L1/L2 and local feasibility

- [ ] RV008 Run real pinned-Qwen LoRA resource probe on actual accepted worst-length rows with five or more updates, finite gradients, generation and save/reload. Record peak scopes, operating cap/headroom and outcome. No full training or resident ASR. Dependencies: RV003, RV005, RV007, LL027.
- [ ] RV009 If LoRA resources require it, explicitly choose and probe genuine NF4 QLoRA with update/generate/save/reload and the same headroom policy; freeze one common method for L1–L3. Otherwise record not_needed. If neither method passes, leave full-training gates blocked rather than silently lowering rank/context. Dependencies: RV008 and verified NF4 stack.
- [ ] RV010 Run explicit L0-G closed-loop evaluation and separately scoped teacher-forced diagnostics under frozen P1/limits. Save planner/tools latency, local metrics and fixed-ten traces without PhoWhisper or ASR caches. Apply the coverage contract: failed/timed-out sources score zero, never successful empty; any not_attempted makes the run partial. Prerequisites: RV001 Phase I scope, RV002, LL006/LL007 frozen membership/projection, LL021–LL024 and appropriate actual-model inference checks. Full accepted Fit corpus/RV007 is not a prerequisite to closed-loop L0-G; teacher-forced diagnostics additionally need their audited/token-valid Validation reference rows. Missing ASR or L3 cannot block G. State metrics remain null without trusted references.
- [ ] RV011 Verify ASR resources in separately scoped records: **export** (best fine-tuned PhoWhisper checkpoint, Fit training membership/selection/processor identity), **Validation cache** (A evaluation), and **Fit cache** (L3 only). Obtain caches from an explicitly run ASR workflow and validate current/history alignment/provenance; never use Validation predictions for training. The full-audio pilot needs the export and audio, not either transcript cache. A needs the export identity and fixed Validation cache, not Fit views. Gold-audio_text L1/L2 training and L0-G need none of these resources. Prerequisites: relevant LL035 validation and external ASR evidence; LL035/LL040 may be authored early without the rest of L3. Missing resources block only their dependent scope, with no pretrained substitution.
- [ ] RV012 Run the separate L0 full-audio pilot on all ten fixed cases on the local RTX 5070 Ti, with component/total timing, decision tokens/call counts and joint VRAM. Record locally_feasible/at_risk/resource_failed/blocked evidence and the pre-full-SFT review. Prerequisites: frozen P1/appropriate L0 model checks from RV010, RV011 **export scope** plus current/history audio, and LL032; transcript caches are unnecessary. If ASR is unavailable, leave the audio pilot blocked and require an explicit recorded unresolved-full-audio-latency decision before L1/L2, without making ASR their training input/dependency. Planner-only G timing is useful but cannot satisfy this pilot or A30 acceptance.
- [ ] RV013 Run L0-A teacher-forced diagnostics and independent full 309-source cached-A closed loop using the fixed Validation ASR cache. Apply the coverage contract and label timing as cached-transcript scope; failed sources remain scored, not_attempted makes coverage partial. Prerequisites: RV011 export/Validation-cache scopes, LL040 and appropriate baseline checks; no Fit noisy-view dependency.
- [ ] RV014 Manually run L1 from the pinned pretrained base on gold `audio_text` for the full common update budget. Preserve periodic/final checkpoints, NLL-selected candidate and training/failure evidence. Prerequisites: RV007, full RV008 qualification or explicitly selected/passed RV009 fallback, objective/tiny-model checks and LL028–LL034 training interfaces; record RV012 review **or** explicit operator decision to proceed with unresolved full-audio latency. No RV011/ASR/checkpoint/cache, LL042 or LL048 prerequisite. Missing ASR alone does not block clean training after all required data/resource gates pass; do not auto-run dependencies.
- [ ] RV015 Explicitly export/reload selected L1, then run G/A diagnostics and closed loop as separate invocations. Apply the coverage contract: all 309 attempted outcomes, including zero-scored failures/timeouts, are fully evaluated; not_attempted/invalid artifacts remain partial. Preserve fixed-case traces and actual-export identity, never substitute native scores. Prerequisites: RV014 and LL031 for export/G; RV011 export/Validation-cache scopes plus LL040 only for A. G can proceed while A is blocked.
- [ ] RV016 Manually run L2 independently from the same pretrained base on gold `audio_text`, with exact L1 clean corpus/order/budget and 1/2/1/2 weighting. Record actual visits/tokens, common qualified method and selected/final checkpoints; no L1 checkpoint warm-start. Prerequisites: the same data/resource/loss/latency-policy requirements as RV014, not L1 completion, ASR resources, LL042 or LL048. Runs remain manual and independent.
- [ ] RV017 Explicitly export/reload and evaluate actual selected L2 in separate G/A runs with the identical profile/checkpoint protocol as L1. Apply the coverage contract: failures/timeouts remain zero-scored in 309, fully evaluated is distinct from 309 successes, and any not_attempted remains partial. Prerequisites: RV016 and LL031 for export/G; RV011 export/Validation-cache scopes plus LL040 only for A. Do not block G on ASR.
- [ ] RV018 Use **LL024 minimal comparison only** to compare saved, fully evaluated compatible L0/L1/L2 G/A exports, select the L3 weighting policy and hash its evidence. Apply the existing A criterion/tie rule without requiring every source to succeed: scored failures stay in the denominator, while partial/missing/incompatible evidence blocks selection. A policy choice is not model promotion. Prerequisites: RV010, RV013, RV015, RV017 and LL024; **no LL042 or final-handoff dependency**. Compare never runs models or replay.

### L3, promotion and deployment

- [ ] RV019 Build and token-audit approved Fit noisy views with full strict-prefix evidence/manual decisions. Record all mandatory meaningful-noise/semantic-change/type/tool coverage and `limited_noisy_coverage`; WER or changed-string counts alone do not demonstrate useful augmentation. Keep `p_noisy=0.5` proposed, exclude pending/invalid views and preserve the clean corpus/gold amounts/IDs/calls. No gold+ASR concatenation or Validation-cache training. Prerequisites: RV007, RV011 export/**Fit-cache** scopes, LL035–LL038 and required Fit review; Validation cache is for A evaluation only.
- [ ] RV020 Manually run L3 independently with the saved RV018 policy, common budget/checkpoint selection and approved view mixing. Verify the bound resource evidence covers actual noisy lengths; explicitly reprobe if needed without launching training automatically. Save realized ratios/RNG states and coverage qualifiers. Dependencies: RV018, RV019 and matching resource/latency evidence.
- [ ] RV021 Explicitly export/reload and evaluate actual selected L3 in separate G/A protocols, retaining periodic/final checkpoints and L1/L2 rules. Apply the coverage contract: all 309 attempted outcomes can include scored failures/timeouts; any not_attempted/invalid outcomes make evaluation partial, not complete. No L3-only checkpoint search. Prerequisites: RV020, actual export checks and common profile; fixed Validation cache is required for A.
- [ ] RV022 Run model-free final eight-row comparison, fixed cases and paired uncertainty on actual exports using **LL042**. Compare fully evaluated compatible runs even when they contain correctly scored failures/timeouts; show partial/missing rows with null complete-run deltas/selection and reasons. Separately apply preregistered promotion gates, including specs §10.5's stricter success/no-timeout requirement: a scoreable failed run does not automatically become a Provisional/State-Verified Winner. Record provisional ranking and retain-L0/no-promoted-winner when gates are unmet; unavailable metrics stay null and limited coverage cannot support broad robustness claims. Prerequisites: saved evaluation outcomes and LL042, not a promise that every source succeeded.
- [ ] RV023 Perform a **reference feasibility investigation first**, independently of LL042: inspect organizer permission/runtime contracts and whether Train gold calls may be replayed in a separately invoked reference-only run with its own RuntimeFactory/process and one ToolEnv per source. Require documented isolation, input/runtime/catalog/canonicalization identity, replay/result consistency, coverage and trust acceptance; do not assume permission, determinism or gold consistency. No reference execution occurs as part of this checklist edit or any prediction run. Only if that route is validated and separately authorized, or another trusted evaluator is supplied, obtain/verify references and compute available state metrics; final ranking integration uses LL042 later. Never read/copy/parse `*_environment/state.json`, hash `label.final_state`, or create a second ToolEnv within a prediction run. Without a trusted reference, keep State Match null and any otherwise eligible winner provisional. Prerequisites: LL023 and rule/runtime evidence for investigation; trusted references and corresponding actual prediction artifacts for scoring. LL042 is not an investigation prerequisite.
- [ ] RV024 Run fresh-process offline export/container and actual full-audio evaluation checks with the selected deployed ASR/Qwen pair. Measure current/history ASR, total latency, joint VRAM, logical budgets, deterministic reruns and deadline/failure handling on the available host. Local success is still not A30 acceptance. Dependencies: LL041, LL043–LL044 and complete export/resources.
- [ ] RV025 Run final acceptance in the actual A30/offline Docker profile, with authoritative calls/hash, model/context budgets, 30-second sample supervision, full coverage and reproducibility evidence. If the host/container/supervisor is unavailable, leave deployment unverified. Dependencies: RV024 and final organizer/runtime infrastructure; no submission-ready claim from local probes or cached A.

## Acceptance gate coverage

Gate IDs and requirements are defined in [specs §13](specs.md#13-preflight-tests--acceptance-criteria).
All statuses initially mean not_run; this mapping is not acceptance evidence. LL
columns identify implementation/fixture delivery; RV columns identify relevant
execution records. A single run may support several gates, but each gate needs its
own result/reason. A failed RV attempt must never turn its gate into passed.

| Spec gate | Authoring tasks | Relevant execution evidence |
|---|---|---|
| D01 Split/labels | LL006, LL018 | RV001, RV006, RV007 |
| D02 Expansion | LL008, LL018 | RV001, RV006 |
| D03 Leakage sentinels | LL005, LL007–LL009, LL018 | RV001, RV006, RV007 |
| D04 Gold audit | LL010–LL012, LL018 | RV001, RV006 |
| D05 Token policy | LL016–LL019 | RV002, RV007, RV019 |
| D06 Three-level audit | LL009–LL012, LL018 | RV001, RV006, RV019 |
| P01 Shared rendering | LL014–LL015, LL019 | Scoped RV001, RV002 after P1 language/content decision |
| P02 Serialization | LL013, LL019 | RV001, RV002 |
| P03 Decoder agreement | LL013, LL017, LL019 | RV002 |
| P04 Loss mask | LL016, LL019, LL034 | RV001–RV003, RV007 |
| P05 Pinned template | LL014–LL017, LL019 | RV002; no freeze before exact P1 content/language and hashes are resolved |
| L01 Weighted loss | LL028, LL034 | RV001, RV003 |
| A01 Noisy rows | LL036, LL045 | RV001, RV019 |
| A02 Mixing/cache | LL035, LL037, LL040, LL045 | RV001, RV011, RV019–RV021 |
| A03 Noisy coverage | LL038, LL045 | RV001, RV019–RV022 |
| M01 Tiny real model | LL026–LL031, LL034 | RV003 |
| M02 Actual resources | LL026–LL027 | RV008, RV009 when needed, RV020 noisy-length verification |
| M03 Resume | LL029–LL030, LL034, LL037 | RV003 and separately selected actual-run resume checks |
| M04 Local compatibility | LL025–LL028, LL046 | RV004, RV005 kernel/early-smoke scopes, RV008–RV009 full qualification |
| S01 Checkpoint selection | LL029–LL031, LL034 | RV003, RV014–RV017, RV020–RV021 |
| E01 Evaluation boundary | LL021–LL022, LL034, LL040 | RV001, RV010, RV013, RV015, RV017, RV021 |
| E02 Metrics | LL020, LL023, LL034 | RV001 and saved real evaluation outcomes |
| E03 References | LL023, LL045; LL042 for final ranking only | Scoped RV001, RV023 investigation/trust evidence or explicit blocked reason |
| W01 Manual lifecycle | LL001, LL030, LL033–LL034, LL039 | RV001, RV003 and individual actual invocations |
| W02 Read-only compare | LL024, LL042, LL045 | RV001, RV018, RV022 |
| W03 Portability | LL003–LL005, LL046, early LL047; LL045/LL048 final review | Scoped RV001, RV004; no final-handoff prerequisite |
| X01 Export | LL031, LL041 | RV015, RV017, RV021, RV024 |
| X02 Submission | LL043–LL044, LL047–LL048 | RV024, RV025 |
| X03 Early latency | LL032–LL033, LL043 | RV012 |

For M03, author both controlled resume tests and an opt-in actual-model interruption/
resume check. Execute it as a separately recorded check when qualifying the target
stack, without extending a full run's 500-update budget or resuming across experiments.
RV001 references always mean the specific phase/test scope needed by the gate;
completing its Phase I scope does not pass later trainer/view/reporting checks.
RV005 early smoke cannot substitute for M02/RV008 worst-row qualification. RV011
export, Fit-cache and Validation-cache scopes are separate dependency records even
when their parent checkbox remains open for unfinished scopes.

## Ordering and readiness rules

### Authoring milestones and dependency flow

These are implementation milestones, not automatically executed commands. Preserve
all LL/RV IDs. Dependencies flow from shared contracts toward consumers; authored
code does not depend on its own future RV results. Resolve runtime choices before
freeze/run, while keeping unexecuted hardware work visibly not_run.

| Milestone | Authoring scope | Required predecessor / ordering note |
|---|---|---|
| Core infrastructure | LL001–LL006 | Existing repository contracts; strict config/paths/storage before consumers |
| Data/export/audit | LL007–LL012 + LL018 | Core; provide serializer/token-audit hooks, but do not seal preliminary exports before prompt contracts exist |
| Shared P1/tokenization | LL013–LL017 + LL019 | Visible input/audit schemas and existing decoder; implement canonical serializer before final export/token acceptance; exact language/content decision before freeze |
| L0 metrics/evaluation | LL020–LL024 | Core projection, P1/grammar and scoring fixtures; no L3/final-comparison/ASR prerequisite for G |
| GPU/model/loss | LL025–LL028 | Shared token/mask/config contracts; implement LL026 + LL028 minimum update helper before LL027 early training smoke, without requiring full LL029 trainer |
| L1/L2 trainer/export | LL029–LL034 | Data/P1, objective/model interfaces and basic evaluator; complete checkpoint/export and controlled tests before full-training qualification |
| L3 cache/augmentation | LL035–LL040 + LL045 | Shared corpus/P1 and cache schemas; LL035/LL040 may be pulled forward for A without LL036–LL039 or any L3 training |
| Final reporting/deployment | LL041–LL044 | Basic LL031 export and LL024 comparison; LL042 extends minimal comparison only after RV018 can already select policy |
| Portable setup/docs | LL046–LL047 throughout | Minimum inventory/setup before RV004; no dependency on LL048 or measured experiment success |
| Final source handoff | LL048 | LL001–LL047 authored/reviewed with explicit unrun/blocked evidence; not a prerequisite to earlier transfer/probes/training |

The non-numeric LL028-before-LL027 smoke-helper ordering reflects the actual
objective/update dependency. It does not change task IDs or the phase scopes.
Early data export can validate shape/risk and hold draft identities; final rendering,
token acceptance and immutable corpus sealing wait for the shared contracts, not
the reverse. This avoids a data-export/prompt-freeze cycle.

Execution branches after authored contracts are:

```text
Phase I code -> RV001 Phase I + RV002 -> reference/data audit -> RV006/RV007
LL003–LL006 + LL046 + minimum LL047 -> RV004
RV004 + LL025 -> RV005 kernel checks
RV005 kernels + LL026/LL028/LL027 smoke + verified masks -> RV005 early smoke
Full trainer/test source + RV003 + RV005 + RV007 -> RV008 [or RV009 fallback]
Frozen P1 + G input/model/evaluator checks -> RV010 L0-G (no ASR/L3)
RV011 export + real audio + L0 model/P1 -> RV012 full-audio pilot
RV007 + full resource/loss checks + (pilot review OR unresolved-latency decision)
  -> RV014 L1 / RV016 L2 independently (no ASR input)
RV011 Validation cache + LL040 -> A evaluation for each available export
Saved fully evaluated L0/L1/L2 G/A + LL024 -> RV018 L3 policy
RV011 Fit cache + audits -> RV019 approved noisy views
RV018 + RV019 + qualified common training path -> RV020/RV021 L3
Saved evaluations + LL042 -> RV022 final comparison/promotion review
LL023 + rule/runtime evidence -> RV023 reference investigation (independent branch)
Trusted references, if validated/authorized -> state scoring/ranking integration
Actual exports + full audio -> RV024 -> RV025 actual A30 acceptance
```

An early smoke may use declared short/long Fit-only or synthetic structural fixtures;
it must record which, never treat a handpicked prompt as actual longest accepted
corpus evidence, and never change the configured rank/context/dataset to hide OOM.
If LoRA fails, choose/record NF4 fallback explicitly and still require full RV009
qualification before training. All hardware checks may be postponed to the later
local GPU handoff when the user's chosen workflow is to finish source first.

### Readiness by evidence level

| Milestone | Required evidence / remaining limitations |
|---|---|
| Reviewable Phase I | LL001–LL020 authored; RV001 Phase I can run without LL034/LL045/GPU/ASR; exact P1 decision and actual corpus/token checks may still be pending |
| Correct executed L0-G | Relevant Phase I checks plus baseline evaluator/local model evidence; ASR, L3 and trusted state may remain blocked |
| Early GPU feasibility | RV004/RV005 limited model/update/short-long-memory evidence; no final trainer/handoff dependency and no full-fit guarantee |
| Full L1/L2 execution | Audited/token-frozen common gold-text corpus, objective/trainer/checkpoint tests, full target-GPU method qualification and pilot review or explicit unresolved-audio-latency decision; no ASR/LL042/LL048 prerequisite |
| L3 execution | Compatible L1/L2 G/A policy, selected-ASR Fit cache, approved full-prefix rows, noise coverage and matching resource evidence |
| Implementation handoff | LL001–LL048 authored/reviewed; RV/gate ledger openly records unrun/blocked items, resource inventory and manual commands |
| Training complete | Each trained experiment has its full declared updates and durable checkpoints, not merely scripts or a passing probe |
| Fully evaluated/comparable | All 309 attempted IDs have valid outcomes, no not_attempted; failures/timeouts remain scoreable with correct zero penalties and shared profiles |
| Candidate promotion | Actual exported-checkpoint results plus stricter preregistered specs §10.5 success/no-timeout and other gates; provisional if state trust is absent |
| Submission ready | Actual offline A30/full-audio/supervision acceptance; neither training success nor State-Verified ranking substitutes for it |

### Open decisions and document alignment

- **P1_LANGUAGE_ALIGNMENT:** specs §4.2 currently says to implement/test/freeze the
  English draft; the reviewed runtime is Vietnamese `lifemate-react-v4`, and the
  current review prefers minimal Vietnamese changes unless another version is
  explicitly settled. Record exact selected text/language and reconcile that
  instruction through an explicit decision before P1 freeze/L0. Parameterized
  renderer/data/test authoring can start now. Neither prompt language is silently
  declared selected by this edit; specs/plan/runtime remain unchanged.
- **Coverage versus promotion:** specs §10.3 counts failures in the 309 denominator,
  while §10.5 proposes 309 successful completions/no timeouts for promotion. Use
  the distinct evaluated/completion/promotion definitions above. The plan's phrases
  about complete comparable results must not be interpreted as requiring zero
  failures merely to compare runs or select an L3 weighting policy.
- **State-reference permission/trust:** organizer/runtime support for a separate
  reference-only gold replay is unverified. LL023/RV023 investigate it without
  executing replay or promising a trusted evaluator. No hidden-state access or
  in-prediction second environment is permitted; absent trust leaves State Match
  null and winner verification provisional.
- **Host/resources:** exact RTX 5070 Ti SKU/VRAM/Windows kernels, locks, real worst-row
  LoRA/NF4 fit, selected-ASR provenance/caches, manual-review capacity, meaningful
  noisy coverage and A30 hard-deadline acceptance still need actual evidence.
  These do not require redesigning the agreed architecture or adding experiments.

The plan's broad LL046–LL048 handoff grouping is a final-delivery description,
not an early RV004 prerequisite. This checklist makes the minimal transfer and
comparison dependencies explicit without modifying plan.md or specs.md.

The receiving teammate records measured evidence in ignored run artifacts and links
the concise status in the team's issue/PR workflow. Do not commit raw data, weights,
transcript caches, hidden app state or full traces. Do not update old JSON review
templates to suggest experiments have run. Any change to architecture, split,
prompt contract after freeze, corpus or shared comparison controls requires the
explicit new-policy/new-suite handling defined in the specification.
