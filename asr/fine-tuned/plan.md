# Implementation plan và contracts

**Status:** shared engine/scripts đã được viết; GPU/large acceptance chưa chạy.
Tài liệu này giữ thiết kế; module map thực tế ở [review.md](review.md), commands chính
xác ở [RUNBOOK.md](RUNBOOK.md). Những tên file thiết kế được gom/tách trong implementation
không thay đổi contract dữ liệu, metric hoặc việc người dùng chạy riêng từng experiment.

## Module và dependency boundary

```text
asr/fine-tuned/
  scripts/
    prepare_model.py     # explicit online snapshot preparation, không train
    prepare_data.py      # frozen manifest projection/audit, không model
    preflight.py         # hardware/environment + selected experiment probe
    run_e0.py            # baseline evaluation, không optimizer
    run_e1.py            # decoder LoRA
    run_e2.py            # encoder + decoder LoRA
    run_e3.py            # optional QLoRA
    run_e4.py            # matched LoRA + augmentation
    export_model.py
    compare.py
  configs/
    common.json
    e0.json ... e4.json
python/src/lifemate/asr_training/
  config.py, data.py, augmentation.py
  models.py, resources.py, trainer.py, checkpoints.py, workers.py
  slots.py, evaluation.py, selection.py, storage.py, reporting.py, exporting.py, orchestration.py, execution.py, cli.py
python/tests/test_asr_training*.py
```

Folder `fine-tuned` giữ tên theo yêu cầu, không dùng tên có dấu `-` làm Python
import path. Scripts là entrypoints độc lập gọi package `lifemate.asr_training`;
không copy training loops thành năm bản. Module training import dependencies lazy,
không khiến CLI baseline cần PEFT/bitsandbytes khi chỉ chạy inference.

Tái sử dụng strict JSON/contained paths/hash từ `lifemate.jsonio`, WAV checks,
normalization/edit counts và timing conventions của `asr/pretrained`. Không import
ToolEnv hoặc pipeline dataset loader có side effects vào exporter ASR.
`asr/pretrained.data.load_selection` hiện chỉ xuất Validation: triển khai training
projection riêng đọc cùng manifest; không đổi nó thành một splitter mới.

## Runtime environment

Tạo môi trường training riêng; không nâng cấp `.venv` CPU benchmark để thử GPU.
Ứng viên ban đầu là Python 3.11/3.12 và stack Torch CUDA/Transformers tương thích
Whisper; Torch 2.9.0 / Transformers 4.57.1 đang có trong baseline chỉ là điểm bắt
đầu đối chiếu, **CPU wheel hiện có không dùng trên GPU**.

Trước E0, chạy kernel probe trên GPU thật; mỗi probe/run freeze `requirements-resolved.txt`:
Torch build/CUDA/cuDNN, Transformers, PEFT, Accelerate, NumPy, audio augmentation
library, safetensors, và bitsandbytes nếu E3 được xét. Nếu E3 cần stack khác, tạo
environment ID mới, chạy lại E0 và LoRA đối chứng để so sánh công bằng. Không dùng
`latest` không khóa phiên bản hoặc coi hỗ trợ Blackwell nói chung là đủ cho bnb.

Training/report offline sau explicit preparation; HF caches đều dưới ignored root,
`local_files_only=True`, remote code tắt, Hub upload/W&B/external logging tắt mặc định.
Model snapshot, noise assets và dependency wheels cần chuẩn bị riêng trước khi
chạy trên máy/container không mạng. Ghi license/release/revision và file hashes.

## Script/CLI contract thực tế

[RUNBOOK.md](RUNBOOK.md) là hướng dẫn cài/chạy chính xác. Scripts là thin entrypoints
cho `python -m lifemate.asr_training`; mỗi lệnh `run` hoặc `preflight` chọn đúng một
experiment. Không có automatic all-experiments runner.

| Operation | Entry point |
|---|---|
| Online snapshot preparation | `prepare_model.py` hoặc CLI `prepare-model --models-dir ... --revision ...` |
| Frozen suite preparation | `prepare_data.py --suite-dir ... --data-root ... --split-manifest ... --model ...` |
| GPU/resource probe | `preflight.py --suite-dir ... --experiment E0` (tương tự E1–E4) |
| One experiment | `run_e0.py` ... `run_e4.py --suite-dir ...`, hoặc CLI `run --experiment ...` |
| Explicit resume | Thêm `--resume-from <durable checkpoint>` vào đúng experiment |
| Status | CLI `status --suite-dir ...`; đọc artifacts, không load model |
| Skip/failure recovery | CLI `skip`, `fail`, `unlock` với reason/PID/path explicit |
| Export selected best | `export_model.py --suite-dir ... --run-dir ... --output ...` |
| Final compare | `compare.py --suite-dir ...`; không training/inference |

Mỗi run có ID mới. Probe pass phải khớp config/model/data/code/environment/GPU;
không chỉ kiểm tra có một file preflight. Resume không cho đổi binding và không
nhận checkpoint probe/experiment khác. E4 freeze control/update budget.
Exit 0 completed/passed, 1 execution/resource failure, 2 input/integrity error,
3 unsupported, 130 interrupted. Skip là operation ghi nhận có chủ đích, exit 0
không có nghĩa experiment đã train thành công. Không tự retry OOM hoặc đổi config.

## Artifacts contract

```text
.agent-work/asr-finetune/<suite-id>/
  suite.json
  data/fit.jsonl, validation-current.jsonl, validation-history.jsonl
  data/audit.json, files.json, slots.jsonl, slot-rules.json  # slots optional
  E0/ ... E4/
    probe-<id>/manifest.json, preflight evidence/checkpoints, files.json
    run-<id>/
      manifest.json, resolved-config.json, requirements-resolved.txt
      train-log.jsonl, augmentation.jsonl, evaluation-history.jsonl
      best-checkpoint.json, latest-checkpoint.json
      checkpoints/step-<step>-<id>/adapter/, optimizer.pt, state.json, files.json
      primary/step-<step>/transcripts.jsonl, metrics.json   # E0 primary trực tiếp
      native-4bit/step-<step>/transcripts.jsonl, metrics.json # E3
      exports/best/                                        # merged local bundle
      export-evaluation/transcripts.jsonl, metrics.json
  comparisons/<timestamp-id>/
    comparison.csv, comparison-variants.csv, details.json, report.md
```

E0 không tạo train log/checkpoint adapter giả. Skipped/unsupported có manifest
và CSV row với metrics `null`; không tạo transcripts thành công giả. Best adapter
cần local base snapshot tương ứng, không chỉ tên model Hub. Không copy 1,55B
weights vào mọi training checkpoint; adapter checkpoints + bản export best đủ.

Manifest tối thiểu: status/reason/timestamps, exact argv, Git revision/dirty state
và code hashes, source model SHA/weight hashes/license, split/fit/selection IDs,
annotation/rules/normalization hashes, hardware/environment, seeds/dtypes/targets,
trainable/base/deployed parameter counts, augmentation provenance, effective batch,
optimizer updates/epoch, resource probe, durations/peaks, selection policy and best ID.

Transcripts giữ các trường benchmark cũ: utterance/sample/turn/group IDs, audio
path/hash/duration, reference/prediction và normalized text, edit counts, status,
error, latency/RTF. Thêm experiment/checkpoint/representation ID và slot matching
counts khi có. Gold slots không đi vào child inference worker.

`comparison.csv`: đúng một primary row E0–E4 cho selected checkpoint/status,
gồm `experiment`, `status`, `reason`, `control_experiment`, `checkpoint_id`,
`model_revision`, `split_identity`, `fit_identity`, `selection_identity`,
`inference_representation`, `training_precision`, `inference_dtype`, `seed`,
`selected`, `succeeded`, `coverage`, failed/timeout/not_run, raw/normalized WER/CER,
CSA/support/annotation coverage/slot P-R-F1, mean/P95/RTF/load seconds,
`train_peak_allocated_gib`, `train_peak_reserved_gib`, `infer_peak_allocated_gib`,
`infer_peak_reserved_gib`, trainable/deployed counts, optional Tool-call F1/Final
State Match. Raw counts và per-type details nằm trong metrics JSON để CSV gọn.
`comparison-variants.csv` tách E3 NF4 native và các backend/dtype diagnostic.

## Sửa guard và tích hợp Python runtime

Runtime đã hỗ trợ large; implementation này cũng đã cập nhật registry/preparation/
loader benchmark sang budget LifeMate. Các invariant vẫn cần giữ khi tiếp tục phát triển:

| Vị trí hiện tại | Việc cần làm |
|---|---|
| `asr/pretrained/prepare.py:model_details` | Policy hợp lệ cho nguồn PhoWhisper-large hoặc helper preparation riêng, giữ provenance/hash checks |
| `asr/pretrained/models.py:local_spec` và `TransformersASR` | Không coi <1B là rule BTC; nếu mở đường large qua benchmark cũ thì sửa cả validation và loader |
| `python/src/lifemate/adapters/asr.py:LocalASR` | Guard đã nới lên budget 6B cho model, CLI kiểm tra tổng; giữ hỗ trợ large/offload, thêm export adapter phù hợp và giữ WAV/deadline/offline policy |
| `python/src/lifemate/cli.py` và adapter planner | Giữ strict total <6B, LLM <5B và context bound; regression tests biên bằng/vượt ngưỡng |

Không xóa mọi guard vô điều kiện. Thay cap ASR tùy ý bằng policy source/architecture
được hỗ trợ và budget toàn hệ thống, đo count thật. Với quantized models, dùng
**logical architecture parameter count** của non-quantized source và adapter;
không lấy số phần tử packed 4-bit storage làm số parameters. Đếm tied parameters
một lần trong mỗi model. Merged LoRA không cộng thêm A/B đã được gộp; unmerged thì có.

## Export và offline acceptance

1. Lưu adapter + base revision. Nạp fresh local non-quantized base trên CPU/host
   đủ RAM, load adapter, merge nếu stack hỗ trợ, lưu safe weights + đầy đủ processor,
   tokenizer, generation config. Không mặc định quantized merge là lossless.
2. So merged với unmerged **cùng dtype/base** trên corpus diagnostic, log text và
   numeric tolerance trước khi chấp nhận; E3 NF4 khác half phải được đo riêng.
   Khi chọn checkpoint từng epoch, chạy evaluation workers tuần tự và giải phóng
   GPU giữa native/primary representations; không vô tình giữ hai model trên GPU.
3. Chặn network ở fresh process, kiểm tra mọi file/hash rồi load/generate được;
   thiếu một file phải fail local-only. Export khác representation/dtype cần full
   primary reevaluation, không tái sử dụng score adapter một cách ngầm định.
4. Adapter integration chạy current/history ASR, tái sử dụng model qua sample,
   timeout/error contracts và input whitelist. Giữ nguyên ToolEnv/prompt/action grammar.
5. Đếm Qwen thực tế + ASR + adapter/model bổ sung; kiểm tra joint peak VRAM và KV
   cache ở context thực. Khoảng 5,55B weights FP16 đã xấp xỉ 11,1 GB decimal,
   chưa kể activations/KV, nên parameter-compliant chưa chắc vừa GPU 12 GB.
6. A30 offline/container replay và total per-sample <=30s là acceptance riêng,
   gồm ASR history, planner, tools, collection. Nếu chưa chạy, ghi unverified;
   không suy từ ASR latency hoặc GPU training.
