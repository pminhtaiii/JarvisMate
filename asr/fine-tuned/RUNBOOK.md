# Chạy PhoWhisper-large E0–E4 thủ công

Chạy từ repo root, trên branch `fine-tuned-asr`. **Mỗi lần chỉ chạy một experiment**:
đọc kết quả/status trước khi gọi experiment tiếp theo. Không có `run --all` và không
script nào tự chuyển E0 → E1 → E2 → E3 → E4. `compare` chỉ đọc artifacts.

Các lệnh dưới đây dành cho người vận hành; tác giả chưa chạy large/GPU/full training.
Máy Raccoon hiện có Torch CPU không dùng để xác nhận chạy vừa GPU NVIDIA 12 GiB.

## 1. Cài environment riêng trên máy GPU

Ví dụ Windows PowerShell với Python 3.12 đã cài:

```powershell
Set-Location 'C:\Users\Windows\Downloads\ZaloAI\JarvisMate'
py -3.12 -m venv .venv-asr-train
$python = (Resolve-Path '.\.venv-asr-train\Scripts\python.exe').Path
& $python -m pip install --upgrade pip
& $python -m pip install torch==2.9.0 --index-url https://download.pytorch.org/whl/cu128
& $python -m pip install -r asr/fine-tuned/requirements-train.txt
& $python -m pip install -e ./python

# Chỉ cần nếu dự định thử E3. Cài trước E0 để giữ môi trường đối chứng thống nhất.
& $python -m pip install -r asr/fine-tuned/requirements-qlora.txt
& $python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
& $python -m lifemate.asr_training --help
```

Torch CUDA 12.8 wheel là một lựa chọn có trong [hướng dẫn chính thức PyTorch](https://pytorch.org/get-started/previous-versions/).
Đó chưa phải evidence binary/driver/bitsandbytes trên GPU của bạn hoạt động.
Nếu launcher `py` lỗi, thay bằng đường dẫn executable Python 3.11–3.13 x64 thực tế;
không dùng lại CPU wheel vì chỉ thấy tên GPU trong Device Manager.

Linux: dùng `python3.12 -m venv .venv-asr-train`, sau đó đặt
`PYTHON=.venv-asr-train/bin/python`, thay `& $python` bằng `$PYTHON`; các script/flags
giống nhau. Không cần activate venv nếu gọi đúng interpreter. `.venv-asr-train/` đã ignored.

## 2. Prepare: giữ nguyên split

Chuyển nguyên dataset và `.agent-work/asr-benchmark/split42.json` sang máy GPU.
Không chạy lại splitter. Root dữ liệu phải trực tiếp chứa `train/`.

```powershell
$suite = '.agent-work/asr-finetune/suite-01'
$dataRoot = (Resolve-Path '../train+public_test/train+public_test').Path
$split = '.agent-work/asr-benchmark/split42.json'
$model = '.agent-work/asr-finetune/models/phowhisper-large'

# Bước chủ động tải weights/processor; các bước sau không tải model ngầm.
& $python asr/fine-tuned/scripts/prepare_model.py
# Khi tái lập: thêm --revision <SHA publisher đã lưu>, mỗi source model có SHA riêng.

# Audit toàn bộ audio/current/history, hashes và tạo suite immutable; không train.
& $python asr/fine-tuned/scripts/prepare_data.py --suite-dir $suite --data-root $dataRoot --split-manifest $split --model $model
& $python -m lifemate.asr_training status --suite-dir $suite
```

Prepare kiểm tra đúng source/identity seed 42, ghép transcript với chính turn user,
WAV/hashes, group membership, conflict PCM và dedup Train có provenance. Fit tối đa
4.083 lượt user thuộc 1.236 source samples; primary Validation giữ đúng 309 lượt current.
Validation history 953 lượt được lưu riêng. Không đọc app environment hoặc Public/Private Test.

Suite tồn tại sẽ bị từ chối overwrite. Tái sử dụng suite cho các experiment trong
cùng comparison. Muốn đổi dataset/model/policy cần suite mới; source file/hash bị
đổi sẽ chặn run. Model folder phải là snapshot `phowhisper-large` đã có provenance.

Optional CSA: nếu có nhãn/rules đã review, thêm **ngay khi prepare**
`--slot-annotations <annotations.jsonl> --slot-rules <rules.json>`; xem
[SLOT_FORMAT.md](SLOT_FORMAT.md). Không có nhãn thì CSA unavailable, vẫn train được,
checkpoint chỉ là provisional về độ đúng ý nghĩa. Thêm nhãn sau E0 cần suite mới và E0 lại.

## 3. E0 — chạy trước tiên, rồi dừng

```powershell
& $python asr/fine-tuned/scripts/preflight.py --suite-dir $suite --experiment E0
if ($LASTEXITCODE -eq 0) {
    & $python asr/fine-tuned/scripts/run_e0.py --suite-dir $suite
}
& $python -m lifemate.asr_training status --suite-dir $suite
```

Preflight đo actual CUDA/GPU/VRAM, thử kernels/precision, audit token lengths và
load/generate trên audio Train. E0 full evaluation chỉ 309 current Validation, không
optimizer. Thành công ghi `completed`, coverage 1.0, rồi **dừng**, không tự chạy E1.
Không lấy điểm PhoWhisper-medium hoặc smoke 5 lượt của benchmark cũ thay E0 large.

## 4. E1 — decoder-only LoRA, gọi riêng

```powershell
& $python asr/fine-tuned/scripts/preflight.py --suite-dir $suite --experiment E1
if ($LASTEXITCODE -eq 0) {
    & $python asr/fine-tuned/scripts/run_e1.py --suite-dir $suite
}
```

E1 yêu cầu E0 completed trên cùng code/environment/GPU. Probe thực hiện ít nhất
10 optimizer updates với accumulation thật, Train longest-duration/label/typical,
kiểm tra gradients, base frozen, adapter thay đổi, save rồi fresh-process reload/
generation. Chỉ train khi probe pass đúng binding. E1 chỉ gắn decoder self/cross
attention q/v; không gắn encoder. Kết thúc best/export/evaluate rồi dừng.

## 5. E2 — encoder + decoder, gọi riêng

```powershell
& $python asr/fine-tuned/scripts/preflight.py --suite-dir $suite --experiment E2
if ($LASTEXITCODE -eq 0) {
    & $python asr/fine-tuned/scripts/run_e2.py --suite-dir $suite
}
```

Yêu cầu E1 completed và hyperparameters đối chứng khớp. Khởi tạo từ pretrained
gốc, không từ best E1. Probe kiểm tra gradient/update ở cả hai phía. Nếu OOM,
lưu `failed_oom` và dừng, không giảm config hoặc chuyển E3 tự động.

Nếu E1 không khả thi, ghi E2 dependency skip trước khi xem xét E3:

```powershell
& $python -m lifemate.asr_training skip --suite-dir $suite --experiment E2 --status skipped_dependency --reason 'E1 resource probe failed; no valid LoRA control'
```

## 6. E3 — NF4 4-bit, có điều kiện và gọi riêng

Chỉ sau khi E1/E2 có terminal records. Default config khai báo mục tiêu
`memory_comparison`; đổi `purpose` thành `oom_fallback` nếu đó là mục tiêu thực tế.

```powershell
& $python asr/fine-tuned/scripts/preflight.py --suite-dir $suite --experiment E3
if ($LASTEXITCODE -eq 0) {
    & $python asr/fine-tuned/scripts/run_e3.py --suite-dir $suite
}
```

Gate phải thấy real Linear4bit, gradients/updates, optimizer, generation và fresh
adapter reload chạy được. Unsupported được lưu, không chuyển int8 một cách ngầm định.
E3 target E2 scope khi E2 thành công, nếu không dùng decoder scope E1. Không có LoRA
control thành công thì không tuyên bố đã đo được mức tiết kiệm so control đó.

Nếu không cần E3, thay các lệnh probe/train bằng skip:

```powershell
& $python -m lifemate.asr_training skip --suite-dir $suite --experiment E3 --status skipped_not_needed --reason 'Unquantized LoRA is feasible; NF4 comparison deferred'
```

Native NF4 nằm ở variants. Primary dùng fresh non-quantized base + adapter, merge
và evaluate FP16 giống E0. Nếu chỉ native chạy được, status `export_unavailable`,
không thay số NF4 vào bảng primary FP16.

## 7. E4 — augmentation, gọi riêng

Cần E2/E3 có outcome và ít nhất một control E1/E2 completed. Engine chọn control
bằng frozen selection policy, khóa config/checkpoint/update budget, rồi khởi tạo
lại từ pretrained. Không train nối tiếp E1/E2. Chạy đến control update budget;
best-checkpoint selection vẫn thực hiện theo từng epoch.

Chuẩn bị JSON noise manifest là **array**, mỗi entry có absolute `path`, `sha256`,
`license`, `reviewed: true`, `contains_speech: false`. Noise phải là local non-speech
PCM mono 16 kHz 16-bit, không rỗng, <=30s, nằm ngoài competition dataset; operator
review/nghe trước. Không tự tải hoặc dùng tiếng nói/Test làm noise.

```powershell
$noise = '.agent-work/asr-finetune/noise-manifest.json'
& $python asr/fine-tuned/scripts/preflight.py --suite-dir $suite --experiment E4 --noise-manifest $noise
if ($LASTEXITCODE -eq 0) {
    & $python asr/fine-tuned/scripts/run_e4.py --suite-dir $suite --noise-manifest $noise
}
```

Speed perturbation là deterministic resampling/interpolation, volume -6..+6 dB,
noise SNR 15..30 dB; 50% lượt clean, xác suất từng transform 0.5 trong nhánh còn lại.
Transform làm vượt 30s hoặc clipping bị fallback và log, không crop/truncate speech.
Không có noise hợp lệ thì không tự chạy E4 thiếu noise. Seed dựa vào root seed/epoch/ID,
không dựa vào timestamp. Chỉ Train được augment, reference giữ nguyên.

## 8. Logs, cấu hình, lỗi và resume

`configs/common.json` là defaults thực tế, `e0.json`…`e4.json` chọn experiment.
Có thể thêm `--config <file>` cho từng script; thay config sau probe làm probe cũ
hết hiệu lực. Không sửa config/stack trong suite rồi so như cùng một điều kiện.
E2/E3 phải khớp LoRA control; E4 kế thừa config/budget của control. Không load Qwen khi train.

Mỗi probe/run có UUID/timestamp, `resolved-config.json`, manifest, code/environment/
model/data bindings, và `requirements-resolved.txt`. Logs/checkpoints nằm dưới
`$suite/E1/run-.../` tương tự các experiment khác:

```powershell
& $python -m lifemate.asr_training status --suite-dir $suite
# Thay bằng run directory vừa được in ra:
Get-Content '.agent-work/asr-finetune/suite-01/E1/run-.../train-log.jsonl' -Tail 10
```

Latest pointer: `latest-checkpoint.json`; best pointer: `best-checkpoint.json`.
Checkpoint lưu adapter, optimizer/scheduler/scaler, RNG và epoch/cursor/step.
Lưu mỗi 50 updates và cuối epoch; giữ immutable checkpoints, không tự xóa. Cần
đủ disk cho adapter/optimizer states và một export large hoàn chỉnh.

```powershell
# Explicit resume: thay đường dẫn bằng checkpoint durable thật, không dùng probe checkpoint.
& $python asr/fine-tuned/scripts/run_e1.py --suite-dir $suite --resume-from '.agent-work/asr-finetune/suite-01/E1/run-.../checkpoints/step-...'
```

Resume tạo run mới, giữ run cũ; chỉ cùng experiment/config/model/data/code/environment/
GPU. Không resume từ một checkpoint khác scope, probe, corrupted hoặc đã hết budget.
Chỉ lịch sử evaluation tới checkpoint được chọn được kế thừa; không kéo best ở tương lai.
Nếu stack/code/GPU đổi, cần suite/rebaseline phù hợp; không cam kết resume bitwise xuyên hardware.

Nếu process bị kill cứng để lại lock, xác minh nó đã dừng rồi dùng PID ghi trong
`active.lock`; tool từ chối unlock process còn sống hoặc lock của host khác:

```powershell
& $python -m lifemate.asr_training unlock --suite-dir $suite --expected-pid 12345
& $python -m lifemate.asr_training fail --suite-dir $suite --run-dir '.agent-work/asr-finetune/suite-01/E1/run-...' --reason 'Worker terminated; continue later from a durable checkpoint'
```

PID/path trong ví dụ phải thay bằng giá trị thật. Không tự kill process khác hoặc
xóa lock đang chạy. OOM/budget/unsupported được ghi rõ, không auto retry cấu hình khác.
Exit: 0 passed/completed, 1 execution/resource failure, 2 input/integrity, 3 unsupported,
130 interrupted. Không chạy bước tiếp theo chỉ vì thấy có file checkpoint.

## 9. Final compare — không train/inference lại

```powershell
& $python asr/fine-tuned/scripts/compare.py --suite-dir $suite
```

Mỗi lần tạo `$suite/comparisons/<timestamp-UUID>/` với `comparison.csv` đủ E0–E4,
`comparison-variants.csv`, `details.json`, `report.md`. Không ghi đè report cũ.
Failed/skipped/unsupported/not_run vẫn có dòng; unavailable là ô trống/null, không 0 giả.
WER/CER trong CSV là ratio; Markdown đổi %. Raw counts, CSA/support/per-type, memory
phases và bootstrap nằm trong JSON. Variants tách native NF4 và matched-budget E4/control.

CSA chưa sẵn sàng thì checkpoint best-WER là provisional, không khẳng định giữ đúng
ý nghĩa. Giữ E0 nếu không có cải thiện đủ evidence. `compare` bootstrap theo group,
không gọi model; có thể chạy trên máy CPU chỉ có package core.

## 10. Export và tích hợp JarvisMate

Run training thành công đã tự export best và fresh-process round-trip, rồi full
evaluate bản export. Đường dẫn nằm ở `manifest.json -> export.path`. Để export
lại có chủ đích sang directory mới:

```powershell
& $python asr/fine-tuned/scripts/export_model.py --suite-dir $suite --run-dir '.agent-work/asr-finetune/suite-01/E1/run-...' --output '.agent-work/asr-finetune/deploy/phowhisper-large-best'
```

Có số parameters Qwen **đếm thực tế** thì thêm `--planner-parameters <count>`;
`--extra-parameters <count>` cho model bổ sung và `--context-tokens 16384`.
Không đưa số danh nghĩa 4B thay số đo để tuyên bố deployment compliant.
Merged output dùng trực tiếp làm `--asr-model <export-path>` của `python -m lifemate run`
trong audio mode, cùng local Qwen. Giữ contract `transcribe(audio_path, remaining_seconds)`.
Runtime đã hỗ trợ large/offload và kiểm tra tổng parameters; vẫn phải đo joint VRAM/
KV cache, history-ASR và toàn pipeline trên A30, không suy từ training 12 GiB.

Inference workers chặn outbound network, local-files-only; không tải missing asset.
Missing/corrupted export phải fail. NF4 native và merged FP16 khác representation,
không gắn nhãn score/VRAM của bản này cho bản kia. Optional Tool-call F1/Final State
Match hiện unavailable vì chưa chạy authoritative pipeline scorer.

## 11. Test và evidence

```powershell
& $python -m unittest discover -s python/tests -p 'test_asr_training*.py' -v
& $python -m unittest discover -s asr/pretrained/tests -p 'test_*.py' -v
```

Tests dùng synthetic WAV/records, mocks và Whisper ngẫu nhiên rất nhỏ trên CPU,
không tải weights. Thiếu PEFT thì tiny tests skip và phải nêu rõ; không được gọi
skip là đã kiểm tra LoRA. [review.md](review.md) ghi exact execution evidence.
GPU/NF4 kernels/large fitting/quality/A30 vẫn cần người dùng chạy theo từng gate ở trên.
