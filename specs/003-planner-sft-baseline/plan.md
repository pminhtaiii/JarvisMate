# Implementation Plan: Native planner QLoRA SFT baseline

**Branch**: `codex/006-planner-sft-baseline` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)

## Summary

Add a separate data-export/training/export CLI to the existing Python package.
Train one native next-action adapter from supplied transcripts and gold strict
prefixes using all designated training data and the existing separate validation
set. Share serialization with feature 002 and deliver a merged FP16 snapshot.
Code and controlled tests exist; no accuracy, real training or latency gate is passed.

**Branch base**: `codex/005-docker-integration` at
`cb4c54236a588c1130086f01fc2c6f2cbe3d7756`.

## Technical Context

**Language/Version**: Python >=3.11; Linux CUDA, single selected GPU.
**Dependencies**: PyTorch, Transformers; isolated training extra with PEFT,
bitsandbytes and Accelerate. Prefer Trainer plus an explicit final-span collator
over adding TRL. Resolve exact compatible versions on the selected host and save
a lock before full training; preserve current inference pins unless justified.
**Storage**: Local snapshots/data; ignored JSONL/manifests/checkpoints.
**Testing**: Existing unittest conventions; separately enabled actual tokenizer,
model, GPU and full audio acceptance.
**Target Platform**: RTX 5090 or H200 for training; A30 deployment gate separate.
**Project Type**: Development CLI/library, not a service or runtime rewrite.
**Performance Goals**: Feasible fixed-recipe training and full deployed attempts
strictly <30 seconds. No training throughput or score is promised.
**Constraints**: Native next action, no reflection, data isolation, offline inference,
combined models <6B, planner <5B, prompt plus output <=16,384 tokens.
**Scale/Scope**: One data pair, one model and recipe; no searches or augmentation.

## Fixed initial recipe

| Setting | Value / policy |
|---|---|
| Base | Pinned local Qwen3-4B-Instruct-2507 |
| Frozen quantized base | NF4 4-bit with double quantization |
| Compute | BF16; require actual GPU/kernel check |
| LoRA targets | q_proj, k_proj, v_proj, o_proj in all decoder layers |
| Rank / alpha / dropout | 8 / 16 / 0.05; standard LoRA, bias none |
| Frozen | Base, MLP, embeddings, output head; only LoRA A/B train |
| Loss | Final completion plus terminal tokens; normalize by total supervised tokens over the entire 16-example accumulation window |
| AdamW | lr 1e-4; betas (0.9, 0.999); eps 1e-8; weight decay 0 |
| Schedule | 25-update linear warmup, then constant lr through update 500 |
| Effective batch | Exactly 16 examples per optimizer update |
| Initial microbatch / accumulation | 1 / 16 on either GPU; explicit larger microbatch allowed if product remains 16 |
| Length | 500 optimizer updates; actual coverage/epochs recorded |
| Coverage | Require 500*16 >= fit row count; fail for explicit recipe revision otherwise |
| Sampling | Seed 20261027; deterministic full shuffled traversal before repeats |
| Epoch boundary | Continuous stream; no dropped final partial batch |
| Memory | Gradient checkpointing; training KV cache off; no packing/offload/sharding |
| Sequence / output budget | 16,384 total; reserve max_new_tokens=512 by default |
| Save/evaluate | Updates 100, 200, 300, 400, 500; token-weighted validation completion NLL |
| Selection | Among checkpoints with 100% unique training-row/source coverage, lowest finite NLL; exact ties choose earlier update |
| Export | Merge selected adapter into fresh original unquantized base; FP16 |

Optimizer details, seed and schedule are explicit planning defaults, not previously
measured results. The reference image does not preselect step 400. Log all five
teacher-forced diagnostics, but only fully covered checkpoints can be selected.
Fail selection when none has both complete coverage and finite NLL. For example,
with 2,120 fit rows, update 100 has seen at most 1,600 rows and is ineligible even
if it has the lowest NLL. Perform one closed-loop competition
assessment of its merged export, without automatic search if scores are poor.
Validation is sequential and gradient-free. Export accounts for every source and
the coverage safeguard prevents a misleading full-data claim at a fixed update budget.

Accumulation must implement summed target-token cross-entropy divided by the total
supervised-token count across all 16 examples, rather than averaging microbatch
means. Verify gradient equivalence between 1x16 and 4x4 with unequal target lengths
and dropout disabled; normal training still uses the configured LoRA dropout.

## Constitution Check

| Principle | Before research | After design |
|---|---|---|
| I. Benchmark integrity | Pass | Roles/overlap checks; no environment reads; authoritative assessment |
| II. Capability boundaries | Pass | Export/train separate; shared renderer; runtime owns execution |
| III. Execution safety | Pass | No inference retry/reset changes; explicit matching training resume |
| IV. Observable evidence | Pass | Provenance; loss/score separation; unrun hardware gates |
| V. Smallest increment | User-authorized exception | Tuning now; one fixed adapter recipe |

Record the tuning authorization, native format and separate validation decisions
in ADR 012 during implementation. Update affected context pointers with these
feature-specific choices while retaining historical/implemented distinctions.

## Phase 0: Research

[research.md](research.md) records codebase facts, choices and primary technical
sources. Paths and compatible package versions are bounded preflight inputs with
explicit failures, rather than reasons to repeat the interview.

## Phase 1: Design

- [Data model](data-model.md): source roles, rows, masks, manifests and identities.
- [Training contract](contracts/training.md): CLI/configuration/artifacts/failures.
- [Runtime handoff](contracts/runtime-handoff.md): native serialization/export gates.
- [Quickstart](quickstart.md): staged verification and proposed commands.

## Project Structure

```text
specs/003-planner-sft-baseline/
  spec.md, plan.md, research.md, data-model.md, quickstart.md, tasks.md
  contracts/training.md, contracts/runtime-handoff.md
  checklists/requirements.md
configs/planner-sft.example.toml                # planned
python/pyproject.toml                          # training extra only
python/src/lifemate/sft/
  __init__.py
  __main__.py                                 # CLI/config/preflight
  data.py                                     # conversion/audit/manifest
  training.py                                 # collator/Trainer/checkpoints
  export.py                                   # merge/reload
python/src/lifemate/adapters/qwen_native.py    # feature 002 shared renderer
python/tests/test_sft_data.py
python/tests/test_sft_training.py
python/tests/test_sft_export.py
docs/adr/012-native-planner-sft-baseline.md
```

**Structure Decision**: Extend the existing package. Reuse dataset/history/tool
eligibility helpers after checking their trust boundary. Pass whitelisted unlabeled
data to rendering, never raw labeled records. Keep pure conversion separate from
GPU code; avoid a second inference pipeline or custom optimizer framework.

## Phase 2: Handoff

[tasks.md](tasks.md) orders shared protocol, export, train, merge and assessment.
MVP is auditable data export; a usable tuned baseline requires all three stories.
Feature 002 owns its remaining runtime/Docker/supervisor implementation.

## Complexity Tracking

| Exception | Why needed | Simpler alternative rejected because |
|---|---|---|
| Tune before old roadmap gate | Explicit user direction based on prior experiments | Repeating broad baseline/model experiments exceeds requested scope |

No checkpoint, measured score or competition acceptance is claimed. [ADR 012](../../docs/adr/012-native-planner-sft-baseline.md)
records why an explicit loop replaced the preferred Trainer.
