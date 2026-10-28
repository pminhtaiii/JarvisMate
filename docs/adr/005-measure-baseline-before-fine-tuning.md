---
status: accepted
---

# Measure an end-to-end baseline before fine-tuning

Build and evaluate the complete competition path using pretrained models before investing in fine-tuning. Follow **Baseline -> Evaluation on Train Validation -> Error Analysis -> Fine-tuning if needed** in the [roadmap](../../context/roadmap.md). This defers specialization work in exchange for an observable baseline that separates speech, planning, execution, and latency failures; compare supplied-transcript and ASR paths on the same frozen grouped Train validation selection.

After deterministic defects and prompt/schema issues are addressed, recurring planner errors may justify the conditional [Train-to-SFT design](../design/train-to-sft.md): user request, context, available tools, and strictly previous gold calls/results supervise one next action. Split source samples before expansion, exclude validation from fitting, and preserve inference label isolation and the existing ReAct/ToolEnv boundary. ASR errors need separate analysis; tool-call SFT is not ASR training.

This elaboration dated 2026-10-27 keeps the baseline-first decision accepted. Training method, hyperparameters, and the decision to train remain conditional. No exporter, training implementation, checkpoint, or measured baseline is established; retain the pretrained baseline if tuning is unnecessary or unproven.
