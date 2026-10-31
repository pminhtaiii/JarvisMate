# Validation quickstart

This is an implementation acceptance guide. Native protocol/training commands below
are planned and will not work until their tasks are implemented. No model experiment
or benchmark result is claimed by creating this file.

## Prerequisites

- Python 3.11+, accepted baseline installation and split-matched Train runtime.
- Local eligible Qwen3-4B-Instruct-2507/tokenizer and selected ASR checkpoints.
- Train JSONL/catalog/audio available locally; tools access environment state only.
- Feature 002 measurement/reporting accepted before comparable full-attempt reports.
- Compatible isolated training lock and measured GPU capacity before fitting.
- Evaluator-provided scoring evidence before any score-based promotion.

Run commands from `python/`. Paths below are example local paths to substitute;
never commit dataset/debug payloads or checkpoint weights.

## 1. Focused protocol checks

```powershell
python -m unittest discover -s tests -p test_qwen_protocol.py
python -m unittest discover -s tests -p test_inference.py
python -m unittest discover -s tests -p test_agent.py
python -m unittest discover -s tests -p test_checkpoint.py
python -m unittest discover -s tests -p test_cli.py
```

Require native rendering/tool whitelist, actual-tokenizer grammar/EOS tests with
local model assets explicitly enabled, strict malformed/multiple-call rejection,
token/time cuts, neutral finish and canonical executor parity. Mocked generation
does not establish actual tokenizer/LMFE compatibility. Include normal clarification,
empty gold, zero arguments, failed calls and selection-filter correction paths.

Implement `LIFEMATE_QWEN_TEST_MODEL` as the opt-in local tokenizer path for native
grammar checks; missing assets produce explicit skips, not acceptance evidence:

```powershell
$env:LIFEMATE_QWEN_TEST_MODEL = 'C:/lifemate-models/Qwen3-4B-Instruct-2507'
python -m unittest discover -s tests -p test_qwen_protocol.py
```

## 2. Freeze partition and compare protocols

Proposed partition command (CPU/data only; no training libraries or environment creation):

```powershell
python -m lifemate.training partition --data-root C:/lifemate-data --output ../.agent-work/lifemate-runs/native-sft/partition.json --seed 20261027 --validation-fraction 0.2
```

Review duplicate groups, fit-side smoke IDs and validation tool/behavior coverage.
Use all frozen validation IDs via repeated existing `--id` flags. The following
single-ID command illustrates syntax only; it is not acceptance coverage:

```powershell
lifemate run --data-root C:/lifemate-data --runtime-dir ../tools/train --split train --input-mode transcript --id train_0001 --planner-model C:/lifemate-models/Qwen3-4B-Instruct-2507 --device cuda --planner-protocol structured-v1 --trace-payloads --run-dir ../.agent-work/lifemate-runs/native-sft/structured-transcript
lifemate run --data-root C:/lifemate-data --runtime-dir ../tools/train --split train --input-mode transcript --id train_0001 --planner-model C:/lifemate-models/Qwen3-4B-Instruct-2507 --device cuda --planner-protocol qwen-native-v1 --trace-payloads --run-dir ../.agent-work/lifemate-runs/native-sft/native-transcript
```

Repeat on complete frozen validation in audio mode with `--asr-model` and fresh run
directories. Keep selection filter disabled and all other settings fixed. Use the
[feature 002 report guide](../002-measurement-prompt-experiments/quickstart.md) once
implemented, applying [this comparison policy](contracts/experiments.md). Missing
scoring/full timing remains unavailable. Record the SFT eligibility/error-analysis decision.

## 3. Export and audit

```powershell
python -m lifemate.training export --data-root C:/lifemate-data --partition ../.agent-work/lifemate-runs/native-sft/partition.json --base-model C:/lifemate-models/Qwen3-4B-Instruct-2507 --output ../.agent-work/lifemate-runs/native-sft/sft
python -m unittest discover -s tests -p test_training_data.py
```

Require zero future-result/mask/cross-partition leakage among accepted rows. Review
every exclusion category, lengths, tool distribution and policy-finish targets.
No hidden-state files or ToolEnv are accessed. Validation rows remain separate.

## 4. Fit-only smoke, then controlled training

Use a separate environment with the implemented exact `requirements-training.txt`.
Create a config conforming to [training contract](contracts/training.md); point its
fit rows to a tiny fit-only smoke artifact and output to a fresh directory first.

```powershell
python -m lifemate.training fit --config ../.agent-work/lifemate-runs/native-sft/smoke-config.json
python -m unittest discover -s tests -p test_training_fit.py
```

Require actual forward/backward/optimizer/save/reload, checked masks and memory at
accepted sequence lengths. Then run `fit` with a separately recorded full-fit config
only after eligibility/preflight passes. Smoke success is not accuracy evidence.

## 5. Merge, load and evaluate actual deployment

```powershell
python -m lifemate.training merge --base-model C:/lifemate-models/Qwen3-4B-Instruct-2507 --adapter ../.agent-work/lifemate-runs/native-sft/fit/checkpoint-final --output ../.agent-work/lifemate-runs/native-sft/deployment
```

In the pinned inference environment, run the same native validation commands using
the merged directory as `--planner-model`. Use actual checkpoint paths emitted by
the fit manifest, not an assumed winning epoch. Compare with unchanged native base,
report per-ID regressions, scores/availability and actual full timing. Verify offline
loading, deterministic reruns, context/parameter budgets and complete audio attempts
strictly below 30 seconds on A30 before promotion. Otherwise retain the base fallback.

After the comparator extension is implemented, compare both pairs using
`lifemate compare-runs --baseline-run PATH --candidate-run PATH --factor protocol
--output-dir PATH` for Stage A and `--factor planner-model` for tuned/base. Supply
`--baseline-evaluation` and `--candidate-evaluation` when evaluator files are available;
without them the output is diagnostic-only and cannot establish benchmark promotion.
