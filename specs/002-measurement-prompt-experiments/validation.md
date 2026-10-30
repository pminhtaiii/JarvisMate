# Measurement and prompt-experiments validation

**Recorded**: 2026-10-30. **Branch**: `feat/measurement-foundation`.
**Revision**: `baa4f4b176d290934a3872b3ad2447d32b91a4dc`.
**Evidence level**: controlled unittest suite executed and passing. No model, GPU,
competition data, or evaluator was available in this environment; real-instrumented,
prompt-arm and failure/compatibility checks below are recorded as NOT RUN with the
reason, not inferred from source inspection or from the controlled pass.

## Controlled acceptance (executed)

Command, run from the repository root, package not installed:

```powershell
$env:PYTHONPATH = 'python/src'
python -m unittest discover -s python/tests -p 'test_metrics.py'
python -m unittest discover -s python/tests -p 'test_reporting.py'
python -m unittest discover -s python/tests -p 'test_prompt_profiles.py'
python -m unittest discover -s python/tests -p 'test_agent.py'
python -m unittest discover -s python/tests -p 'test_artifacts.py'
python -m unittest discover -s python/tests -p 'test_cli.py'
```

Interpreter: Python 3.13.1. Platform: Windows-11-10.0.26200. Exit status: `0` for every
command above. Results:

| File | Tests | Result |
|---|---|---|
| `test_metrics.py` | 20 | OK |
| `test_reporting.py` | 44 | OK |
| `test_prompt_profiles.py` | 35 | OK |
| `test_agent.py` | 15 | OK |
| `test_artifacts.py` | 25 | OK |
| `test_cli.py` | 32 | OK |

Also run, outside the quickstart's explicit list, for full-suite regression on files
this feature touches or that exercise the same manifest/checkpoint surface:

| File | Tests | Result |
|---|---|---|
| `test_checkpoint.py` | 6 | OK |
| `test_dataset.py` | 12 (2 skipped) | OK |
| `test_runtime.py` | 5 | OK |
| `test_selection.py` | 5 | OK |
| `test_audio.py` | 13 | OK |
| `test_inference.py` | 25 | OK |

237 tests ran, 237 passed, 2 skipped (real-sample-only cases inside `test_dataset.py`
that require `LIFEMATE_REAL_*` data). `test_real_samples.py` was not invoked: it needs
`LIFEMATE_REAL_DATA_ROOT`/`LIFEMATE_REAL_SAMPLE_ID`/`LIFEMATE_RUNTIME_DIR`, none of which
exist in this environment. This confirms the controlled behaviors in
`contracts/measurement.md`, `contracts/prompts.md`, and `contracts/experiments.md`
against fixtures only: nested/partial spans, failure timing, offload accounting,
trace/output-overhead crossing 30s while the loop succeeds, I/O loss, generous-deadline
prediction parity, nearest-rank distributions on small/empty populations, unknown
versions, invalid artifacts, incomplete/imported runs, incompatible factors, baseline
profile-message equivalence, scoped example IDs, strict-prefix rejection, fit/validation
exclusion, frozen hashes and overflow. It does not measure real latency, token rates,
or model accuracy.

Updated after addressing CodeRabbit's review of [PR #8](https://github.com/pminhtaiii/JarvisMate/pull/8):
all 24 findings from the first review (7 Major, 17 Minor, including 4 only in the
review summary, not posted as separate inline comments) were fixed, each with a
new or extended regression test. A second review round after that push (triggered
by an `@coderabbitai review` comment) posted 6 more findings (1 Major: an
unterminated final row in `predictions.partial.jsonl` could block reporting; 5
Minor: a non-finite aggregate token rate, a hard-link publish failing on
filesystems without hard-link support, a same-prompt comparison passing
validation, and a dataset-mismatch test that didn't actually exercise its own
check). All 5 of those with a concrete code fix were fixed and tested.

One finding from that second round is **not** fixed as literally suggested:
CodeRabbit's note on `cli.py` that the run path trusts a bundle's copied
`audit_schema_version`/`source_dataset_sha256`/`catalog_sha256`/`partition_sha256`
fields without re-verifying examples against Train labels. Per
[contracts/prompts.md](contracts/prompts.md), re-verification against Train labels
belongs only to the offline `audit-examples` command — "Parsing Train labels
belongs only to this separate offline command... never feeds this raw labeled row
to inference" — and the run path is specified to verify only "these identities
[the four hashes] against the visible inputs," which is what it does. Re-checking
targets at run time would require the run path to read Train labels, contradicting
that contract. This is a cooperative-identity check, like every other hash
comparison in this codebase (dataset/catalog/partition digests), not a
cryptographic guarantee against a hand-forged bundle; closing that gap for real
would need an external signature mechanism outside this feature's scope.

## Real instrumented control, prompt arms, failure/compatibility checks — NOT RUN

[quickstart.md](quickstart.md) also lists a real `lifemate run`/`report` control, an
instruction (`precise-v1`) and few-shot arm with `audit-examples`, and synthetic
boundary checks for budget/import/digest rejection. None of these were executed here:

- No `--data-root` with the official Train split, catalog, or audio exists in this
  environment; `check-data`/`run` were not invoked.
- No local planner/ASR model snapshot is provisioned, so `--planner-model`/`--asr-model`
  and any `--device cuda` run are unavailable.
- No evaluator-produced `--evaluation-file` exists, so `report`/`compare-runs`
  correctness classification was not exercised beyond the `not_evaluated`/fixture paths
  already covered by `test_cli.py`/`test_reporting.py`.
- No A30 (or any GPU) hardware was available to this session.

## Frozen fit/validation selection and experiment hypothesis

No frozen partition manifest exists yet in this repository (checked: no file matching
`*partition*manifest*`, no JSON containing the roadmap's seed `20261027`). Per the
[roadmap](../../context/roadmap.md#stage-2-evaluation-on-a-held-out-part-of-train), that
selection — an approximately 80/20 fit/validation split of **Train** by conversation
group, seed `20261027`, with smoke IDs `train_1748`-`train_1751` assigned to the fit
side — must be created and frozen (source hashes, grouping rule/version, seed, group and
sample IDs, counts) before any instruction or few-shot arm may select demonstrations or
report a validation-backed result. That creation is development-validation work outside
this feature's code change and is not performed by this record.

**Experiment hypothesis** (per [spec.md](spec.md) FR-012, SC-003, SC-006 and
[contracts/experiments.md](contracts/experiments.md)): holding samples, models, ASR,
runtime, decoding, limits and hardware fixed, (1) the `precise-v1` instruction profile
and (2) a fit-only few-shot bundle each change closed-loop tool-call correctness and/or
latency versus the `baseline` profile, evaluated as two single-factor arms against the
same frozen validation IDs and the same audio control — never combined in one run, and
never promoted on JSON validity or latency alone without the paired correctness/latency
classification in `contracts/experiments.md`.

**Commands to run once data/hardware/evaluator are authorized and available** (frozen
IDs substituted for `$validationIds`, exact command text from [quickstart.md](quickstart.md)):

```powershell
lifemate run --data-root $dataRoot --runtime-dir $runtimeDir --split train `
  --input-mode audio @idOptions --planner-model $plannerModel --asr-model $asrModel `
  --device cuda --sample-timeout-seconds 30 --prompt-profile baseline `
  --trace-payloads --run-dir .agent-work/lifemate-runs/control-audio
lifemate run ... --prompt-profile precise-v1 --run-dir .agent-work/lifemate-runs/instructions-audio
lifemate audit-examples --bundle PATH --partition-manifest PATH --train-jsonl PATH --catalog PATH --output AUDITED_BUNDLE
lifemate run ... --prompt-profile baseline --few-shot-bundle AUDITED_BUNDLE `
  --partition-manifest PATH --few-shot-token-budget 1024 --run-dir .agent-work/lifemate-runs/fewshot-audio
lifemate report --run-dir .agent-work/lifemate-runs/control-audio --evaluation-file BASELINE_EVAL_PATH
lifemate report --run-dir .agent-work/lifemate-runs/instructions-audio --evaluation-file CANDIDATE_EVAL_PATH
lifemate compare-runs --baseline-run .agent-work/lifemate-runs/control-audio `
  --candidate-run .agent-work/lifemate-runs/instructions-audio --factor instructions `
  --baseline-evaluation BASELINE_EVAL_PATH --candidate-evaluation CANDIDATE_EVAL_PATH `
  --output-dir .agent-work/lifemate-runs/instructions-comparison
```

Run each arm as three fresh paired replicates per
[contracts/experiments.md](contracts/experiments.md) before any latency acceptance
claim. Until the above is actually executed, no instruction/few-shot comparison,
latency budget compliance, or promotion decision is established by this document.
