# Controlled experiment contract

## Staging

1. Freeze Train Validation by source/conversation/duplicate groups per roadmap.
   Fit examples come only from its disjoint fit partition.
2. Establish one instrumented control: baseline profile, no examples, fixed models,
   ASR, runtime/catalog, greedy decoding, limits, seed, hardware, measurement protocol
   and selection-filter setting (off for initial prompt trials).
3. Harness-only candidates use baseline/no examples and declare one orchestration
   change. This feature specifies comparison; it implements no parallelism/offload
   optimization beyond existing options.
4. Instruction-only trials use precise-v1 without examples and unchanged harness.
5. Few-shot-only trials use baseline plus a pinned bundle and unchanged harness.
6. Consider a combined trial only after individual results are recorded; no combined
   optimization is required by this feature.

Run transcript diagnostics separately from audio evaluation. Hold IDs and all
non-factor settings fixed. Compare only newly executed attempts; disallow mixed
resume/imported populations for acceptance. Code revisions may differ for a harness
factor; record exact revisions and declare the changed files/configuration, while
checking all fixed identity components. Instructions/few-shot require identical
execution code. Missing identity/evaluation data yields exploratory reporting only.

## Comparison evidence

Report paired per-ID total/planner times, tokens and generation counts, correctness
and failures; include all selected IDs, not only successful intersections. A missing
or failed candidate is a regression/incomplete comparison, not a removed pair.
Score evidence includes evaluator-provided gold_empty/sample_score, state-hash match,
benchmark-gated call F1 for nonempty-gold samples,
precision/recall and empty-gold behavior where supplied. Show ask-missing, invalid,
extra/missed calls and failure categories when available. Unavailable diagnostics
remain explicit. Correctness is imported offline; inference never reads gold labels.

Summarize paired deltas and p50/p95/p99/max, with each run's coverage and missing
measurements. A mean of available evaluator-provided sample_score values may be reported as a
development diagnostic, explicitly not an official competition aggregate. Require
full fixed selection with scores for every selected ID for acceptance, not a
changing observed-only mean. Empty-gold scores use the benchmark's empty-call-list
rule, independently of the hash gate for nonempty gold; undefined call F1 stays null.

## Default acceptance policy

These are specification defaults selected under the user's delegated metric choice;
experiments must freeze any revised thresholds before examining candidate outcomes.

- Harness candidate: preserve per-sample correctness scores/state-hash results and
  authoritative call behavior; introduce no failure or deadline regression; improve
  p95 total latency. Confirm latency direction on three fresh paired runs, reporting
  each replicate rather than treating repeats as independent sample IDs.
- Prompt/few-shot candidate: improve the full-selection mean sample_score diagnostic,
  do not reduce state-hash match count or increase failures/TIME_LIMIT/known >=30s
  counts. List every per-sample regression, including empty-gold and missing-info
  cases, for review. Record extra tokens/time even when accuracy improves.
  Default automatic recommendation also requires no p95 total-latency increase.
  A score gain with higher p95 is labeled an accuracy/latency trade-off for explicit
  review, not an unqualified promotion, even if all samples remain below 30 seconds.
- Final-budget acceptance additionally requires complete known audio timings on A30,
  no failed/unknown/not-started samples, and every measured total strictly <30s.
  Transcript or non-A30 gains are exploratory, not compliance evidence.

No arbitrary latency headroom is mandated before a baseline exists. Report remaining
margin `30 - sample_total_seconds` per known attempt and revisit a practical safety
margin after measurement. Existing cooperative deadlines are a known limitation;
absolute full-attempt enforcement, hard timeout supervision and organizer cold-start
rules require separate follow-up. A loop-completed attempt can still miss the full
budget and must fail final-budget acceptance without changing its persisted status.
