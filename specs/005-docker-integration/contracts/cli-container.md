# CLI and Container Contract

Commands/settings below are proposed, not available yet. Existing
`python -m lifemate run` remains the legacy comparison path.

## Command

```text
python -m lifemate.integration --config PATH [--check-config]
  [--asr-model PATH] [--planner-model PATH] [--device DEVICE]
```

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
mode = "audio"
sample_ids_file = "/config/selection.txt"

[output]
root = "/output"
debug_payloads = false
```

Both models support validated explicit device/dtype/offload changes. Host GPU IDs
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
docker run --rm --network none --gpus '"device=0"' \
  --mount type=bind,src=/absolute/models,dst=/models,readonly \
  --mount type=bind,src=/absolute/data,dst=/data,readonly \
  --mount type=bind,src=/absolute/config,dst=/config,readonly \
  --mount type=bind,src=/absolute/output,dst=/output \
  lifemate-integration:dev --config /config/integration.toml
```

Replace host index with the chosen actual index/UUID. One selected GPU is the initial
topology; no automatic sharding/distributed execution. Hardware settings can change
for another host but must be recorded and revalidated. CPU diagnostics do not establish
GPU deadline performance.

## Artifacts

Run root contains effective config/provenance, attempt ledger, bounded traces,
accepted sample rows, partial predictions and report. Complete publication requires
exact selected-ID coverage without failures/duplicates. Resume rejects different
models/templates/config/data and never replays failed/uncertain samples. Submission
rows retain the organizer schema exactly.
