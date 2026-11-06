# Research and decisions

**Status**: Design research, 2026-11-06. Luna explored this checkout read-only at
maximum reasoning as requested. No model, training or GPU checks ran.

## Repository evidence

The [roadmap](../../context/roadmap.md) and [SFT design](../../docs/design/train-to-sft.md)
contain designs, not an exporter, trainer, dataset manifest or recorded tuning run.
The existing runner uses legacy JSON call/finish. [Feature 002](../002-docker-integration/plan.md)
plans the native Qwen runtime and full-attempt supervisor with tasks pending.
The reference image's counts, ASR views and validation results are not verified here.

## Decisions

**Decision: one fixed QLoRA recipe.** Use the agreed 4B model and attention-only
recipe in the plan. Rationale: deliver a practical baseline from existing user
experiments. Alternatives: model search, full tuning, all-linear LoRA and ASR
augmentation add unrequested experiments and remain deferred.

**Decision: reuse separate validation.** All designated training sources stay
training; no new holdout. Rationale: explicit user choice. Audit roles and overlap.
Alternative: randomly splitting expanded steps risks leakage and changes ownership.

**Decision: direct native next action.** Share feature 002 rendering; use actual
previous observations at inference and strict gold prefixes only for supervised
conversion. Rationale: real lookup results supply downstream IDs without critique.
Alternatives: whole-chain targets can invent dependencies; reflection is rejected.

**Decision: Trainer with explicit final-span masking.** Use PEFT/bitsandbytes and
a tested collator; no packing initially. Rationale: historical assistant messages
must stay masked, so assistant-role masking alone is insufficient. Alternative:
TRL adds a dependency without a demonstrated missing capability.

**Decision: resolve a tested host-specific environment lock.** One Linux CUDA
5090 or H200 runs an NF4 BF16 backward/memory smoke before full training. Rationale:
GPU names alone establish neither installed-wheel compatibility nor feasibility.
Alternatives: guessed package pins create untested claims; unpinned latest installs
lose reproducibility. Record the resolved lock separately from runtime dependencies.

**Decision: inexpensive candidate selection, separate competition assessment.**
Lowest validation NLL among checkpoints with full unique training-row/source
coverage selects one candidate, earliest exact tie. Early NLL remains diagnostic;
no eligible finite candidate means selection fails. Merge into a fresh
unquantized base and assess the FP16 artifact itself. Rationale: deterministic
selection without a search; loss remains distinct from executed competition score.
Alternatives: assuming reference step 400 is best or equating NLL with score has
no supporting evidence. Record quantized/FP16 behavior differences explicitly.

## Primary technical sources consulted

- [Qwen model card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507): model identity,
  native template usage and license metadata; actual snapshot and pre-cutoff release
  eligibility still require recording during implementation preflight.
- [PEFT quantization guide](https://huggingface.co/docs/peft/developer_guides/quantization):
  preparation and adapter training over a frozen quantized base.
- [PEFT LoRA reference](https://huggingface.co/docs/peft/package_reference/lora):
  adapter configuration and merge interfaces, verified against locked versions.
- [bitsandbytes installation guide](https://huggingface.co/docs/bitsandbytes/main/en/installation):
  platform/build compatibility must match the selected host. Main documentation is
  not a tested project package lock.

## Execution gates

Dataset/catalog/snapshot paths, exact counts, grouping metadata, GPU/CUDA environment,
permitted validation labels/reference hashes and organizer accounting are execution
inputs. Missing inputs fail the affected stage clearly; they do not authorize
invented data, hidden state access or claims that these gates passed.
