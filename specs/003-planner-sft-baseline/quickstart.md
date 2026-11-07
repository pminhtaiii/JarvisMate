# Validation guide

**Status**: Commands implemented. No real training, NF4, GPU or runtime acceptance has run;
see [recorded evidence](#recorded-evidence).

## Prerequisites

Linux CUDA, Python >=3.11, one RTX 5090 or H200, permitted local Train and catalog
files (plus a labeled validation file only for `validation_mode = "separate"`), pinned
local base snapshot. Resolve the training extra against
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

Copy `configs/planner-sft.example.toml` to an ignored local
file. Set paths/roles; start microbatch 1 and accumulation 16. Explicit larger
microbatch must preserve product 16. No new holdout is created. Choose the
[validation mode](contracts/training.md#validation-modes) explicitly: the example ships
with `validation_mode = "none"`.

### 100% Train, no validation (`validation_mode = "none"`)

The supplied dataset v3.2.0 has no labeled validation file, so this is the mode that can
run on it. Keep `validation_mode = "none"` and leave the three `validation_*` keys absent.
A reviewed resolution for `train_1696` is still required; this mode does not bypass the audit.

```text
python -m lifemate.sft preflight --config <local.toml>
python -m lifemate.sft prepare   --config <local.toml>
python -m lifemate.sft train     --config <local.toml> --smoke   # 2 isolated NF4 updates under <experiment>/smoke
python -m lifemate.sft train     --config <local.toml>
python -m lifemate.sft train     --config <local.toml> --resume <experiment>/checkpoints/step-0N00   # only after an interruption
python -m lifemate.sft export    --config <local.toml> --selection <experiment>/selection.json
```

Expected: `preflight` and `prepare` report `validation_mode: none` and overlap
`not_applicable`; `sft/` holds `train.jsonl`, `audit.jsonl` and the manifest, with no
validation file. Smoke writes `smoke/smoke_report.json` with `validation_mode: none` and
`frozen_unchanged: true`. Train commits checkpoints at 100, 200, 300, 400 and 500, computes
no NLL, and writes `selection.json` with `mode: final_update` and `selected_update: 500`.
A run stopped before update 500 writes no selection; resume from the latest checkpoint. If
it stopped after committing step 500, `--resume .../step-0500` runs no further update and selects it.
Export rechecks the final checkpoint's digests, coverage and mode, and its manifest has
no `validation_nll`. `diagnose` refuses this mode (`SFT_DIAGNOSTICS`) rather than compare
on Train prompts.

Limitation: without validation there is no checkpoint-selection signal and no held-out
metric before the runtime assessment. Training loss on fitted rows is not a quality
estimate. Overfitting after the first full epoch (305 updates for 4,865 rows) is not
detected here.

### Separate validation (`validation_mode = "separate"`)

Set `validation_mode = "separate"` (or omit it) and set the three `validation_*` keys.

```text
python -m lifemate.sft preflight --config <local.toml>
python -m lifemate.sft prepare --config <local.toml>
python -m lifemate.sft train --config <local.toml> --smoke   # short isolated NF4 feasibility run
python -m lifemate.sft train --config <local.toml>
python -m lifemate.sft export --config <local.toml> --selection <experiment>/selection.json
python -m lifemate.sft diagnose --config <local.toml> --selection <experiment>/selection.json
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

From `python/tests`, with `PYTHONPATH=../src` when the package is not installed:

```text
python -m unittest discover -s . -p "test_sft_*.py"
```

Tiny-model cases need torch, transformers and peft. `LIFEMATE_NATIVE_TOKENIZER` enables
actual-tokenizer and merge cases (tokenizer files suffice), `LIFEMATE_SFT_TRAIN` the
supplied-source accounting, and `LIFEMATE_SFT_GPU_BASE` the real NF4 smoke on a GPU host.

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

## Recorded evidence

Measured 2026-11-07 on a Windows CPU-only machine, in a scratch venv with torch 2.9.0+cpu,
transformers 4.57.1 and peft from the `training` ranges. bitsandbytes was not installed.

| Evidence | Command or input | Result |
|---|---|---|
| Standard library only | `python -m unittest discover -s . -p "test_*.py"` from `python/tests` | 263 run, OK, 41 skipped |
| With model libraries | Same, with `LIFEMATE_NATIVE_TOKENIZER` = Qwen3-4B-Instruct-2507 tokenizer files | 263 run, OK, 5 skipped |
| Supplied Train accounting | `LIFEMATE_SFT_TRAIN` = dataset v3.2.0 Train, `max_new_tokens` 512, actual tokenizer | 1545 sources: 1544 with rows, 1 unresolved; 4865 rows (3538 calls including 217 clarifications, 1327 finishes); prompt mean 5309, max 9255; target mean 25, max 103; no overflow |
| Flagged source | Same | `train_1696` decision 2, `UNGROUNDED_ID`: gold invents `chat_6142`, and its result says the chat was not found |
| Grammar admits gold | Scratch walk through `NativeConstraint`, one target per tool plus finish | 147 of 147 accepted, then EOS allowed |
| CLI flow | Scratch copy holding out the last 20 Train rows as a stand-in validation | `preflight` passed, `prepare` blocked until `train_1696` was resolved, then `ready` with 4820 and 45 rows; `train` failed with `MODEL_UNAVAILABLE` for no GPU |

No-validation mode (`validation_mode = "none"`), measured 2026-11-08 on the same Windows CPU-only
machine. The repository venv had torch 2.9.0+cpu and transformers 4.57.1; peft 0.21.2 and
accelerate 1.15.0 were installed into a scratch directory on `PYTHONPATH`. bitsandbytes was not
installed, and no tokenizer, supplied-data or GPU variable was set.

| Evidence | Command or input | Result |
|---|---|---|
| Standard library plus torch, no peft | `python -m unittest discover -s . -p "test_*.py"` from `python/tests` | 296 run, OK, 55 skipped |
| SFT suite with model libraries | `python -m unittest discover -s . -p "test_sft_*.py"` | 129 run, 7 skipped; 2 failures in `TrainOnlyExportTests` (an unregistered `SFT_DIAGNOSTICS` code and a fixture without a covered non-final update), both fixed afterwards |
| After those fixes | `python -m unittest -v test_sft_export.TrainOnlyExportTests` | 6 run, OK |

The full model-library suite was not rerun after the two fixes. The controlled no-validation
cases use the CPU tiny model and the character tokenizer. They show the mode's config,
prepare, schedule, final selection, resume and export rules. They are no evidence of NF4
behaviour, memory fit or model quality, and the NF4 smoke without validation has not run.

The stand-in split only exercised the flow and is not a validation set. Supplied token counts
used tokenizer files with a header-only weights file, so base-snapshot identity is unmeasured.

Consequences for planning, from those counts rather than from any training run: with all
Train rows, one epoch needs 305 updates, so in mode `separate` only updates 400 and 500 can be
selected. Updates 100 to 300 remain diagnostics. Dataset v3.2.0 ships Train and unlabeled
public test only: no separate validation file exists. Mode `separate` needs one supplied
before `prepare` can be ready; mode `none` trains on all approved Train sources and selects
update 500 (about 1.64 epochs at 4,865 rows).

LMFE rejects a natural token that spans an escaped quote and an adjacent escape or string end,
such as `\"\`. No Train gold argument contains a quote, backslash, tab or newline, so no
training target is affected. Whether decoding reaches such text through other tokens is untested.

Controlled CPU cases exercise real LoRA, backward, 1x16/4x4 gradient equivalence, exactly equal
adapter weights after resume and an offline merged reload on a random two-layer Qwen3. They do not establish NF4
behaviour, memory fit, adapter-versus-merged drift on the real model, quality or latency.

### Pending on the GPU host

T016 NF4 smoke and environment lock, T017 full run, T020 drift diagnostics, T021 validation
assessment and T022 Docker/A30 gates. Record commands, identities and results here. In mode
`none`, T020 has no validation prompts and is not run by `diagnose`; the merged export's
reload and protocol checks still run during `export`.
