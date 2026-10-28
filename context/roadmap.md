# LifeMate development roadmap

**Updated**: 2026-10-27. **Status**: design and roadmap only. No baseline run,
validation score, SFT export, or training completion is established by this page.

The development sequence is **Baseline -> Evaluation on Train Validation -> Error
Analysis -> Fine-tuning if needed**. It extends [ADR 005](../docs/adr/005-measure-baseline-before-fine-tuning.md)
without changing the [runtime architecture](architecture.md) or
[competition constraints](benchmark.md). Fine-tuning is conditional, not a prerequisite
for a working baseline or an automatic fourth-stage commitment.

## Stage 1: Pretrained baseline

Implement the [Python sample pipeline](../specs/001-python-sample-pipeline/plan.md)
and its [27 implementation tasks](../specs/001-python-sample-pipeline/tasks.md):

- Keep ASR, the single general planner, and deterministic tool execution separate.
- Start with supplied Train transcripts, then use audio for the same samples.
- Use the accepted Qwen planner and Whisper/PhoWhisper experiments from the
  [technology stack](tech_stack.md); no weight updates in this stage.
- Keep the bounded structured ReAct loop and exact
  [planner action grammar](../specs/001-python-sample-pipeline/contracts/planner.md).
- Produce authoritative calls/hash, required traces, and manifests. Stop a development
  batch on its first execution failure; preserve partial output without declaring it complete.

**Exit evidence**: passing controlled boundary tests, an opt-in supplied-runtime
smoke, and separate real pretrained-planner transcript/audio runs. Code and controlled
tests alone do not satisfy real-model acceptance. A few successful samples establish
integration, not a validation score or full-submission readiness.

The current developer machine is for implementation and model-free checks. A teammate
with suitable compute executes the real runs. T017, T021, T025, and other unexecuted
acceptance checks stay open until their stated evidence exists. This handoff policy
does not authorize implementation or model execution through this documentation update.

## Stage 2: Evaluation on a held-out part of Train

### Freeze the sample partition first

Before any SFT export or training, create a versioned partition manifest from the
official **Train** records. Use an approximately 80/20 fit/validation allocation
with seed `20261027` as the initial split policy. Actual counts depend on grouping
and class coverage; no split manifest or counts have been produced yet.

- Group at the source-sample/conversation level, before expanding samples into steps.
  All current and historical turns and all SFT rows derived from a sample stay together.
- Detect exact/near duplicate requests, shared conversation prefixes, and repeated
  scenario templates using visible Train inputs. Keep identified related samples in
  one group; a random split of step rows or WAV files is insufficient.
- Review coverage for apps/tool families, multi-app and long-history requests,
  `sys.ask_missing_info`, and empty-gold cases. Report sparse/missing categories and
  grouping limitations rather than forcing duplicates across partitions.
- Assign the already inspected smoke IDs `train_1748` through `train_1751` to the
  fit/development side before freezing. Smoke examples are not an unseen validation set.
- Record source JSONL/catalog hashes, grouping rules and version, seed, group IDs,
  fit/validation sample IDs, counts, and any exclusions. Freeze this identity across
  baseline and tuned comparisons; a changed split starts a separately named experiment.

Validation references are allowed for evaluation, error inspection, and model selection.
They are excluded from optimizer updates, fitting transforms, SFT fit rows, synthetic
training prompts, and few-shot/retrieval banks. Repeated validation-guided selection
must be disclosed; this is a development validation set, not an unbiased final test.
Do not use public/private test samples or generated labels from them to train or tune.

### Compare two inference paths

| Path | User-turn text | Purpose |
|---|---|---|
| Transcript diagnostic | Supplied Train transcript for current and historical user turns | Isolate planner/tool behavior from speech recognition |
| Audio baseline | Local ASR for every current and historical user turn, with no supplied-text fallback | Measure the end-to-end path and ASR impact |

Run the same frozen validation IDs and keep base checkpoint, prompt/tool schemas,
seed/decoding, execution bounds, and runtime versions fixed in comparisons. Change
one component at a time. A controlled adapter result is an infrastructure check,
not a substitute for either real-model path.

Record per-sample outcomes before aggregates:

| Measurement | Evidence and interpretation |
|---|---|
| Final-state match | Use an authoritative reference hash/evaluator with the matching runtime; a submitted hash alone does not establish correctness |
| Tool-call precision/recall/F1 | Apply the supplied exact/non-fuzzy and fuzzy matching rules; distinguish a verified scorer from approximate diagnostics |
| Empty-gold behavior | Empty-call accuracy, including erroneous exploratory calls |
| Missing-information behavior | Correct tool/parameter targets and actual termination condition; preserve earlier calls |
| Execution quality | Schema-rejected, extra/missed/unavailable calls, invalid JSON, limit exhaustion, crashes, and incomplete samples |
| Speech quality | Train-only WER/CER with a documented text normalization, plus errors in names, numbers, and relative times |
| Runtime | ASR/planner/tool and total per-sample timings, initialization separately, p50/p95/max, timeout rate, and peak device memory |

Use benchmark-shaped scoring only when its evaluator and reference evidence have
been verified. `label.final_state` contains changed apps, not the full state to hash.
Do not derive a gold hash from it or reset an agent environment to obtain a better
result. If authoritative state/scoring evidence is unavailable, mark that metric
blocked and report available diagnostics without presenting them as an official score.

Each independent inference run uses one split-matched `ToolEnv` per sample. Gold
references remain in a separate evaluation component, never in planner input; app
state is accessed through the organizer API, never environment-file reads. A full
validation run requires all selected assets. The current fail-fast runner's partial
output must retain its incomplete coverage instead of silently shrinking the denominator.

**Exit evidence**: reproducible baseline reports on the frozen selection, paired
transcript/audio traces, provenance, coverage/failure counts, and explicit metric
limitations. See [testing guidance](testing.md) for capture and storage requirements.

## Stage 3: Error analysis and the tuning decision

Use Train Validation traces and references in the evaluation process to assign a
primary cause and any secondary causes to each failure:

| Error family | Inspect | First response |
|---|---|---|
| ASR | Names, amounts, addresses, negation, time expressions, history-user text | Compare ASR candidates/preprocessing; do not assume planner SFT fixes speech |
| Request/history reasoning | Conditions, references to earlier turns, partial completion, unsupported requests | Inspect prompt/context assembly and permitted-tool selection |
| Tool/argument decision | Wrong tool, unresolved ID, enum/type, missing parameter, excessive/missing calls | Inspect schema presentation and grounding in prior observations |
| Stop decision | Premature finish, needless actions, wrong `ask_missing_info` parameters | Inspect completion examples and the deterministic terminal rule |
| Infrastructure | Label leakage, history replay, runtime mismatch, parser, trace/publication failures | Fix and revalidate deterministic code before training |
| Resource limits | Context overflow, too many model decisions, timeout, unavailable weights/device | Measure deployment/configuration; tuning is not assumed to solve it |

Keep an error register with sample ID, run/trace reference, observed versus expected
behavior, category, frequency, severity, proposed change, owner, and verification
plan. Do not copy validation examples into a training set to fix their individual answers.

**Decision gate**: consider planner SFT only when real transcript-mode runs show
recurring learnable tool-decision errors after deterministic defects and prompt/schema
issues have been addressed. Require sufficient eligible fit data, a frozen validation
set, known model/data eligibility, and available compute. If ASR dominates, investigate
ASR separately; gold tool-call SFT is a planner task. If baseline performance is adequate
or evidence is insufficient, retain the pretrained baseline and record that decision.

## Stage 4: Conditional planner SFT

If the gate is met, open a separate implementation feature/issue covering the
[Train-to-SFT design](../docs/design/train-to-sft.md). That plan will implement:

1. A Train-only exporter with leakage/quality checks and reproducible provenance.
2. Stepwise supervision: **User Request + Context + Available Tools + Previous
   Observations -> Next Tool Call**, with the existing call/finish action grammar.
3. A training configuration and target-only loss mask. LoRA/QLoRA or full fine-tuning
   remain options to choose from measured compute/memory, not installed dependencies.
4. A candidate checkpoint, reload/export checks, and an unchanged planner-adapter
   interface; model weights change without transferring execution policy to the model.
5. Comparison against the frozen pretrained baseline using the same validation IDs,
   both transcript and audio paths, and the same scorer and inference configuration.

Predeclare candidate-selection metrics and regression/latency tolerances before
training. Require measured improvement in the targeted errors and benchmark-relevant
validation behavior, no unacceptable empty/missing-info or other-category regression,
and reproducible compliant deployment. Training loss or teacher-forced next-call
accuracy alone does not justify promoting a checkpoint. Otherwise keep the baseline.

The training host may differ from the inference host. Check the exported system against
the [technical-rule checklist](../docs/design/train-to-sft.md#technical-rule-checklist)
and final organizer instructions before any submission claim. Public leaderboard
results do not replace the frozen Train Validation comparison or authorize test labeling.

## Roadmap artifacts and current status

| Stage | Planned artifact | Current evidence |
|---|---|---|
| Baseline | Python package, controlled tests, real-model manifests/traces | 23 authoring deliverables checked; 4 execution tasks and all runtime checkpoints unverified; see [handoff](../specs/001-python-sample-pipeline/validation.md) |
| Train Validation | Frozen sample/group manifest, per-sample results and comparison report | Planned; no partition or scores created |
| Error analysis | Error register and recorded tune/no-tune decision | Planned; requires baseline evidence |
| Conditional SFT | Export audit, fit/development files, training/checkpoint manifest, validation comparison | Design only; no exporter, dataset, trainer, or tuned checkpoint created |

Store datasets, model files, traces, and experiment artifacts in ignored local storage
such as `.agent-work/lifemate-runs/`; keep code/configuration and concise reports in
their reviewed canonical locations. GitHub issues/PRs carry team ownership and progress.
The existing baseline task ledger remains authoritative for feature 001; this roadmap
does not mark its tasks complete or add training to its implementation scope.
