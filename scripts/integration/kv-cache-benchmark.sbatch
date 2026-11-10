#!/usr/bin/env bash
# Submit explicitly from a separate branch-009 checkout on an allocated UIT GPU.
# Resource/partition/GRES flags are supplied to sbatch by the operator.
# Arguments: existing audio TOML, smoke16 ID file, NEW absolute run root, Python.
set -euo pipefail
[[ $# -eq 4 ]] || { echo 'Need: CONFIG IDS NEW_RUN_ROOT PYTHON' >&2; exit 2; }
cd "${SLURM_SUBMIT_DIR:?Submit from the branch-009 repository root}"
export PYTHONPATH="$PWD/python/src"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
[[ ! -e "$3" ]] || { echo 'Run root already exists; refusing to resume/overwrite' >&2; exit 2; }
git rev-parse HEAD
nvidia-smi
exec "$4" -m lifemate.kv_benchmark --config "$1" --ids "$2" --run-root "$3"
