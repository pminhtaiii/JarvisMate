# Experiment and promotion contract

Reuse [feature 002 measurement/experiments](../../002-measurement-prompt-experiments/contracts/experiments.md)
after their implementation/acceptance. This feature adds protocol and tuning factors,
not a new scorer or reporting subsystem. Until reporting/evaluator prerequisites are
available, mark exploratory diagnostics and unavailable evidence explicitly.

## Comparator integration

Extend existing `compare-runs --factor` choices with `protocol` and `planner-model`;
do not weaken `harness`, `instructions` or `few-shot` validation. Existing factors
cannot compare changed planner weights. Add focused rejection and acceptance tests.

For `protocol`, require identical code, checkpoint/tokenizer, ASR, data/catalog,
selected IDs, hardware/dtype/seed/limits, execution/offload/filter settings and no
examples. Only resolved protocol/system serialization, constraint identity and
associated prompt metadata may differ. Both adapters run in the same code revision.
Native uses the baseline instruction-policy selection with native protocol wording;
reject current structured `precise-v1` and example bundles until explicitly ported.

For `planner-model`, allow only planner checkpoint weight/config export identity to
change. Require identical tokenizer/template, native protocol/prompt/constraints,
ASR/runtime/data, code/packages, selected IDs and all other execution settings.
Reject changed ASR, context budget, examples or instruction policy. Record each
factor's allowed differences explicitly rather than bypassing all model checks.
New factors use the scoring/latency evidence below; a diagnostic report cannot
declare final benchmark promotion. Add these identities without relaxing legacy
manifest compatibility or mixed-resume rejection.

## Stage A: Protocol-only comparison

Freeze grouped Train fit/validation before tuning. Baseline is current structured
protocol; candidate is native with the same original checkpoint. Fix selected IDs,
runtime/catalog, ASR, seed, greedy decoding, limits, selection filter (off), offload,
instruction policy, hardware and measurement setup. Native serialization/system
protocol instructions/constraint are the declared changed factor. No weight updates,
few-shot augmentation or simultaneous harness optimization. Both adapters may be in
one revision with explicit protocol selection; record exact identities.

Run supplied-transcript diagnostics and audio evaluation separately. Report all
selected IDs, including failures/missing attempts; never compare successful intersections
only. Do not reuse mixed resume populations. Report malformed outputs, premature
finish, extra/missed calls, clarification/empty-gold cases, tokens/generation counts,
state-hash outcomes/evaluator scores where available, and full-attempt timing.

Native is a chosen training direction but not an assumed performance win. Retain
structured control if native regresses; investigate before expensive fitting. A
documented accuracy/latency trade-off may be reviewed, not hidden in aggregate means.

## Stage B: SFT eligibility

Require completed baseline/protocol reports, recurring transcript-mode planner errors,
and correction of deterministic prompt/parser/schema defects before fitting. Missing
official scoring may permit data/export and fit-only engineering smoke, but cannot
establish benchmark improvement or satisfy score-based promotion. Freeze comparison
policy before reading tuned outcomes. Validation never enters fit/augmentation/examples.

## Stage C: Native base versus tuned deployment export

Compare the native base and each actual merged export on identical validation IDs,
native protocol, runtime, prompt/template, decoding and ASR settings. Separate any
later quantization change as another factor. Training loss/teacher-forced next-action
accuracy support diagnosis only. List per-ID regressions and error categories.
Repeated validation selection is development tuning, not an independent test result;
do not use public/private test labels. Preserve the unmodified base as fallback.

## Scoring and promotion

Use authoritative evaluator outputs, including gold-empty/sample score/state match
when available. Do not implement a proxy scorer here, infer gold hashes from
`label.final_state`, or inspect environment state. The supplied brief does not define
official aggregation. A full-selection mean of evaluator sample scores is labeled
a development diagnostic; official claims require organizer-supported aggregation.

Default promotion recommendation requires full fixed-selection coverage, improvement
in an organizer-supported benchmark aggregate,
no increase in failed/unknown/TIME_LIMIT/>=30s attempts, no decrease in state-hash
match count where supplied, and a report of every sample regression. Freeze revised
trade-off criteria before candidate outcomes; disclose any acceptance exception.
A development-diagnostic gain can select an experimental checkpoint for further
evaluation, but its status remains exploratory/eligible-for-review. It cannot satisfy
the benchmark promotion gate while official aggregation or evaluator evidence is unavailable.

Final-budget acceptance additionally requires audio mode on the specified A30 setup,
every full attempt known and strictly <30 seconds, total model/context/parameter
eligibility and deterministic rerun evidence. Report p50/p95/p99/max and per-ID
deadline margin. A score gain on developer hardware is exploratory until this passes.
Loop-only timings and cooperative deadlines are not hard-preemption evidence.
Record initialization/cold-start policy separately and defer to final organizer rules.

Completing infrastructure can yield no promoted model. State that outcome honestly.
GRPO reward/rollout/reset policy and synthetic augmentation are separate future specs.
