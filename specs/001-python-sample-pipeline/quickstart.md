# Quickstart validation guide

**Status**: Proposed commands for the implementation. No `lifemate` CLI exists yet;
these are acceptance steps, not evidence of already working inference.

## 1. Prepare the local subset layout

Keep `sample/` ignored and preserve organizer source/catalog contents. The runtime
needs the following layout even though its code can live separately in `tools/train/`:

```text
sample/train/
  train.jsonl
  train_tools_catalog.json
  audio/train_1748/...
  audio/train_1749/...
  audio/train_1750/...
  audio/train_1751/...
  train_environment/<sample-id>/state.json
```

From the repository root, add a directory alias for the expected spelling, leaving
the uploaded environment directory intact, and place the unchanged catalog alongside
the split JSONL. If the correctly spelled path already exists, verify its intended
layout instead of replacing it. These commands are not run by `check-data` or this
planning task. The alias target must resolve inside the same split directory.

```powershell
$dataSplit = Join-Path (Get-Location) 'sample/train'
Test-Path -LiteralPath (Join-Path $dataSplit 'train_environment')
# Only if the correctly spelled target is absent and train_enviroment exists:
New-Item -ItemType Junction -Path (Join-Path $dataSplit 'train_environment') -Target (Join-Path $dataSplit 'train_enviroment')
Copy-Item -LiteralPath tools/train_tools_catalog.json -Destination (Join-Path $dataSplit 'train_tools_catalog.json')
```

Do not inspect or copy hidden environment contents. The official runtime opens its
own state. On Linux, use a contained directory symlink instead of a Windows junction.
If alias creation is unavailable, report the setup blocker rather than copying or
renaming original environment data. Later public-test preparation follows its layout,
catalog, and `tools/test` runtime; it is not necessary for the initial training smoke.

## 2. Install and run GPU-free checks

Requires Python 3.11+. The existing root Node tooling remains separate.

```powershell
python -m venv .agent-work/python-venv
& ./.agent-work/python-venv/Scripts/python.exe -m pip install -e ./python
& ./.agent-work/python-venv/Scripts/python.exe -m unittest discover -s python/tests -p 'test_*.py'
```

Default tests require no weights or GPU. Real-data checks skip with an explicit reason
unless opted in. Test controlled responses through injected interfaces; do not expose
a fake prediction backend as an ordinary production CLI option.

```powershell
& ./.agent-work/python-venv/Scripts/python.exe -m lifemate check-data --data-root sample --split train --runtime-dir tools/train --input-mode transcript --id train_1748
& ./.agent-work/python-venv/Scripts/python.exe -m lifemate check-data --data-root sample --split train --runtime-dir tools/train --input-mode audio --id train_1748 --id train_1749 --id train_1750 --id train_1751
```

Expected: exit 0 with explicit IDs/count, valid split catalog, and subset scope.
The command loads neither models nor a ToolEnv. A wrong environment spelling or missing
catalog fails clearly; missing assets outside the selected IDs do not block the run.

## 3. Opt in to the supplied-runtime smoke

```powershell
$env:LIFEMATE_REAL_DATA_ROOT = (Join-Path (Get-Location) 'sample')
$env:LIFEMATE_REAL_SAMPLE_ID = 'train_1748'
$env:LIFEMATE_RUNTIME_DIR = (Join-Path (Get-Location) 'tools/train')
& ./.agent-work/python-venv/Scripts/python.exe -m unittest discover -s python/tests -p 'test_real_samples.py'
```

Expected: one real ToolEnv, an allowed read-only tool call chosen from the sample's
catalog with valid arguments, an authoritative call log/hash, and a terminal trace.
Use controlled decisions and observations, without labels or direct environment reads.
This establishes integration only. It is not a real planner/ASR result or model accuracy.

## 4. Real planner transcript checkpoint (external prerequisites)

First provision suitable compute and local model snapshots. The teammate GPU is not
yet available. Install the optional inference dependencies during environment setup;
runtime inference must not download anything. Record exact tested package/snapshot versions.

```powershell
& ./.agent-work/python-venv/Scripts/python.exe -m pip install -e './python[inference]'
& ./.agent-work/python-venv/Scripts/python.exe -m lifemate run --data-root sample --split train --runtime-dir tools/train --input-mode transcript --id train_1748 --planner-model .agent-work/models/qwen3-4b-instruct-2507 --device cuda --sample-timeout-seconds 120 --trace-payloads --run-dir .agent-work/lifemate-runs/train-1748-text
```

The 120-second development budget is explicit and does not establish the 30-second
competition limit. Use a fresh run name each time. After one sample completes, repeat
with all four explicit IDs. Inspect calls and training references separately; never
give gold actions/results to the planner. A runnable model can still act incorrectly:
record those failures without claiming reliable accuracy.

Expected artifacts and completion rules are in [contracts/artifacts.md](contracts/artifacts.md).
Keep `predictions.jsonl` separate from traces and inspect the manifest's subset scope.

## 5. Audio checkpoint on the same IDs

```powershell
& ./.agent-work/python-venv/Scripts/python.exe -m lifemate run --data-root sample --split train --runtime-dir tools/train --input-mode audio --id train_1748 --id train_1749 --id train_1750 --id train_1751 --planner-model .agent-work/models/qwen3-4b-instruct-2507 --asr-model .agent-work/models/phowhisper-small --device cuda --sample-timeout-seconds 120 --trace-payloads --run-dir .agent-work/lifemate-runs/four-train-audio
```

Run a separate experiment with a local Whisper-small snapshot using identical sample
selection and planner settings. Only the selected ASR is loaded per run. Transcribe
current and previous user audio; supplied transcript fallback is a failure. Compare
ASR text and tool paths with the transcript-mode run. Keep model accuracy, execution
success, and deadline compliance as distinct outcomes.

## 6. Failure and evidence checks

- Inject an unrecoverable second-sample failure: third sample never opens; exit is
  nonzero; first row remains in partial output; failure trace and failed manifest remain.
- Test an unavailable tool and invalid arguments: validation feedback is traced before
  dispatch; actual attempted environment calls still appear in its authoritative log.
- Test missing information and unsupported requests: both produce legitimate outcomes,
  distinct from execution failure; previous actions are preserved when asking for info.
- Test exhausted bounds, missing weights, context overflow, and trace/output I/O failure.
- Assert exact output keys, selected IDs/order/count, hashes from the environment,
  one environment per sample, no label leakage, and no history replay.
- Record command, exit status, revision, dirty state, split/IDs, models/settings,
  timings, paths, and observed results in the run manifest and final validation record.

Completion means the relevant acceptance checks actually ran. GPU-free completion
alone leaves the real-model tasks open. A four-sample result is not a full submission;
complete data, final timing, model eligibility, replay, and Docker checks are later gates.
