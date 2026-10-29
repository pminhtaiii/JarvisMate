# Implementation plan và contracts

**Status:** implementation chưa bắt đầu. File/script/config trong cây dưới đây là
deliverables dự kiến, không phải những file đã có hoặc đã chạy thành công.
Đọc yêu cầu ở [spec.md](spec.md), trình tự ở [experiments.md](experiments.md).

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
  config.py, data.py, preprocessing.py, augmentation.py
  adapters.py, resource_probe.py, trainer.py
  slots.py, evaluation.py, artifacts.py, exporting.py
python/tests/asr_training/
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

Trước E0, chạy kernel probe trên GPU thật rồi freeze `requirements-train.lock`:
Torch build/CUDA/cuDNN, Transformers, PEFT, Accelerate, NumPy, audio augmentation
library, safetensors, và bitsandbytes nếu E3 được xét. Nếu E3 cần stack khác, tạo
environment ID mới, chạy lại E0 và LoRA đối chứng để so sánh công bằng. Không dùng
`latest` không khóa phiên bản hoặc coi hỗ trợ Blackwell nói chung là đủ cho bnb.

Training/report offline sau explicit preparation; HF caches đều dưới ignored root,
`local_files_only=True`, remote code tắt, Hub upload/W&B/external logging tắt mặc định.
Model snapshot, noise assets và dependency wheels cần chuẩn bị riêng trước khi
chạy trên máy/container không mạng. Ghi license/release/revision và file hashes.

## Script/CLI contract dự kiến

Chạy scripts từ repo root với interpreter của environment training. Các lệnh dưới
đây mô tả interface cần implement; **chưa thể chạy trước khi scripts/configs có thật**.

```powershell
# Biến DATA_ROOT, MODEL_SHA và environment do người chạy cấu hình trên máy GPU.
$suite = '.agent-work/asr-finetune/suite-01'
$split = '.agent-work/asr-benchmark/split42.json'
$model = '.agent-work/asr-finetune/models/phowhisper-large'

# Chỉ bước này có thể truy cập mạng để chuẩn bị snapshot.
python asr/fine-tuned/scripts/prepare_model.py --source vinai/PhoWhisper-large --revision $MODEL_SHA --output $model
python asr/fine-tuned/scripts/prepare_data.py --data-root $DATA_ROOT --split-manifest $split --train-scope with-history --eval-scope current --suite-dir $suite
python asr/fine-tuned/scripts/preflight.py --model $model --suite-dir $suite --experiment E0
python asr/fine-tuned/scripts/run_e0.py --config asr/fine-tuned/configs/e0.json --suite-dir $suite

# Mỗi profile phải có probe pass đúng config/hash trước full training.
python asr/fine-tuned/scripts/preflight.py --model $model --suite-dir $suite --experiment E1
python asr/fine-tuned/scripts/run_e1.py --config asr/fine-tuned/configs/e1.json --suite-dir $suite
python asr/fine-tuned/scripts/preflight.py --model $model --suite-dir $suite --experiment E2
python asr/fine-tuned/scripts/run_e2.py --config asr/fine-tuned/configs/e2.json --suite-dir $suite
python asr/fine-tuned/scripts/preflight.py --model $model --suite-dir $suite --experiment E3
python asr/fine-tuned/scripts/run_e3.py --config asr/fine-tuned/configs/e3.json --suite-dir $suite
python asr/fine-tuned/scripts/preflight.py --model $model --suite-dir $suite --experiment E4
python asr/fine-tuned/scripts/run_e4.py --config asr/fine-tuned/configs/e4.json --suite-dir $suite
python asr/fine-tuned/scripts/compare.py --suite-dir $suite
```

Những dòng trên không phải batch automation để chạy mù: xem result/gate từng
stage. Script phải từ chối predecessor/config chưa đạt; E3/E4 skipped được ghi
bằng `--record-skip <reason>` thay vì train. E1 fail không có nghĩa tự động kết
luận E2 OOM; ghi E2 skipped vì thiếu prerequisite như experiments.md.

Common contract:

- Mỗi experiment có directory/run ID mới. `--resume-from <checkpoint>` explicit,
  không overwrite và không resume khi model/split/config/source hashes khác.
- `preflight` dùng cùng effective config được script experiment resolve; training
  phải kiểm tra probe hash, không chỉ kiểm tra “có file preflight.json”.
- `--limit` chỉ được dùng smoke/evaluation diagnostic; đánh dấu partial và không
  cho checkpoint promotion. Probe chỉ lấy Train, không gradient trên Validation.
- Exit 0 thành công; exit 1 execution/OOM; exit 2 input/config/integrity; exit 3
  unsupported/skipped có reason; 130 interrupted. Gate engine hiểu trạng thái,
  không coi một exit khác 0 là được phép chạy tiếp full training.
- Mọi failure lưu manifest/partial artifacts trước khi thoát; không giấu lỗi
  generation bằng ground truth hoặc loại row. Không auto retry config khác.

## Artifacts contract

```text
.agent-work/asr-finetune/<suite-id>/
  suite.json, requirements-train.lock
  data/audit.json, fit.jsonl, validation-current.jsonl
  data/validation-history.jsonl             # chỉ nếu bật diagnostic
  annotations/critical-slots-v1.jsonl
  E0/ ... E4/
    manifest.json, resolved-config.json, preflight.json
    train-log.jsonl, evaluation-history.jsonl, memory.json
    best-checkpoint.json
    checkpoints/<step>/adapter_model.safetensors, adapter_config.json
    checkpoints/<step>/training-state/     # optimizer/scheduler/scaler/RNG/sampler
    exports/<checkpoint-id>/               # merged model + processor/tokenizer/config
    primary/transcripts.jsonl, metrics.json
    native-4bit/transcripts.jsonl, metrics.json  # E3, nếu khả thi
  comparison.csv, comparison-variants.csv
  report.md, error-analysis.jsonl
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

Sau khi đồng bộ `main` tại `2006a02`, runtime đã hỗ trợ large; implementation cần
xử lý đường benchmark còn bị chặn và giữ các invariant runtime:

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
