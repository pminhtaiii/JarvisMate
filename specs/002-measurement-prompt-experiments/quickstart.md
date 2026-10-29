# Validation guide (after implementation)

These are planned validation scenarios and proposed commands. None were executed
while writing this specification. New options/commands/tests do not exist yet.

## Prerequisites

Use the [Python setup](../../python/README.md) on the receiving machine. Controlled
tests need no GPU/models/competition data. Real runs need eligible local model
snapshots, the split-matched runtime, authorized visible audio, and a frozen Train
fit/validation manifest. Use selected validation IDs from that manifest; do not
replace them with the entire Train set or include example-source groups.

## Controlled acceptance

Run from repository root, using the project's installed Python environment:

```powershell
python -m unittest discover -s python/tests -p 'test_metrics.py'
python -m unittest discover -s python/tests -p 'test_reporting.py'
python -m unittest discover -s python/tests -p 'test_prompt_profiles.py'
python -m unittest discover -s python/tests -p 'test_agent.py'
python -m unittest discover -s python/tests -p 'test_artifacts.py'
python -m unittest discover -s python/tests -p 'test_cli.py'
```

Expected: exact fake-clock timings and nearest-rank percentiles; each selected ID
accounted for; failed attempts/imports/incomplete spans separated; unchanged baseline
predictions; no metric payload leakage; no models/ToolEnv in offline reporting.
Add checkpoint/provenance tests to the applicable existing suite as identified during
implementation. Cover unavailable adapters and output/trace failure independently.

## Real instrumented control

The following PowerShell skeleton assumes `$dataRoot`, `$runtimeDir`, `$plannerModel`,
`$asrModel`, and `$validationIds` are already set to real local paths/selected IDs.
The array must be expanded into repeated `--id` arguments, preserving dataset order.

```powershell
$idOptions = @()
foreach ($sampleId in $validationIds) { $idOptions += @('--id', $sampleId) }
lifemate run --data-root $dataRoot --runtime-dir $runtimeDir --split train `
  --input-mode audio @idOptions --planner-model $plannerModel --asr-model $asrModel `
  --device cuda --sample-timeout-seconds 30 --prompt-profile baseline `
  --trace-payloads --run-dir .agent-work/lifemate-runs/control-audio
lifemate report --run-dir .agent-work/lifemate-runs/control-audio
```

Choose a fresh run directory each time. Detailed traces are enabled for this baseline
per existing evaluation guidance. An incomplete run remains incomplete; report it
before changing continuation settings. Expect manifest, traces, durable predictions
when available, report.json/report.md and explicit correctness `not_evaluated`.
Startup time is separate; sample totals include output completion. Use A30 for final
budget evidence and record actual hardware/runtime. Transcribe audio history too.

## Prompt and few-shot arms

Repeat the same command into a fresh directory with exactly one changed factor:

- Instruction arm: `--prompt-profile precise-v1`, no bundle.
- Few-shot arm: `--prompt-profile baseline --few-shot-bundle PATH
  --partition-manifest PATH --few-shot-token-budget 1024`.

Select and review the 1-3 example bundle from the frozen fit partition only. Run the
separate `audit-examples` command specified in [prompts.md](contracts/prompts.md) to
verify exact source prefixes/targets and write the audited bundle used by inference.
Validate source/group hashes and strict prefixes. Invalid overlap, unknown partition, wrong
catalog, excess demonstration tokens or full-context overflow must fail explicitly.
No concrete bundle is supplied by this planning change. Run transcript diagnostics
separately with identical paired IDs; they do not demonstrate audio latency.

Attach separate evaluator-produced evidence matching the contract:

```powershell
lifemate report --run-dir .agent-work/lifemate-runs/control-audio --evaluation-file PATH
lifemate report --run-dir .agent-work/lifemate-runs/instructions-audio --evaluation-file PATH
lifemate compare-runs --baseline-run .agent-work/lifemate-runs/control-audio `
  --candidate-run .agent-work/lifemate-runs/instructions-audio --factor instructions `
  --baseline-evaluation BASELINE_EVAL_PATH --candidate-evaluation CANDIDATE_EVAL_PATH `
  --output-dir .agent-work/lifemate-runs/instructions-comparison
```

The evaluator is separate; its absence does not block latency reports, but it blocks
accuracy/promotion claims. Never pass labels to inference to obtain this evidence.

## Failure and compatibility checks

Using synthetic fixtures, verify a known total of exactly 30s is over budget; an
unknown total is not a pass; failed attempts remain in observed distributions;
an agent-loop-completed sample whose durable output finishes at/above 30 seconds
remains persisted under existing semantics but is flagged over budget; no
retroactive TIME_LIMIT or tool retry is introduced. Report regeneration may replace
only derived report files inside its source run, whereas comparison output must not
overlap either source.
imports have their original source run; a missing terminal span is partial. Reject
invalid metric versions/negative times, duplicate terminals, mismatched evaluation
digests and conflicting comparison factors. Verify strict resume rejects changed
profiles, examples, partition or budget; explicit mixed resume stays exploratory.

Use [experiments.md](contracts/experiments.md) for thresholds and three fresh paired
replicates when confirming harness latency. Record exact commands, IDs, revisions,
hardware, model/tokenizer identity, failures and limitations. Do not mark acceptance
complete without actual evidence; hard stuck-call termination remains outside scope.
