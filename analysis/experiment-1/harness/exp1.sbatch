#!/usr/bin/env bash
#SBATCH --job-name=lm011-skill-ablation
#SBATCH --ntasks=1
# Partition/GRES/account/QoS/time are explicit sbatch arguments; no auto submission.
set -euo pipefail
[[ $# -eq 2 ]] || { echo 'Need EXPERIMENT_ROOT PYTHON' >&2; exit 2; }
task_root="$(realpath "$1")"
python_exe="$2"  # Keep the venv path: realpath of its symlink could bypass the venv.
case "$task_root" in
  /datastore/binhvp/BuiTrongTan/tmp/*) ;;
  *) echo 'Experiment root must be under UIT tmp' >&2; exit 2 ;;
esac
[[ -x "$python_exe" ]] || { echo 'Python is not executable' >&2; exit 2; }
: "${SLURM_JOB_ID:?Run in an allocated Slurm job}"
: "${CUDA_VISIBLE_DEVICES:?Slurm must provide the GPU visibility}"
export PYTHONPATH="$task_root/src/python/src"
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export HF_HOME="$task_root/cache/huggingface" XDG_CACHE_HOME="$task_root/cache"
cd "$task_root"
verify_on_exit() {
  local prior_code=$? integrity_code
  trap - EXIT
  set +e
  "$python_exe" "$task_root/harness/prepare.py" verify --experiment "$task_root"
  integrity_code=$?
  if [[ "$prior_code" -ne 0 ]]; then exit "$prior_code"; fi
  exit "$integrity_code"
}
trap verify_on_exit EXIT
[[ ! -e "$task_root/evidence/slurm-hardware.txt" ]] || { echo 'Allocation evidence already exists' >&2; exit 2; }
nvidia-smi > "$task_root/evidence/slurm-hardware.txt"
"$python_exe" "$task_root/harness/prepare.py" verify --experiment "$task_root"
run_phase() {
  local phase="$1" run_code oracle_code score_code
  set +e
  "$python_exe" "$task_root/harness/run_pair.py" --experiment "$task_root" --phase "$phase" --python "$python_exe"
  run_code=$?
  "$python_exe" "$task_root/harness/gold_oracle.py" --experiment "$task_root" --phase "$phase"
  oracle_code=$?
  "$python_exe" "$task_root/harness/score.py" --experiment "$task_root" --phase "$phase"
  score_code=$?
  set -e
  printf 'phase=%s run=%s oracle=%s score=%s\n' "$phase" "$run_code" "$oracle_code" "$score_code"
  [[ "$run_code" -eq 0 && "$oracle_code" -eq 0 && "$score_code" -eq 0 ]]
}
run_phase smoke
# Default job stops after smoke. Full experiment needs an explicit environment flag
# and still has its smoke evidence gate in run_pair.py.
if [[ "${EXPERIMENT1_RUN_MAIN:-0}" == 1 ]]; then run_phase main; fi
