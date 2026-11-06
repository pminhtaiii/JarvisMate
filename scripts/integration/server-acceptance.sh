#!/usr/bin/env bash
# GPU-server acceptance for specs/002-docker-integration T024/T025.
# Run on the Linux GPU server from the repo root; never on a laptop without a GPU.
#
#   scripts/integration/server-acceptance.sh \
#     --models /abs/models --data /abs/data --config /abs/config --output /abs/output \
#     --gpu 0 [--second-planner /models/planner-b] [--image lifemate-integration:dev]
#
# /abs/config must hold integration.toml (paths under /models, /data, /config, /output)
# and its selection file. Evidence (image digest, resolved packages, nvidia-smi, every
# command and exit code, manifests) is written under <output>/evidence-<UTC timestamp>/.
# Exit codes are recorded, not hidden: an incomplete run is evidence, not success.
set -euo pipefail

image="lifemate-integration:dev"
second_planner=""
gpu=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --models) models="$2"; shift 2 ;;
    --data) data="$2"; shift 2 ;;
    --config) config="$2"; shift 2 ;;
    --output) output="$2"; shift 2 ;;
    --gpu) gpu="$2"; shift 2 ;;
    --second-planner) second_planner="$2"; shift 2 ;;
    --image) image="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
for name in models data config output gpu; do
  if [[ -z "${!name:-}" ]]; then echo "Missing --$name" >&2; exit 2; fi
done
for path in "$models" "$data" "$config" "$output"; do
  [[ "$path" = /* ]] || { echo "Paths must be absolute: $path" >&2; exit 2; }
done
[[ -f "$config/integration.toml" ]] || { echo "Missing $config/integration.toml" >&2; exit 2; }

evidence="$output/evidence-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$evidence"
log="$evidence/commands.log"

record() {  # record <label> <command...>: run, keep stdout/stderr and the exit code.
  local label="$1"; shift
  printf '\n$ %s\n' "$*" >>"$log"
  set +e
  "$@" >"$evidence/$label.out" 2>"$evidence/$label.err"
  local code=$?
  set -e
  echo "exit=$code" >>"$log"
  echo "$label exit=$code"
  return 0
}

mounts=(--mount "type=bind,src=$models,dst=/models,readonly"
        --mount "type=bind,src=$data,dst=/data,readonly"
        --mount "type=bind,src=$config,dst=/config,readonly"
        --mount "type=bind,src=$output,dst=/output")
run=(docker run --rm --init --network none --gpus "\"device=$gpu\"" --user "$(id -u):$(id -g)" "${mounts[@]}")

git rev-parse HEAD >"$evidence/revision.txt"
git status --porcelain >"$evidence/worktree-status.txt"
record nvidia-smi nvidia-smi --query-gpu=index,uuid,name,driver_version,memory.total --format=csv
record docker-version docker version
record build docker build -t "$image" .
docker image inspect --format '{{.Id}} {{json .RepoDigests}}' "$image" >"$evidence/image-id.txt"
record packages docker run --rm --network none --entrypoint pip "$image" freeze
record offline-imports docker run --rm --network none --entrypoint python "$image" -c \
  "import torch, transformers, lmformatenforcer, lifemate.integration; print(torch.__version__, torch.version.cuda)"
record gpu-visible "${run[@]}" --entrypoint python "$image" -c \
  "import torch; print(torch.cuda.is_available(), torch.cuda.device_count(), torch.cuda.get_device_name(0))"

# T024: preflight then the configured run, fully offline with read-only inputs.
record check-config "${run[@]}" "$image" --config /config/integration.toml --check-config
record run-primary "${run[@]}" "$image" --config /config/integration.toml

# T025: the same image with a second compatible planner snapshot, no source/image change.
if [[ -n "$second_planner" ]]; then
  record run-second "${run[@]}" "$image" --config /config/integration.toml --planner-model "$second_planner"
fi

echo "Evidence: $evidence"
echo "Record the outcomes, image id, packages and manifests in specs/002-docker-integration/quickstart.md."
