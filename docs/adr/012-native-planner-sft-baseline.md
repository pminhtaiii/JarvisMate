---
status: accepted
---

# Native planner QLoRA baseline before the old roadmap gate

Add one fixed supervised fine-tuning baseline for Qwen3-4B-Instruct-2507, specified by
[feature 003](../../specs/003-planner-sft-baseline/spec.md), as a development CLI
(`python -m lifemate.sft`) outside the inference runtime.

## Decision

At the user's explicit request:

- **Tune now.** This overrides the conditional gate of [ADR 005](005-measure-baseline-before-fine-tuning.md)
  and the [roadmap](../../context/roadmap.md) for this one recipe. The exception
  authorizes neither a search nor a claim that tuning improves the competition score.
- **Separate validation.** All designated training sources are fitted. The explicitly
  supplied validation set replaces the roadmap's internal 80/20 proposal and never
  contributes gradients. Sets are audited for overlap, never repartitioned.
- **Native next action, no reflection.** The target is one `qwen-native-v1` call or the
  neutral finish text plus EOS, rendered by the runtime's own functions in
  `lifemate/adapters/qwen_native.py`. No legacy JSON, critique or rationale targets exist.
  Waiting clarification stays a deterministic stop and emits no extra finish row.
- **Coverage-safe selection.** Lowest finite validation NLL among the five candidates
  that trained on every ready row and source; an exact tie takes the earlier update.
  Earlier candidates remain diagnostics. NLL is not a competition score.
- **Train-only alternative (added 2026-11-08).** Dataset v3.2.0 ships no labeled
  validation set, so `data.validation_mode = "none"` fits 100% of the approved Train
  sources with no held-out set. It selects the update-500 checkpoint only after all 500
  updates complete with full coverage; it computes no validation NLL and is recorded as its
  own selection mode and config identity. Hyperparameters, the audit and the overlap rule
  for `separate` are unchanged. This mode has no checkpoint-selection signal and no
  pre-runtime quality evidence; the closed-loop runtime assessment is the first measurement.

## Consequences

- **An explicit training loop replaces `transformers.Trainer`.** The plan preferred
  Trainer over adding TRL. The required objective (summed target cross-entropy divided by
  the supervised tokens of the whole 16-example window), a sampler that resumes mid-stream,
  and persisted coverage would each override Trainer internals that vary between versions.
  A short PyTorch loop adds no dependency and makes the 1x16/4x4 equivalence directly testable.
- Only target positions reach the frozen output head, through `logits_to_keep`. A
  full-sequence vocabulary-sized logits tensor is unnecessary at long tool-schema prompts.
- Training packages stay in a separate `training` extra outside the Docker image.
- A reviewed resolution file is the only way to clear a flagged training source: it records
  an explicit exclusion, or keeps a flagged gold target. Unresolved entries block readiness.
- Code authored for this feature does not establish GPU feasibility, a trained checkpoint,
  a validation score or A30 compliance. See the
  [quickstart](../../specs/003-planner-sft-baseline/quickstart.md) for recorded evidence.
