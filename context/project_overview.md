# LifeMate project overview

## Goal

LifeMate is a five-person competition project for turning spoken Vietnamese requests into ordered app-tool calls. The first target is a small, real, runnable MVP slice through audio interpretation, planning, tool execution, and measurement. A runnable path is a starting point; it does not imply reliable accuracy.

The agent is judged on its actions and resulting simulated app state. It should use available installed-app tools, request missing information with `sys.ask_missing_info` when needed, and return no calls when no installed app can handle the request. See the [benchmark reference](benchmark.md) and [provided competition brief](../docs/reference/lifemate-competition.md).

## Success and evidence

Measure success by benchmark scoring: exact final `state_hash` match gates the non-empty-gold sample score, while tool-call precision and recall measure call matching. Empty-gold samples score only when no calls are submitted. The hash and call log must come from the sample's `zaic_tools` environment. Report measured results with the dataset split and command used; do not claim a capability based on a plan or an unmeasured run.

The immediate engineering goal is to make one end-to-end path runnable and observable, then measure it. The intended benchmark covers Vietnamese audio, user context and history, installed apps and schemas, and a simulated environment. Submission constraints and exact scoring details are in the [benchmark page](benchmark.md).

The first deliverable is a small runnable pipeline that produces the competition-required prediction artifact, with an initial submission targeted for 27 October 2026. A small integrated run is the first checkpoint; a submission file must cover every sample in the target split. This is a target, not evidence of a completed run or submission. Dataset access and working inference remain prerequisites.

## Development sequence

The [Python baseline source and tests](../python/README.md) are authored for handoff,
with execution explicitly deferred to the receiving teammate. No measured baseline
or submission is established; see the [validation record](../specs/001-python-sample-pipeline/validation.md).

Follow **Baseline -> Evaluation on Train Validation -> Error Analysis -> Fine-tuning
if needed** in the [roadmap](roadmap.md). Establish the pretrained transcript/audio
baseline first, freeze a grouped fit/validation partition of Train, and attribute
errors before deciding whether training is justified. The
[planner SFT design](../docs/design/train-to-sft.md) specifies how Train gold
call/result prefixes can supervise the next action without leaking future results.
It is documentation for conditional later work; no training is implemented or scheduled
by this update. Real-model validation is handed off to a teammate with suitable compute.

## Team and open decisions

Prioritize the competition pipeline and offline submission before a phone or browser voice interface. Benchmark-provided audio is the initial input. Model experiments, fine-tuning direction, development compute, and the accepted hybrid boundary are recorded in the [technology stack](tech_stack.md).

This is a five-person competition effort. Teammates own bounded components end to end, coordinate interfaces before dependent parallel work, and use GitHub issues and pull requests for shared scope, progress, review, and integration. See [team workflow](team.md).

Still open: exact models, component assignments, frontend timing, and the MVP scenario. Record settled cross-component choices in the [context entry](README.md); keep task details in the relevant issue or PR. Do not present open choices as commitments.

## Vocabulary and boundaries

A [sample](../GLOSSARY.md) contains a spoken request, context, installed apps, optional history, and an isolated simulated app environment. The MVP slice is an observable runnable path, not a claim of model quality. The simulated app state is accessed only through `zaic_tools`; never read the split environment files directly. See [architecture](architecture.md) for the provisional runtime outline.
