# CLI and Container Contract

Implemented in `python/src/lifemate/integration.py` and `configuration.py`; the image
and GPU behaviour are not yet built or measured (T024/T025). Existing
`python -m lifemate run` remains the legacy comparison path.

## Command

```text
python -m lifemate.integration --config PATH [--check-config] [--resume]
  [--asr-model PATH] [--planner-model PATH] [--device DEVICE]
```

`--device` overrides both models' device. `--resume` continues the run already in
`output.root`; without it an existing journal is refused. Exit codes: `0` complete
coverage, `1` incomplete run (any failed/timeout/uncertain/unattempted ID, recovery or
journal failure), `2` invalid arguments/configuration/inputs or rejected resume (no
worker, model or ToolEnv was started).

Strict preflight precedes models/environments. CLI overrides only known TOML fields;
unknown/invalid/contradictory settings fail clearly. `--check-config` validates paths,
metadata/limits/eligibility without inference, tools or downloads; it does not prove
memory fit. Actual model load/template smoke precedes worker-ready acknowledgement.
Exit zero means complete runtime coverage, not correct gold predictions. Invalid
configuration, failed/timeout attempts, incomplete output or recovery failure exit nonzero.

## TOML v1 (example schema)

```toml
schema_version = 1

[asr]
backend = "whisper"
model_path = "/models/asr"
device = "cuda:0"
dtype = "float16"
offload = false

[planner]
backend = "qwen3"
protocol = "qwen-native-v1"
model_path = "/models/planner"
device = "cuda:0"
dtype = "float16"
offload = false
context_tokens = 16384
max_new_tokens = 512

[execution]
timeout_seconds = 30
max_steps = 16
startup_timeout_seconds = 300
recovery_attempts = 1
seed = 42

[data]
root = "/data"
split = "train"
mode = "audio"                                # audio | transcript (Train-only diagnostic)
runtime_dir = "/opt/lifemate/tools/train"     # split-matched runtime; tools/test for public_test
sample_ids_file = "/config/selection.txt"     # or: select_all = true (exactly one)

[output]
root = "/output/run-001"
debug_payloads = false
```

Accepted values: devices `cpu`, `cuda`, `cuda:N`; dtypes `float32`, `float16` (CUDA
only), `bfloat16`; offload requires CUDA; `0 < max_new_tokens < context_tokens <= 16384`;
`timeout_seconds` in `(0, 30]`; `max_steps` 1..64; `startup_timeout_seconds` in
`(0, 3600]`; `recovery_attempts` 0 or 1 restart per worker loss; 32-bit `seed`.
Relative paths resolve against the TOML file's directory. The documented example is
`configs/integration.example.toml`. Both models support validated explicit
device/dtype/offload changes. Host GPU IDs
are not container ordinals: after selecting one host GPU, `cuda:0` names the visible
device. Example settings are not measured speed/memory defaults. Context limits reserve
output tokens; fail rather than silently truncating required evidence. Strict model/
context/parameter checks apply to competition acceptance; the integration maximum
deadline is always 30 seconds.

## Packaging

Build installs pinned inference dependencies/package and organizer runtime(s); routing
remains split-matched. Resolve CUDA base digest/dependency pins with an actual build.
`.dockerignore` excludes models, datasets, weights, runs, training, secrets and git;
explicitly include required runtime code rather than unrelated uploaded tool copies.

Mount `/models`, `/data`, `/config` read-only and `/output` writable. Snapshots must
include all tokenizer/processor/weight files. Enforce local-only loads and offline
HF/Transformers settings. Build may use network; runtime cannot download/call services.

```bash
docker run --rm --init --network none --gpus '"device=0"' --user "$(id -u):$(id -g)" \
  --mount type=bind,src=/absolute/models,dst=/models,readonly \
  --mount type=bind,src=/absolute/data,dst=/data,readonly \
  --mount type=bind,src=/absolute/config,dst=/config,readonly \
  --mount type=bind,src=/absolute/output,dst=/output \
  lifemate-integration:dev --config /config/integration.toml
```

Replace host index with the chosen actual index/UUID. `--init` reaps the supervisor's
worker processes when the CLI is PID 1. The image runs as uid 1000 unless `--user` is
given; `/output` must be writable by that user.
`scripts/integration/server-acceptance.sh` builds the image, runs the offline checks
and configured runs on the GPU server and keeps their evidence. One selected GPU is the initial
topology; no automatic sharding/distributed execution. Hardware settings can change
for another host but must be recorded and revalidated. CPU diagnostics do not establish
GPU deadline performance.

## Artifacts

Run root (`output.root`): `effective-config.json`; `manifest.json` (identity, host and
worker hardware, startup/recovery/packaging/total wall time, report); `journal.jsonl`
(checksummed reservations and terminal records); `staging/<attempt>/` (accepted
attempts' trace, outcome, prediction); `quarantine/<attempt>/` (unaccepted);
`workers/gen-N.{lock,log}`; `predictions.partial.jsonl` (accepted rows); and, only for
complete coverage, `predictions.jsonl`. Complete publication requires
exact selected-ID coverage without failures/duplicates. Resume rejects different
models/templates/config/data and never replays failed/uncertain samples. Submission
rows retain the organizer schema exactly.

The attempt journal includes fsynced pre-dispatch reservations. Resume requires
exclusive run ownership, confirmed prior-worker termination and a valid journal;
reserved-but-not-durably-accepted IDs remain uncertain and cannot be rerun. Staged
files or missing terminal records never establish that a sample is safe to dispatch.
