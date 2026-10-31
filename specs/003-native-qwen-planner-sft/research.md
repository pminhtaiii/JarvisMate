# Research decisions

Researched 2026-10-31 with Luna/max exploration. Sources describe model/library
behavior, not measured LifeMate results.

## Native protocol and boundary

**Decision**: Use the exact checkpoint's native template; normalize one native call
to canonical JSON inside the adapter, preserving the existing runner interface.
**Rationale**: Qwen recommends Hermes-style calls. Its template accepts tools,
assistant tool calls and tool results; Instruct-2507 is non-thinking only.
**Alternatives considered**: Custom format stays control only; Qwen-Agent/vLLM add
unneeded runtime architecture; changing runner to batches changes execution policy.

Sources: [Qwen function calling](https://qwen.readthedocs.io/en/latest/framework/function_call.html),
[model card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507),
[actual template](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/blob/main/tokenizer_config.json).

## Grammar and termination

**Decision**: Compose LMFE sequence/union/literal/schema parsers for one native call
or fixed final text, followed by actual tokenizer EOS. Use per-tool schema binding.
**Rationale**: LMFE 0.11.3 exposes these combinators and admits EOS once a branch can
end. Qwen call delimiters are `special:false`; EOS is `<|im_end|>`. Actual-tokenizer
tests remain necessary. Keep catalog extension information in model-visible schemas;
reuse current x-one-of grammar expansion and organizer x-ref/x-match authority.
**Alternatives considered**: Unconstrained fallback loses the current contract;
generic name/arguments union can mismatch schemas; multiple calls change step semantics.

Sources: [LMFE parsers](https://github.com/noamgat/lm-format-enforcer/blob/v0.11.3/lmformatenforcer/characterlevelparser.py),
[LMFE token enforcer](https://github.com/noamgat/lm-format-enforcer/blob/v0.11.3/lmformatenforcer/tokenenforcer.py).

## Finish supervision

**Decision**: Constrain final assistant content to `Mình hiểu.` and map normal EOS
to internal finish. Record this as a deterministic policy target, not original gold text.
**Rationale**: Gold supplies calls, not final prose. Neutral acknowledgement avoids
asserting a mutation succeeded and meets the accepted short native final response.
**Alternatives considered**: Arbitrary prose is ambiguous; an internal finish function
introduces a non-organizer tool; empty output hides failure; custom finish JSON mixes protocols.
Successful terminal missing-info calls receive no extra final target. Final text is
not emitted as a benchmark tool or included in submission rows.

## Data and masking

**Decision**: Split source groups before step expansion; one native next-completion
per strict prior prefix, final-completion-only loss including EOS, packing off initially.
**Rationale**: Prior assistant calls are input, so assistant-only masking is insufficient.
The local gold conversion design already defines leakage/grounding audits. Verified
diverse tool data is supported by ToolACE, but not proven optimal for LifeMate.
**Alternatives considered**: Whole plans cannot use live results; result supervision
teaches fabricated observations; immediate synthesis confounds the first experiment.

Sources: [TRL SFT](https://huggingface.co/docs/trl/sft_trainer),
[ToolACE](https://arxiv.org/abs/2409.00920),
[local data design](../../docs/design/train-to-sft.md).

## Training method and stack

**Decision**: All-linear LoRA if measured memory allows; NF4/double-quant/BF16 QLoRA
otherwise. Lock optional TRL/PEFT/Transformers/bitsandbytes versions after a one-batch
compatibility smoke, before fitting; record exact versions and hardware. Merge onto
original non-quantized base and test the actual deployment export.
**Rationale**: PEFT documents the recipe. Thinking Machines found MLP coverage
important in its experiments. These support a starting point, not LifeMate optima.
**Alternatives considered**: Full tuning first uses greater optimizer memory without
local evidence; attention-only adapters narrow coverage; dynamic inference adapters
add an unnecessary deployment interface. GPU capacity remains a measured gate.

Sources: [PEFT quantization](https://huggingface.co/docs/peft/developer_guides/quantization),
[QLoRA](https://arxiv.org/abs/2305.14314),
[LoRA Without Regret](https://thinkingmachines.ai/blog/lora/).

## Evaluation and RL

**Decision**: Use evaluator-provided outcomes. Any mean sample score is a development
diagnostic unless official aggregation is supplied. Missing scoring blocks promotion;
GRPO remains a separate later feature.
**Rationale**: No local official scorer API or baseline evidence was established.
Local rules specify state gating but not official aggregation. Full-attempt timing
depends on feature 002; loop-only/non-A30 timings cannot prove deadline compliance.
**Alternatives considered**: Teacher-forced accuracy, proxy rewards, or inferred gold
hashes cannot establish the accepted benchmark objective. Never derive a gold hash
from `label.final_state` or inspect environment files.

Sources: [benchmark](../../context/benchmark.md),
[experiment contract](../002-measurement-prompt-experiments/contracts/experiments.md).
