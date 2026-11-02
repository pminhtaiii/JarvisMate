# Native Qwen next-action fine-tuning

Implementation for specs v1.3: foundation repairs F1–F8 and LL025–LL048. Work is
sequential; the manual CLI selects one phase. The explicitly requested whole-suite
entry point `CHAY_TUNING_LLM.ps1` orchestrates L0–L3 through separate recorded
subprocesses and stops at missing gates/ASR. See TUNING_LOCAL.md; it has not run models.

Read [RUNBOOK.md](RUNBOOK.md) for commands, [HANDOFF.md](HANDOFF.md) for task/evidence
status, and [ASR_HANDOFF.md](ASR_HANDOFF.md) for the selected-ASR cache interface.
Receiving-machine commands after ASR transfer are in [TUNING_LOCAL.md](TUNING_LOCAL.md).
The authoritative requirements remain [specs.md](specs.md).

The model sees shared native Qwen messages/tools, predicts one native call or the
ordinary final `Đã kết thúc.`, and receives actual ToolEnv observations. Training
never opens ToolEnv or hidden state. L0 is pretrained; L1/L2 start independently
from that base; L3 also starts independently and needs an explicit RV018 report.

Source is authored and scoped checks have run. Actual 4B smoke/qualification,
corpus preparation, ASR workflows, L0 evaluation, full training, actual exports and
A30 acceptance have **not** run in this handoff. Checkboxes in tasks.md remain open;
source delivery is separate from executed acceptance.

The receiving-machine profile is explicitly **Windows/Python 3.12.10/cu128**,
using the available interpreter rather than pretending Python 3.11 was tested.
The full [37-wheel lock](locks/windows-py312-cu128.lock) includes the candidate NF4
dependency. Training and NF4 dependency inputs remain separate. The
[lock manifest](locks/windows-py312-cu128.manifest.json) records builds and hashes;
it does not qualify a 4B training run. Do not reuse it with Python 3.11 or Linux.

The implemented boundaries are:

| Boundary | Source |
|---|---|
| Ordered persistence, proof/input/corpus readiness | storage.py, tokenization.py, acceptance.py |
| Exact pinned weights and logical headers | model_identity.py |
| Host/CUDA kernels, LoRA/NF4, scoped probes | resources.py, models.py, qualification.py |
| Exact loss, fixed budget, durable resume | losses.py, trainer.py, checkpoints.py |
| Selected ASR, separate caches, approved views | asr_views.py |
| Actual merged export and independent offline reloads | export.py |
| Teacher-forced/closed loop, audio timing, comparison | evaluation.py, pilot.py, reporting.py |
| External A30/supervisor evidence validation | deployment.py |

These modules are under `python/src/lifemate/llm_training/`. Imports and model-free
commands do not import model/device libraries. Token auditing explicitly permits
CPU tokenizer/backend libraries. Model phases validate the complete lock first.

Use `CHAY_TUNING.ps1 -Phase status` or the venv interpreter. No activation, global
Python package changes, remote model service, model download or automatic ASR job
is part of these commands. A missing resource blocks its dependent phase.
