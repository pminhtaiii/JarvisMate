# Tasks: Native Qwen3-4B Next-Action SFT

**Project:** JarvisMate / LifeMate 2026. **Date:** 2026-11-01.
**Status:** planned; all implementation and execution items below remain open.
**References:** [specs.md](specs.md), version 1.3, and [plan.md](plan.md).
The specification is authoritative. New paths/commands are future deliverables.
This revision adopts the approved native Qwen model-facing protocol in the design.
It selects Vietnamese P1/final wording and refines specs/plan/tasks only, not
runtime/source or executed/hash acceptance. Existing LL/RV checkboxes remain open.
No main merge, PR reopening or experiment run is requested.

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
  Minimal decoder/fixture authoring precedes its CPU proof; that passed proof gates
  full exporter integration, P1 acceptance and native L0, not its own prerequisites.
  Hardware RV items may remain not_run until all source is transferred; that is not an
  implementation failure. A staged RV record must identify its scope explicitly.

## Native protocol and migration scope

Audio -> selected fine-tuned PhoWhisper-large -> pinned Qwen native messages/tools
-> at most one native tool call -> Python -> ToolEnv -> actual role=tool result
-> next call or complete ordinary assistant final turn. Keep one planner, iterative
Next-Action, no decomposition/explicit CoT and independent L0–L3 initialization.

Custom action/finish objects are allowed only at the internal Python executor
boundary. They are not SFT targets, model-facing assistant messages or native JSON
inside tool_call tags. No synthetic finish function or forced tool-call-only branch.
All four experiments need a fresh native suite and native L0 with new protocol,
renderer/catalog-adapter/parser/decoder/terminal/template hashes. Do not reuse
custom-format token caches, accepted masks, checkpoints or comparison identities.
Original dataset/split, the same pinned pretrained Qwen/tokenizer files and
compatible ASR assets may be reused after verification; native acceptance is new.

The pinned template, source migration audit and mandatory native contracts are in
[specs §4](specs.md#4-native-qwen-prompt-and-decision-contract-p1-native) and
[specs §2.4](specs.md#24-current-source-migration-audit-no-source-changes-in-this-task).
The current branch has no llm_training implementation; existing custom runtime
needs the listed migration. Historical review reports are not native acceptance.

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
- Hard validity gates are separate from performance selection (specs §10.5).
  A fully evaluated failed/timed-out run may be compared and selected under its
  preregistered nonzero tolerances; one timeout or one lost minority TP is not an
  automatic whole-run veto. Freeze primary metric, controls, regression tolerances,
  supports/null handling and ties before model outcomes; no post-hoc waivers.
  Actual offline A30/submission acceptance remains a separate strict requirement.

## Phase I — Data & Prompt Foundation

First author LL001–LL005 plus the minimal LL007 catalog adapter, LL013–LL017
native codec/Vietnamese P1/token helpers and LL019 POC fixtures. Execute the explicit
CPU RV002/decoder_poc before **full** LL008–LL012 exporter integration, P1 acceptance
freeze or native L0. The proof needs no full exporter, LL018 data suite, sealed suite,
ASR/weights or GPU. Then complete LL006–LL012 data/audit, remaining shared renderer/
mask work and LL018–LL020 fixtures. Independent pure work may proceed while proof
resources are blocked; do not claim full integration acceptance or use a fallback.

- [ ] LL001 Create lazy llm_training CLI/package and model-free status, with an explicit early CPU `token-audit --scope decoder-poc --config ... --output-root ...` path that needs no full exporter/sealed suite/weights/GPU. Keep other model-free commands usable without model libraries, reject L0 training/automatic dependencies/all-experiment chains and preserve import side-effect tests.
- [ ] LL002 Implement strict native configs/artifacts: pinned Qwen, selected Vietnamese P1 `lifemate-native-p1-vi-v1`, decoder `lifemate-qwen-native-single-v2`, exact final policy `lifemate-native-final-vi-v1`, rejection schema, native row v2 and proof bindings. Add preregistered selection-policy schema/values/support/null/tie rules from specs §10.5. Reject unknown/floating/mixed-format identities; preserve split/seeds/experiments/weights/limits. Seal selection policy before the first model outcome, independently of completed runs.
- [ ] LL003 Implement project-root path resolution and CLI overrides for data/model/ASR/split/cache/output/suite paths. Use relative defaults, contained writable roots and visible-path guards. Handle spaces/non-ASCII paths and reject traversal; exclude machine-specific absolute paths from portable content identity.
- [ ] LL004 Implement `storage.py` stable hashes, atomic writes, immutable core suite sealing and unique run/export/report directories. Record source revision/dirty-patch identity, status and error provenance; do not overwrite durable checkpoints or scan hidden environment files.
- [ ] LL005 Implement model-free `verify-resources` and `preflight`: phase-specific inventory, visible source/model-file/cache hashes and missing-resource reports without model-library imports. Distinguish source, data/audio, weights, tokenizer, ASR exports, caches, split, environment locks and generated artifacts; optional ASR must not block clean preparation.
- [ ] LL006 Validate the existing grouped seed-42 manifest against exact specs §2 source/catalog/split hashes, membership and group disjointness. Map manifest train to Fit; preserve 1,236/309 sources and Fit smoke IDs. Missing/mismatched identity fails rather than resplitting.
- [ ] LL007 Author the minimal pure exact catalog-to-functions adapter first for the early CPU proof; then integrate full visible/history projection after that proof. Preserve original names/descriptions/schemas/extensions/ordering/sys and hash-bound metadata. Implement specs §4.3.1 historical mapping for text-only, text+single/multiple calls and ordered results without replay/guessed interleaving. Missing/mismatched/ambiguous/non-representable history stays unsupported/needs_review; no invented results/current targets or full inference preflight.
- [ ] LL008 After a matching passed CPU decoder proof, integrate full native next-action expansion with exact gold/historical pairing and strict j<k messages. One native assistant call or exact ordinary-final target per row; no current/future result, custom action output or extra final after terminal successful ask. Preserve values/order/source membership and all four semantic types. Minimal fixture construction for the proof is independent of this full exporter.
- [ ] LL009 Implement Level 1 native-aware deterministic audit: visible JSON/schema/tool eligibility, original gold pairing, historical native projection, strict prefixes, terminal structure, lossless catalog adapter, native target serialization and leakage. Use pure organizer validation plus tested decoder projection; x-one-of means at least one complete group. Expose CPU token-audit hooks without loading tokenizer/weights during export. No ToolEnv or hidden-state reads.
- [ ] LL010 Implement Level 2 semantic risk and Level 3 recorded manual review with stable reasons/evidence paths/original-target hash under the native row schema. Screen amount/currency, IDs/entities, phone/time, negation/correction, branches, grounding and downstream final; serialization migration never certifies semantics. Critical/ambiguous rows require review; unresolved rows stay needs_review. Preserve original labels/results and full-prefix evidence.
- [ ] LL011 Preserve dependent-prefix/final quarantine: train_1696 k=2 and dependent final k=3 are excluded without label/ID repair. Earlier k=0/1 need independent audit. A native wrapper or EOS cannot make an unsupported gold call/finish valid; never splice rejected calls/results out of a later row.
- [ ] LL012 Write native row/audit/proof-bound artifacts atomically after early proof and data checks, with complete messages/tools, target, protocol/P1/adapter/codec/decoder/terminal/rejection/history identities and token/quality statuses. Preserve L1/L2 clean corpus/309 closed-loop sources; quarantine unsupported historical pairing/order and dependent prefixes. No fabricated native acceptance or reuse of custom masks. Model-free prepare verifies supplied proof metadata, never runs the proof.
- [ ] LL013 Author minimal native catalog/assistant serializer plus wrapper/schema/final decoder-composition interfaces for POC before full exporter. Use pinned-template-rendered bytes, name-bound argument parsers, true at-least-one-group x-one-of and a union with exact ordinary final; no forced initial tool tag/custom envelope/first-call extraction. Preserve argument values/order/escaping/Unicode/phone zeros and use real catalog fixtures or labeled controlled schemas.
- [ ] LL014 Implement the selected Vietnamese native P1 text from specs §4.2, retaining valid lifemate-react-v4 business rules but removing every custom-output instruction. Exact final policy is NFC `Đã kết thúc.` with no extra whitespace/content and one assistant EOS; it is not a success certificate or fake tool. Share native tools/messages/history rendering across all paths; preserve pinned template, supplied text/calls/results and no-thinking behavior. Record design-selected versions now, accepted hashes only after proof/regressions; no language superiority claim.
- [ ] LL015 Author a minimal pure native parser/constraint for the early CPU proof, then migrate LocalPlanner/agent after proof. Require raw IDs, real EOS/stop evidence and whole-response parse; reject malformed/multiple/truncated/unknown/empty finals without dispatch or first-call salvage. Implement canonical `lifemate-native-rejection-v1` user records: step/code/Vietnamese message, UTF-8-bounded raw preview/byte metadata/stop/eos/repairability. Preserve prior actual call/results, never fake role=tool or replay an invalid proposal. Allow at most two total repair generations within existing step/time bounds; terminal cuts/internal errors and uncertain mutations never implicitly retry. Preserve pure schema prechecks plus authoritative env.call rejection logging; no custom/unconstrained fallback.
- [ ] LL016 Author minimal shared tokenizer suffix/mask helpers for CPU proof before full exporter, then complete native full-template supervision. Exact inference prefix plus one native assistant call/final/EOS target; mask headers/system/tools/user/history/previous assistant/tool/padding. No independent-fragment assumptions, duplicated BOS/EOS or normalization of malformed/whitespace output into the exact final.
- [ ] LL017 Implement the early suite-independent CPU decoder-poc scope first, using local pinned tokenizer/LMFE/minimal fixtures only. After it passes, complete clean/asr token-audit, exact prefix/masks/EOS/flag checks, native lengths and P1/terminal/hash freeze. Full exporter/P1 freeze/native L0 require matching proof; the proof requires no corpus export, GPU or sealed suite. Relevant helper/backend/policy changes invalidate proof bindings; no automatic proof jobs or accepted-hash claims before real checks.
- [ ] LL018 Author pure data/audit/history fixtures after the proof-backed exporter is integrated: split/hash drift, strict j<k/no label leakage, both final types, terminal ask and train_1696 dependencies. Real Fit history anchors: train_0008/history[1], train_0069/history[5]/[9]; verify text+multi-call/order/transcripts without replay or historical targets. Missing/mismatched/order-conflict cases are explicitly controlled mutations, unresolved ones unsupported. No environments/weights/hidden state in tests.
- [ ] LL019 Author an early P03 CPU decoder POC fixture subset first, with all nine specs §4.4.1 groups and actual pinned-tokenizer token walks/EOS gating/backend-error injection. It must not import the full exporter or depend on LL008–LL012/LL018/RV007. Later extend full prompt/codec/tokenization regressions for Vietnamese P1/exact final, real-history shapes, canonical rejection records, malformed/name/multi/missing-EOS/repeated errors and repair after successful observations. Keep pure/CPU-tokenizer/model scopes separate; failed proof records blocker, never fallback.
- [ ] LL020 Implement pure metrics/fixtures separating native-format/EOS validity from normalized semantic tool-name/arguments/ask/initial-final/post-final accuracy, multi-step behavior and trusted final state. Never use wrapper exact-text match as semantic accuracy. Preserve maximum one-to-one fuzzy/duplicate matching, failure-aware empty-gold scoring, strict ask ordered params, four classes/undefined supports and the fixed ten Validation-only diagnostic IDs.

**Phase I authored exit:** LL001–LL020 deliver reviewable data/P1/fixture code.
**Executed exit:** relevant RV001/RV002/RV006/RV007 evidence and gates below; no
checkbox here establishes 4B training feasibility or model quality.

## Phase II — L0/L1/L2

Start a correct L0-G path after Phase I core contracts and LL021–LL024; it need not
wait for L3, exhaustive reporting automation or trusted state references. Trainer
authoring can proceed independently of access to the eventual GPU host. Full
training needs actual data/token/resource evidence and the latency review policy.

- [ ] LL021 Implement native closed-loop G/A runner with one ToolEnv/source, actual observations/log/hash, parsed internal decisions and coverage invariants. Migrate native rejection-feedback handling without losing successful prefixes or duplicating mutations; fail missing-EOS/truncated/uncertain execution without invented tool results. G needs no ASR. Record format/EOS/rejection, semantic outcomes, failures/timeouts and scope-aware timings separately; these measured failures do not automatically invalidate whole-run comparison.
- [ ] LL022 Implement native teacher-forced G/A diagnostics on exact gold strict-prefix messages/tools, completion-mean unweighted NLL, semantic normalized next-action/argument/type supports and separate native validity. Score finals by parsed native terminal policy/current decision prefix, not historical call count or wrapper bytes. Keep oracle-prefix ASR diagnostics distinct from actual closed loop, retain unusable-reference denominators and no hidden filtering of hard A cases.
- [ ] LL023 Connect all native report/prediction schemas and specs §10.3 metrics, including raw-format versus semantic/multi-step/state layers, failure=0 coverage and authoritative env logs. Investigate separate reference-only Train-gold replay permission/trust independently of inference/comparison; document dataset/runtime/catalog/canonicalization identities and consistency before any authorized replay. Never hash label.final_state, read hidden state or create a second ToolEnv in a prediction run. Missing trusted references keep state metrics null and ungated scoring available.
- [ ] LL024 Implement minimal model-free native L0/L1/L2 G/A comparison and RV018 weighting selection with separate hard validity versus preregistered performance policy. Bind protocol/P1/decoder/proof/terminal/export/evaluator/selection-policy identities; reject leakage/partial/incompatible artifacts, not every failed source. Use primary state-gated A if trusted, otherwise provisional ungated F1; apply predeclared minority/critical/error/timeout/G/latency tolerances and null handling. One timeout or lost TP is not an automatic veto. L2 versus L1 ties to L1; no post-hoc waiver, LL042/bootstrap/model/replay dependency.
- [ ] LL025 Implement `resources.py` explicit GPU preflight for actual local RTX 5070 Ti: SKU/physical/free VRAM in bytes/GB/GiB, RAM/disk, Windows/Python/driver/CUDA wheel, architecture coverage and allocation/matmul/backward. Keep CUDA-runtime/toolkit labels distinct; record actual kernels/precision. Document conditional WSL only for reproduced native blockers.
- [ ] LL026 Implement `models.py` pinned local Qwen/config/tokenizer loading and LoRA scope assertions: q/k/v/o projections in every decoder self-attention layer, rank/alpha/dropout from config, base frozen and only adapter A/B trainable. Implement genuine NF4/double-quantization fallback with k-bit preparation and explicit version/build validation; no silent int8 or CPU substitution.
- [ ] LL027 Implement separate early-smoke and full resource-probe scopes for the new native profile. Early scope after LL026/LL028 plus native-mask code tests model/tokenizer loading, LoRA, forward/backward, one update and short/long native tools prompts. Full RV008 scope uses actual accepted native worst lengths/targets and at least five updates, real accumulation, constrained native generation/EOS, save/reload and measured headroom. Do not reuse custom-format probes. NF4 is explicit fallback with its own qualification; no automatic rank/context/data/method change or resident ASR.
- [ ] LL028 Implement `losses.py` exact specs §7.1 objective: row completion mean including EOS, global Fit mu_w, uniform base visits, per-window (w_i/mu_w)*ell_i/m and actual partial m. Prevent double division or micro-batch weight cancellation; no weighted sampling/oversampling. Author analytic loss/gradient fixtures including relative ask weight 2.
- [ ] LL029 Implement explicit fixed-budget trainer: independent pretrained initialization, deterministic uniform epoch shuffling, 500 updates/16 accumulated rows, AdamW/schedule/clipping/checkpointing and probed precision. Log actual tokens/type visits and finite/update failures. Use common clean-G unweighted teacher-forced NLL every 100 updates/final; no experiment-specific early stopping or implicit extra phases.
- [ ] LL030 Implement `checkpoints.py` durable periodic/final checkpoints and best/latest pointers; save optimizer/scheduler/scaler, all RNGs, sampler/view state, identities, completed/remaining budget and NLL selection history. Earliest-step NLL tie, retained final step, symmetric preregistered secondary step analyses only. Explicit compatible resume rejects corrupt/probe/cross-experiment/cross-method checkpoints.
- [ ] LL031 Implement basic selected-adapter export/verify-export for L1/L2 with complete merged FP16 local weights/tokenizer/pinned native template and new native-format contract. Verify semantic native generation/EOS/parser/reload and logical counts before actual-export G/A comparison. Record unmerged-NF4 versus merged-FP16 differences; export failure never substitutes old custom/native training scores.
- [ ] LL032 Implement an explicit native L0 full-audio pilot on the fixed ten cases. Measure current/history ASR, tools-injected native prompt/target tokens, Qwen invocations/prefill/decode where available, ToolEnv/total time and joint VRAM/offload. New native profile requires new timing/resource evidence; cached-ASR/custom L0 timing is not native end-to-end or A30 acceptance. Never auto-trigger from setup/prepare/train.
- [ ] LL033 Add common/native L0/L1/L2 configs and thin manual wrappers with new protocol/adapter/parser/decoder/terminal identities and independent initialization. Require matching native token/full-resource evidence before training; no custom-profile reuse or implicit probe/export/evaluation. Gold audio_text L1/L2 need no ASR after required data/resource gates and recorded audio-pilot review or explicit unresolved-latency decision. One experiment/phase/mode per invocation, explicit resume only.
- [ ] LL034 Author trainer/checkpoint/native-evaluation/manual fixtures for weighted loss, native target masks, resume/NLL selection and source/contract integrity. Include canonical feedback no-fake-tool cases, preserved history/successful prefix, total repair cap, terminal cuts and exactly-one-environment/logging; score fully evaluated failures under a frozen selection policy. Tiny-Qwen tests are explicitly separate and download-free; no actual-GPU prerequisite for Phase I.

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
- [ ] LL039 Add independent native L3 config/wrapper/trainer integration bound to a saved compatible native L1/L2 policy report. Same native renderer/parser/decoder/terminal/shared corpus/objective/budget; approved Fit noisy views rerender to native messages. Do not warm-start custom or L1/L2 adapters, edit sealed suite, auto-create ASR data or treat absent native evidence as success.
- [ ] LL040 Implement the cache-backed ASR adapter for A evaluation using the existing ASR protocol, source/turn/audio/checkpoint validation and no reference access/gold fallback. Preserve complete-sample ownership and supplied assistant history. Cache-backed timing is planner/tools scope; absent/mismatched turns fail explicitly.
- [ ] LL041 Complete offline native export/budget hooks: complete pinned tokenizer/template/format contract, logical merged/unmerged/quantized counts, fresh network-disabled native generation/parse/EOS, target-host repeatability and missing-asset failure cases. No custom-profile export equivalence claim; training infrastructure remains outside deployed model count.
- [ ] LL042 Extend LL024 to final artifact-only eight-row native comparisons/fixed cases/paired uncertainty. Enforce hard protocol/leakage/identity/export/evaluator/coverage validity separately from frozen performance tolerances and tie rules in specs §10.5; fully evaluated failures/timeouts remain comparable and potentially selectable. Compare promotion to native L0, retain L0 without qualifying gain, rank passing SFT ties L1/L2/L3. Disclose critical/precision/latency missing supports, state trust and no A30 acceptance; never infer readiness from final text or waive regressions post hoc.
- [ ] LL043 Implement explicitly invoked full-audio evaluation integration with selected ASR/Qwen, actual export identities, complete current/history timing, authoritative results, failure accounting and joint-memory measurements. Measure initialization/warmup separately; no cached-A substitution for full audio or automatic ASR training/export selection.
- [ ] LL044 Define A30/Docker acceptance hooks and the interface to existing process supervision: offline assets, <5B LLM/<6B total, <=16384 context, hard sample deadlines, cleanup and failure/output accounting. Reuse the submission boundary; disclose missing supervisor/container support as a dependency rather than treating cooperative timeout as solved or building unrelated infrastructure.
- [ ] LL045 Author native ASR-view/report/export/portability regressions: strict-prefix native messages after noisy text replacement, cache separation/certificates, RNG/resume, meaningful-noise coverage, native comparison/export identity and no fake state/metric/winner. Preserve p_noisy=.5 as proposed and limited_noisy_coverage; actual-model/organizer/GPU tests remain separately enabled.

## Cross-phase delivery — Portability & Runbook

Start these during Phase I; complete them before claiming an implementation handoff.

- [ ] LL046 Author separate training/QLoRA dependency inputs, a platform-specific full hashed Windows/Python/CUDA lock-generation/verification procedure, resource manifest and optional matching offline-wheelhouse instructions. Pin candidate versions/builds from specs §9, with observed compatibility status separate. Never mark an unverified lock as tested or copy a venv; add a separate Linux lock only if the conditional profile is actually needed.
- [ ] LL047 Write incremental README/RUNBOOK for CPU POC-first authoring, exact Vietnamese P1/final/history/rejection fixtures, new proof/version/policy bindings and manual operations. Minimal setup/resources precede transfer; early token-audit needs only local tokenizer/backend fixtures, no exporter/suite/weights. Full exporter/freeze/L0 follow a passed proof. Preserve two-machine portability, VRAM/RAM distinction, explicit GPU probes/experiments/resume and independent A30 acceptance; no source/runtime modification in documentation stage.
- [ ] LL048 Perform the **final implementation review/handoff** after LL001–LL047 authoring, not as a prerequisite to RV004/RV005/RV008 or L1/L2. Prepare the gate ledger, source revision, resource locations/hashes, exact manual commands and unresolved dependencies. Review authored portability checks and record actual relocation evidence if available; hardware RV tasks may all remain not_run when the user chooses source-first delivery. Verify ignored data/weights/caches and bounded logs; do not claim unrun gates or modify old reports into results.

## Execution checklist — Receiving machine and acceptance evidence

These are future manual tasks, not instructions to run now. RV IDs identify evidence
collection, while the acceptance ledger below determines whether each gate passed.
Source authoring may finish even when execution dependencies are unavailable.

### CPU, data and pinned-tokenizer evidence

- [ ] RV001 Run focused pure/controlled Phase I tests and relevant existing pipeline regressions, proving model-free CLI/imports do not load model libraries, weights, ToolEnv or CUDA implicitly. **Phase I prerequisites: LL018–LL020 and their Phase I code only; no LL034/LL045 dependency.** This Phase I run may complete RV001's initial scope. Append separately identified Phase II/III test-run records when LL034/LL045 are authored, with exact revision/test selection/results and gate scope; an earlier Phase I pass cannot stand for those later checks. Never overwrite earlier evidence or wait for later phases to test Phase I.
- [ ] RV002 Collect two explicit CPU scopes with local pinned tokenizer/LMFE, never weights/inference/GPU: **decoder_poc first**, then full render/mask/history/feedback regressions later. Early prerequisites are minimal LL001–LL005, catalog portion LL007, prototype LL013–LL017 and LL019 POC fixtures only; no LL008–LL012 full exporter, LL018 full suite, RV001 full Phase I or RV007. Token-walk all nine specs §4.4.1 cases plus backend-error injection, ordinary final initially with tools, stop/EOS boundaries and schema alternatives. Save passed/failed/blocked proof with exact helper/backend/P1/terminal identities before full exporter integration/P1 freeze/native L0; do not assume reachability means pretrained quality. Later scopes extend evidence without overwriting it. A failed composition blocks, never switches policy.
- [ ] RV003 Run separately enabled random tiny-Qwen forward/backward/update/save/reload and interruption/resume tests. Verify only adapters update, objective/masks and deterministic remaining-budget behavior. No checkpoint downloads; this does not establish actual 4B memory fit. Dependencies: LL026–LL031, LL034.
- [ ] RV004 On the receiving local machine verify transferred source, visible dataset/catalog/split, local model/tokenizer and phase-required resource inventory. Recreate the venv from the correct platform lock and record relocation/paths-with-spaces checks; never copy the authoring venv. **Prerequisites: LL003–LL006, LL046 and only LL047's minimum setup/resource-inventory section. LL048 and the final runbook are not prerequisites.** Verify optional ASR/caches only for requesting phases. An early transfer may carry the minimum viable training path; final source delivery may occur later without Python path edits.
- [ ] RV005 Execute explicitly selected actual-device checks on the local RTX 5070 Ti, with scoped records: first kernel/platform preflight (LL025 + RV004), then early training feasibility when LL026/LL028 and LL027's small probe path are authored and local token-mask fixtures are verified. Early smoke checks model/tokenizer load, LoRA injection, masked forward/backward, one optimizer update and short/long-prompt memory; explicitly probe genuine NF4 if LoRA fails and the operator selects that fallback. No LL029–LL034, RV003, sealed worst-corpus qualification or LL048 prerequisite for this early smoke. Record actual SKU/VRAM/RAM/disk/binaries and limited scope; it does not pass RV008/M02. A reproduced native blocker may lead to an explicitly selected/retested WSL profile, never automatic configuration changes. Source-first users may defer both scopes as not_run without implementation failure.
- [ ] RV006 Run visible-data quality audit on the original Train partition, resolve required manual reviews and record accepted/pending/quarantined coverage. Verify train_1696 disposition and identical L1/L2 corpus; do not modify gold/source/reports or inspect hidden state. Dependencies: LL006–LL012, RV001.
- [ ] RV007 After matching passed RV002/decoder_poc and data audits, explicitly prepare/export/token-audit the native corpus and seal proof/P1/history/rejection/terminal/row identities with full render/mask acceptance. Preserve membership/raw versus accepted counts and 309 expected sources; no custom-mask reuse. Seal the selection-policy record with concrete tolerances/support/null/ties before RV010 or any model outcomes; prepare never auto-runs proof/tokenizer/model jobs. Prerequisites: early proof, required later RV002 regressions, RV006 and exporter source.

### L0/L1/L2 and local feasibility

- [ ] RV008 Run full pinned-Qwen LoRA qualification on actual accepted native worst-length prompts/targets with five or more updates, real accumulation, finite gradients, constrained native tool/final/EOS generation and save/reload. Capture actual headroom/memory scope; old custom resource evidence or early smoke does not qualify. No full training/resident ASR. Prerequisites: RV003, RV005, RV007 and LL027.
- [ ] RV009 If LoRA resources require it, explicitly choose and probe genuine NF4 QLoRA with update/generate/save/reload and the same headroom policy; freeze one common method for L1–L3. Otherwise record not_needed. If neither method passes, leave full-training gates blocked rather than silently lowering rank/context. Dependencies: RV008 and verified NF4 stack.
- [ ] RV010 Run fresh native L0-G only after matching CPU proof/P1 acceptance and preregistered selection policy; teacher-forced diagnostics are separate. Save native validity/EOS/semantic/confusion/error/timing outcomes and fixed-ten traces without ASR. Full coverage allows scored failures/timeouts; not_attempted is partial. Prerequisites: relevant RV001/early+full RV002 scopes, LL006/LL007 membership/projection, LL021–LL024 and local model checks; closed-loop G needs no full Fit export/RV007, but must seal equivalent P1/proof/selection metadata first. Reference diagnostics require their audited rows; no custom L0 reuse or fabricated state metrics.
- [ ] RV011 Verify ASR resources in separately scoped records: **export** (best fine-tuned PhoWhisper checkpoint, Fit training membership/selection/processor identity), **Validation cache** (A evaluation), and **Fit cache** (L3 only). Obtain caches from an explicitly run ASR workflow and validate current/history alignment/provenance; never use Validation predictions for training. The full-audio pilot needs the export and audio, not either transcript cache. A needs the export identity and fixed Validation cache, not Fit views. Gold-audio_text L1/L2 training and L0-G need none of these resources. Prerequisites: relevant LL035 validation and external ASR evidence; LL035/LL040 may be authored early without the rest of L3. Missing resources block only their dependent scope, with no pretrained substitution.
- [ ] RV012 Run the explicitly selected native L0 full-audio pilot on all ten fixed cases with selected ASR, native component/token/call timing and joint VRAM. Reaudit native prompt growth and decoder/final overhead; custom or cached timings cannot qualify. Prerequisites: frozen native P1/model checks from RV010, RV011 export plus audio and LL032, not transcript caches. Missing ASR leaves audio feasibility unresolved; L1/L2 may proceed only with required data/resources and explicit recorded unresolved-latency decision, never automatic ASR jobs.
- [ ] RV013 Run L0-A teacher-forced diagnostics and independent full 309-source cached-A closed loop using the fixed Validation ASR cache. Apply the coverage contract and label timing as cached-transcript scope; failed sources remain scored, not_attempted makes coverage partial. Prerequisites: RV011 export/Validation-cache scopes, LL040 and appropriate baseline checks; no Fit noisy-view dependency.
- [ ] RV014 Manually train native L1 independently from the pinned pretrained Qwen on gold audio_text for the full common budget. Require new native RV007, full matching RV008 or passed RV009 fallback, objective/tiny-model checks and LL028–LL034; record completed audio-pilot review or explicit unresolved-latency operator decision. No ASR snapshot/cache, LL042 or LL048 prerequisite; Qwen snapshot/tokenizer are still required. Save periodic/final/NLL-selected checkpoints; never resume old custom adapters or auto-run dependencies.
- [ ] RV015 Explicitly export/reload the actual selected native L1 checkpoint and evaluate separate G/A diagnostics/closed loop under identical native controls. Retain all 309 outcomes including scored failures/timeouts, fixed-ten traces and raw format/EOS versus semantic metrics; not_attempted means partial. G needs no ASR; A additionally needs fixed RV011 export/Validation-cache and LL040. No custom profile or unmerged-score substitution. Prerequisites: RV014 and LL031.
- [ ] RV016 Manually train native L2 independently from the same pretrained Qwen with exact native L1 corpus/order/budget and 1/2/1/2 weighting. Keep parser/decoder/template/terminal and qualified method fixed, log native tokens/visits and checkpoints. Same prerequisites as RV014 including native data/resource/loss/latency policy, not L1 completion/ASR/LL042/LL048. No warm-start from L1 or a custom adapter.
- [ ] RV017 Export/reload actual selected native L2, then evaluate separate G/A under native L1 controls/checkpoint policy. Separate native validity/EOS from semantic metrics; preserve all 309 attempted outcomes including zero-scored failures, and mark not_attempted/invalid artifacts partial. G depends on RV016/LL031 only plus common checks; A also needs the fixed ASR Validation cache/LL040. Reject cross-format score comparisons.
- [ ] RV018 Use LL024 saved native L0/L1/L2 G/A comparison under hard validity and the already-sealed performance policy. Correctly scored failures/timeouts remain eligible; partial/leaked/incompatible evidence does not. Compare L2 to L1 using declared A criterion/tolerances; choose qualifying L2 only for improvement >1e-6, otherwise comparable valid L1, with ties to L1. Missing required supports/evidence remains pending, not a post-hoc waiver or guessed policy. No LL042/final-handoff/model/replay dependency.

### L3, promotion and deployment

- [ ] RV019 Build/token-audit approved Fit ASR rows through the native renderer with full original strict-prefix evidence/manual decisions. Targets/gold values stay fixed; no Validation training or clean+ASR concatenation. Record required meaningful-error/semantic/type/tool coverage, realized mixing and limited_noisy_coverage; p_noisy=.5 is proposed. Reaudit native lengths without loosening filters. Prerequisites: new RV007, RV011 Fit/export scopes, LL035–LL038 and Fit review.
- [ ] RV020 Manually run L3 independently with the saved RV018 policy, common budget/checkpoint selection and approved view mixing. Verify the bound resource evidence covers actual noisy lengths; explicitly reprobe if needed without launching training automatically. Save realized ratios/RNG states and coverage qualifiers. Dependencies: RV018, RV019 and matching resource/latency evidence.
- [ ] RV021 Export/reload actual selected native L3 and evaluate independent G/A under the same native identities, profile/checkpoint rules and fixed Validation cache as L1/L2. Preserve all 309 outcomes/failure penalties, separate format validity from semantic/state metrics and mark partial runs honestly. No custom L0 pairing or L3-only post-hoc checkpoint search. Prerequisites: RV020 and actual export checks.
- [ ] RV022 Run LL042 final artifact-only native comparison/fixed cases/uncertainty with the preregistered policy hash. Separate hard validity from performance tolerance: fully evaluated failures/timeouts can still be ranked and selected, while partial/leaked/incompatible runs cannot. Apply primary A, minority TP/precision, critical-argument, failure/timeout/G/latency guards and explicit missing-support rules; no categorical one-timeout/one-TP veto or retrospective changes. Compare SFT to native L0, retain L0 without qualifying gain, break passing SFT ties L1/L2/L3. Provisional versus State-Verified needs appropriate references; submission readiness still requires RV025.
- [ ] RV023 Perform a **reference feasibility investigation first**, independently of LL042: inspect organizer permission/runtime contracts and whether Train gold calls may be replayed in a separately invoked reference-only run with its own RuntimeFactory/process and one ToolEnv per source. Require documented isolation, input/runtime/catalog/canonicalization identity, replay/result consistency, coverage and trust acceptance; do not assume permission, determinism or gold consistency. No reference execution occurs as part of this checklist edit or any prediction run. Only if that route is validated and separately authorized, or another trusted evaluator is supplied, obtain/verify references and compute available state metrics; final ranking integration uses LL042 later. Never read/copy/parse `*_environment/state.json`, hash `label.final_state`, or create a second ToolEnv within a prediction run. Without a trusted reference, keep State Match null and any otherwise eligible winner provisional. Prerequisites: LL023 and rule/runtime evidence for investigation; trusted references and corresponding actual prediction artifacts for scoring. LL042 is not an investigation prerequisite.
- [ ] RV024 Run fresh-process offline export/container and actual full-audio evaluation checks with the selected deployed ASR/Qwen pair. Measure current/history ASR, total latency, joint VRAM, logical budgets, deterministic reruns and deadline/failure handling on the available host. Local success is still not A30 acceptance. Dependencies: LL041, LL043–LL044 and complete export/resources.
- [ ] RV025 Run final acceptance in the actual A30/offline Docker profile, with authoritative calls/hash, model/context budgets, 30-second sample supervision, full coverage and reproducibility evidence. If the host/container/supervisor is unavailable, leave deployment unverified. Dependencies: RV024 and final organizer/runtime infrastructure; no submission-ready claim from local probes or cached A.

## Acceptance gate coverage

Gate IDs and requirements are defined in [specs §13](specs.md#13-preflight-tests--acceptance-criteria).
Existing gate IDs are retained with native contracts; N01–N04 add catalog, parser,
termination and suite-identity acceptance without adding LL/RV task IDs.
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
| P01 Shared native rendering | LL007, LL013–LL015, LL018–LL019 | Scoped RV001/RV002: selected Vietnamese text, exact history/multi-call/order and feedback-prefix preservation |
| P02 Native serialization | LL007, LL013, LL019 | RV001/RV002 catalog and native assistant/tool-role fixtures |
| P03 Early CPU decoder proof | Minimal LL007, LL013–LL017, LL019 POC subset | RV002/decoder_poc: actual pinned-tokenizer nine-case token walks before full exporter/freeze/L0; no full exporter/GPU prerequisite |
| P04 Native response-only mask | LL016, LL019, LL034 | Scoped RV001, native RV002/RV003/RV007 |
| P05 Pinned native template | LL014–LL017, LL019 | Native RV002 early proof plus full regressions; new Vietnamese P1/exact-final hashes only after tests |
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
| W02 Read-only compare | LL002, LL024, LL042, LL045 | Scoped RV001 hard-validity/performance/tie/one-timeout fixtures; preregistered-policy RV018/RV022, no model jobs |
| W03 Portability | LL003–LL005, LL046, early LL047; LL045/LL048 final review | Scoped RV001, RV004; no final-handoff prerequisite |
| X01 Export | LL031, LL041 | RV015, RV017, RV021, RV024 |
| X02 Submission | LL043–LL044, LL047–LL048 | RV024, RV025 |
| N01 Native catalog | LL007, LL009, LL013, LL018–LL019 | RV001/RV002 extension/availability/order/financial/empty-args conformance |
| N02 Native parser/feedback | LL015, LL019, LL021, LL034 | RV002 early parser proof plus scoped RV001/RV002 feedback/missing-EOS/repetition/successful-prefix repair fixtures; real run diagnostics |
| N03 Native termination | LL008, LL014–LL019, LL020–LL022 | RV002 early initial/post exact-final reachability with nonempty tools; later ask/empty/cut regressions and native RV010 |
| N04 Native suite identity | LL002, LL012, LL017, LL024, LL039, LL041–LL042, LL045 | RV001/RV007 old-format rejection; RV010/RV015/RV017/RV021/RV022 native rebaseline/comparability |
| X03 Early latency | LL032–LL033, LL043 | RV012 |

For M03, author both controlled resume tests and an opt-in actual-model interruption/
resume check. Execute it as a separately recorded check when qualifying the target
stack, without extending a full run's 500-update budget or resuming across experiments.
RV002/decoder_poc is an early scoped record: later RV002 regressions may still be
pending while that passed matching proof gates full exporter integration. Final P1
acceptance also requires those later tests. No proof depends on its own future
exporter output. RV001 references always mean the specific phase/test scope needed by the gate;
completing its Phase I scope does not pass later trainer/view/reporting checks.
RV005 early smoke cannot substitute for M02/RV008 worst-row qualification. RV011
export, Fit-cache and Validation-cache scopes are separate dependency records even
when their parent checkbox remains open for unfinished scopes.

## Ordering and readiness rules

### Authoring milestones and dependency flow

These are implementation milestones, not automatically executed commands. Preserve
all LL/RV IDs. Dependencies flow from minimal native helper/fixture code to its
CPU proof, then to full exporter/acceptance and consumers. The proof must not depend
on future exporter outputs. Other source can be authored before hardware work;
GPU checks remain not_run until explicitly requested on the target machine.

| Milestone | Authoring scope | Required predecessor / ordering note |
|---|---|---|
| Core infrastructure | LL001–LL006 | Existing contracts/config/paths/storage; full split/data preparation is not required by the minimal decoder proof |
| Early CPU native proof | Catalog subset LL007 + minimal LL013–LL017/LL019 | Core + local tokenizer/backend fixtures -> RV002/decoder_poc, no full exporter/LL018/RV007/GPU |
| Full data/export/audit | LL007–LL012 + LL018 | Integrate after matching passed early proof; preserve strict prefix/history/gold; no reverse proof dependency on full export |
| Full native P1/token acceptance | LL013–LL017 + LL019 | Selected Vietnamese P1/exact final; early proof then remaining history/rejection/render/mask regressions before acceptance freeze; CPU only |
| Native L0 metrics/evaluation | LL020–LL024 | Native projection/P1/parser/decoder/EOS and semantic fixtures; fresh native L0, no L3/ASR/final-comparison prerequisite for G |
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
Core + minimal native catalog/codec/Vietnamese P1/token/POC fixtures
  -> RV002/decoder_poc (CPU tokenizer only; no full exporter/weights/GPU)
  -> full exporter/history/audit + remaining render/mask/rejection tests
  -> scoped RV001 + later RV002 -> RV006/RV007/P1 acceptance
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
Hard validity + preregistered tolerances/ties + saved evaluations + LL042
  -> RV022 final comparison/performance selection (A30 acceptance separate)
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
| Early native feasibility | Minimal helpers plus RV002/decoder_poc actual local-tokenizer token walks; blocks full exporter/freeze/L0 if absent/failed, no GPU needed |
| Reviewable native Phase I | Vietnamese P1/final selected, proof-backed full integration and LL001–LL020 authored; remaining data/token evidence explicit; no ASR/GPU/LL034/LL045 prerequisite |
| Correct executed L0-G | Relevant Phase I checks plus baseline evaluator/local model evidence; ASR, L3 and trusted state may remain blocked |
| Early GPU feasibility | RV004/RV005 limited model/update/short-long-memory evidence; no final trainer/handoff dependency and no full-fit guarantee |
| Full L1/L2 execution | Audited/token-frozen common gold-text corpus, objective/trainer/checkpoint tests, full target-GPU method qualification and pilot review or explicit unresolved-audio-latency decision; no ASR/LL042/LL048 prerequisite |
| L3 execution | Compatible L1/L2 G/A policy, selected-ASR Fit cache, approved full-prefix rows, noise coverage and matching resource evidence |
| Implementation handoff | LL001–LL048 authored/reviewed; RV/gate ledger openly records unrun/blocked items, resource inventory and manual commands |
| Training complete | Each trained experiment has its full declared updates and durable checkpoints, not merely scripts or a passing probe |
| Fully evaluated/comparable | All 309 attempted IDs have valid outcomes, no not_attempted; failures/timeouts remain scoreable with correct zero penalties and shared profiles |
| Candidate selection | Actual export + hard validity + preregistered performance tolerances/support/ties; full-coverage failures/timeouts not automatic veto, provisional without trusted state |
| Deployment readiness | Requires separate actual RV025 offline A30/audio/deadline/model/reproducibility acceptance; local performance tolerance is not submission compliance |
| Submission ready | Actual offline A30/full-audio/supervision acceptance; neither training success nor State-Verified ranking substitutes for it |

### Open decisions and document alignment

- **NATIVE_P1_ACCEPTANCE:** Vietnamese native P1 and exact NFC final "Đã kết thúc."
  are selected by specs §4.2, with new versions. Their installed-tokenizer/decoder/
  mask/hash acceptance remains unrun; do not leave language as an unresolved design
  choice or claim Vietnamese outperforms English. A different final policy needs
  explicit identity change/rebaseline before comparisons, not a post-hoc allowlist.
- **EARLY_DECODER_PROOF:** actual pinned-template/LMFE nine-case CPU token walks and
  backend-failure handling are not run. Missing local resources or failed composition
  block full exporter/P1 acceptance/native L0. A replacement native decoder needs
  review/new identity/same proof; no custom/unconstrained fallback.
- **HISTORY_NATIVE_PROJECTION:** exact text plus paired arrays preserve supplied
  turn structure, not invented temporal interleaving. Missing/mismatched/ambiguous
  ordering stays unsupported/needs_review. Use real Fit anchors and labeled controlled
  negative cases; no history replay, missing-result fabrication or current labels.
- **REJECTION_FEEDBACK:** existing agent.py still has custom correction wording;
  migrate it only during implementation. Canonical native user feedback must retain
  successful tool prefixes, explicit stop metadata and total bounded repair count.
  Missing EOS/cuts/internal errors and uncertain mutations never silently retry.
- **SELECTION_POLICY_ACCEPTANCE:** hard validity differs from performance guards.
  Proposed nonzero tolerances/support/null handling/ties in specs §10.5 must be
  sealed before outcomes. One timeout/lost TP is not automatically incomparable or
  unselectable; mandatory missing evidence stays pending, optional risk unverified.
  Native winners remain distinct from actual A30/submission acceptance.
- **State-reference permission/trust:** organizer/runtime support for a separate
  reference-only gold replay is unverified. LL023/RV023 investigate it without
  executing replay or promising a trusted evaluator. No hidden-state access or
  in-prediction second environment is permitted; absent trust leaves State Match
  null and winner verification provisional.
- **Host/resources:** exact RTX 5070 Ti SKU/VRAM/Windows kernels, locks, real worst-row
  LoRA/NF4 fit, selected-ASR provenance/caches, manual-review capacity, meaningful
  noisy coverage and A30 hard-deadline acceptance still need actual evidence.
  These do not require redesigning the agreed architecture or adding experiments.

The native specs/plan/tasks are synchronized in this documentation change. The
original review reports, runtime/source, models and datasets are unchanged. The
branch remains fine-tune-llm; no merge into main or PR reopening is requested.
LL046–LL048 final delivery never becomes an early transfer/probe prerequisite.

The receiving teammate records measured evidence in ignored run artifacts and links
the concise status in the team's issue/PR workflow. Do not commit raw data, weights,
transcript caches, hidden app state or full traces. Do not update old JSON review
templates to suggest experiments have run. Any change to architecture, split,
prompt contract after freeze, corpus or shared comparison controls requires the
explicit new-policy/new-suite handling defined in the specification.
