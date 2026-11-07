# Validation guide

**Status**: Future implementation commands; no training/model/GPU acceptance ran.

## Prerequisites

Linux CUDA, Python >=3.11, one RTX 5090 or H200, permitted local train/validation
and catalog files, pinned local base snapshot. Resolve the training extra against
the actual host, verify NF4 BF16 backward/memory and record a compatible environment
lock before full training. See [training contract](contracts/training.md).

Resolve the training environment on the selected host, separately from the runtime:

```text
python -m venv .venv-sft && . .venv-sft/bin/activate
pip install --index-url <CUDA wheel index matching the host> torch==2.9.0
pip install "./python[inference,training]"
pip freeze > <experiment>/requirements.lock.txt
```

The `training` extra holds compatible ranges, not a tested lock. Train records
`pip freeze` itself and fails resume when package versions differ. Never install this
extra into the Docker runtime image. An RTX 5090 needs a CUDA 12.8+ wheel; if the pinned
torch has none for the host, stop and record the incompatibility rather than editing pins.

## Prepare and train

After implementation, copy `configs/planner-sft.example.toml` to an ignored local
file. Set paths/roles; start microbatch 1 and accumulation 16. Explicit larger
microbatch must preserve product 16. No new holdout is created.

```text
python -m lifemate.sft preflight --config <local.toml>
python -m lifemate.sft prepare --config <local.toml>
python -m lifemate.sft train --config <local.toml>
python -m lifemate.sft export --config <local.toml> --selection <experiment>/selection.json
```

Expected: source/overlap audit, ready manifest, five candidate diagnostics,
deterministic selection and merged FP16 snapshot. Unresolved training exclusions
block the full-dataset-ready claim. Bad inputs, insufficient coverage budget,
nonfinite loss and memory failures stop with evidence. Resume is explicit and
requires a complete matching checkpoint.

Inspect per-checkpoint unique row/source coverage: a lowest-NLL checkpoint is
ineligible until every ready training row/source has contributed to an update.
For 2,120 rows, reject update 100 (at most 1,600 visited) even if it is best by NLL.
Verify resume preserves coverage and export rejects an ineligible selection.

## Focused checks

From `python/`, after implementation:

```text
python -m unittest discover -s tests -p "test_sft_*.py"
```

Verify future-result sentinel isolation; source overlap; exact Unicode arguments;
empty/clarification terminal rules; missing pairings; target/padding/EOS masks;
context overflow; frozen base/adapter gradients; checkpoint identity; deterministic
coverage-aware selection; resumed coverage; rejection of ineligible exports; and
merged reload. Verify accumulation gradient equivalence across 1x16 and 4x4 using
unequal completion lengths and disabled dropout. Separately enable actual tokenizer/GPU/supplied-data
checks and record the real assets/hardware rather than substituting fake responses.

## Assess the merged snapshot

Point feature 002's planner setting at `<experiment>/merged_fp16`; preserve existing
ASR/runtime settings and use a fixed recorded validation selection. Use its eventual
implemented CLI, recording the exact invocation when available. Cover lookup-dependent,
empty, missing-information and historical-audio cases where the data provides them.

Run one competition assessment of the selected export with actual execution and
full audio timing. Report available scores, category denominators and every failure;
do not manufacture hashes/scores. Existing valid pretrained experiment evidence may
be reused; a broad comparison search is unnecessary.

Record exact commands/status, revision, dataset IDs/digests, software/GPU, actual
source/row counts, coverage/epochs, checkpoint NLLs and export/runtime evidence.
Training completion is separate from feature 002, offline Docker and A30 acceptance;
leave unrun gates pending.
