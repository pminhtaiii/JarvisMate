# Tuning LLM trên JarvisMate_5

## Một lệnh cho toàn bộ L0–L3

**Data root cho ToolEnv hiện ở `_5`:**
`D:\JarvisMate_5\JarvisMate\DATA_JarvisMate\train+public_test`.
Theo quyền sao chép một lần do người dùng cấp ngày02/11/2026, đã chép nguyên
1.545 file state Train từ `_4` sang `_5` (11.546.236 bytes), đối chiếu đầy đủ
SHA-256/kích thước/mtime và cấu trúc thư mục. Nguồn `_4` giữ nguyên; không phân
tích hoặc hiển thị nội dung state. Ngoại lệ này chỉ dành cho lần chuyển dữ liệu;
trong pipeline, state tiếp tục chỉ được đọc thông qua ToolEnv.

Preflight309/309 inputs,4.083 Fit +953 Validation ASR cache turns và mở1 ToolEnv
thật từ `_5` (0 tool calls) đã qua. Cấu hình local không còn dùng data root `_4`;
code/model/cache/output cũng ở `_5`. Không chạy lại ASR hay tuning để xác minh.
Biên nhận: `.agent-work/llm-implementation/state-transfer-20261102/`.

Trước khi bổ sung state, run `L0-L3-20261102T025412Z-ab25a190` lỗi309/309 đầu
vào closed-loop, rồi pilot dừng với1 failed/9 not_attempted. Log lịch sử giữ
nguyên; hai teacher-forced diagnostics không chứng minh closed-loop thành công.

Lệnh chung nay có phase `evaluation-inputs` sau verify-resources, trước prepare
và các Qwen probes. Phase này chỉ kiểm tra input/runtime và metadata tồn tại của
state, không tạo ToolEnv hoặc tải model. Thiếu asset sẽ báo ASSET_MISSING ngay;
closed-loop và pilot kiểm tra lại trước tải model. Unsupported input thuộc
schema/behavior vẫn giữ trong mẫu số, không biến mất khỏi benchmark.

Kiểm tra riêng, không chạy model:

```powershell
Set-Location "D:\JarvisMate_5\JarvisMate"
& .\.venv-llm\Scripts\python.exe -m lifemate.llm_training evaluation-inputs --config .agent-work/llm-finetune/local-suite.json
```

Terminal hiển thị đầu/cuối mỗi phase, tiến độ probe theo update/microbatch,
train theo update với mean unweighted row loss/LR, validation NLL và số mẫu
evaluation đã xử lý. ETA là ước tính theo phần việc hoàn thành trong lần chạy
hiện tại; chưa đủ dữ liệu thì hiện `--`. Tiến độ trong update/evaluation được
giới hạn khoảng30 giây mỗi dòng; train in sau mỗi optimizer update. Khi child
chưa phát tiến độ, entrypoint báo phase vẫn chạy sau30 giây im lặng. Loading bars,
warning TF32/generation flags quen thuộc và JSON dài không đổ ra terminal;
stdout.log/stderr.log của từng phase vẫn giữ chi tiết, lỗi mới vẫn hiển thị.
Tiến độ đi qua stderr; stdout của CLI phase giữ nguyên một JSON cho orchestration.

### Tối ưu inference, giữ nguyên30 giây

Planner giữ KV cache giữa các quyết định của cùng một mẫu và chỉ tái sử dụng
phần token prefix khớp chính xác. Full prompt vẫn được kiểm tra token budget;
model chỉ forward suffix mới với attention mask đầy đủ. Khi prefix đổi,
cache bị crop đúng điểm khác đầu tiên. Đổi mẫu, kết thúc phiên, trả final hoặc
gặp lỗi đều xóa cache. Decoder parser vẫn dựng mới cho từng quyết định.

Không đổi prompt/tools, precision,16384 context/512 output tokens,16 steps,
repair cap hoặc30 giây. Policy được ghi trong metadata/execution_profile;
trace ghi cached_prefix_tokens nhưng prompt_tokens vẫn là toàn bộ prompt.
Code mới cần proof/native acceptance mới và run mới; không trộn số đo của run cũ.
Giải mã native greedy dùng cùng GuardedPrefix/parser, gộp các đoạn token có đúng
một lựa chọn hợp lệ vào một forward trước quyết định kế tiếp. Vẫn forward prompt
thật và chọn argmax của model ở mọi chỗ có nhiều lựa chọn; không tạo tool call hay
final từ luật. Model/config không hỗ trợ giữ đường Transformers generate cũ.
Policy generation và số forward/forced tokens được ghi trong metadata/trace.
Các composition parser giữ lại alphabet của trạng thái bất biến, tránh dựng lại
Unicode set nhiều lần. Character language được đối chiếu với LMFE stock; mỗi
quyết định vẫn có parser riêng.

Full-audio pilot/evaluation lần lượt đưa ASR rồi Qwen lên GPU, tránh giữ cả hai
cùng lúc. Trọng số CPU gốc được giữ cho inference và khôi phục sau phiên, tránh
copy trọng số không đổi từ GPU về CPU. Thời gian chuyển model vẫn tính trong30
giây; không thêm warmup, không đổi gate1 GiB headroom. Cơ chế này không dùng cho
training hoặc model có gradient.

CPU/tiny/decoder tests chỉ chứng minh cơ chế; kết quả GPU A/B và phạm vi xác minh
được lưu tại `.agent-work/llm-implementation/inference-speed-20261102/`.

Pilot local ngày02/11/2026 trên RTX5070 Ti Laptop:10/10 fixed Validation cases
completed,0 failed;3,80–21,45 giây/mẫu, không warmup.
NVML sampled min-free1.170.305.024 bytes (~1,09 GiB), memory gate passed.
Kết quả này chỉ xác nhận pilot trên máy local; chưa chạy lại toàn bộ309 mẫu và
không chứng minh runtime trên A30. Run cũ giữ nguyên; lệnh dưới tạo run mới và
vẫn đo/review pilot, không kế thừa kết quả pilot này để bỏ gate.

Theo yêu cầu điều phối ASR và toàn bộ suite, chạy một lệnh PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "D:\JarvisMate_5\JarvisMate\CHAY_TUNING_LLM.ps1" -Method nf4
```

Entry point này điều phối **L0 pretrained evaluation → L1 Natural SFT → L2 loss
weighting 1/2/1/2 → L3 approved-ASR SFT**, chung P1 frozen. L1/L2/L3 mỗi run500
updates, khởi tạo độc lập từ pretrained, không warm-start hoặc oversampling.
L0 không train. Mỗi subprocess/phase có log, argv, source và outcome riêng tại
`.agent-work/llm-finetune/single-runs/L0-L3-*/`.

Thứ tự gồm chuẩn bị/tiếp tục ASR cache khi thiếu, prepare/token audit/qualification, L0 G/A diagnostics và closed loop,
native full-audio pilot, L1/L2 train/export/offline verify/G/A, RV018, Fit noisy
views/token audit/length qualification, L3 train/export/verify/G/A và comparison
đủ tám dòng. ASR chỉ được chuẩn bị theo lựa chọn E4 đã được operator cho phép và
ghi trong `orchestration.json`. Script không tự cấp semantic certificate, quyết
định pilot review, trusted state hoặc deployment acceptance; gate lỗi vẫn dừng.
Pilot phải locally_feasible và được chính operator đọc/xác nhận trong terminal
trước training; từ chối/thiếu review sẽ dừng.

**ASR hiện đã hoàn tất**, config local trỏ cache4.083 Fit +953 Validation turns.
Lệnh chung reuse cache đã được kiểm tra, không cần chạy lại ASR. Job này từng được
người dùng yêu cầu dừng ở175 lượt, sau đó đã được chạy tiếp đến hoàn tất. Nếu cần
chuẩn bị/resume ASR, script chỉ dùng quyền chọn E4 và đúng job/source binding trong
`.agent-work/llm-finetune/orchestration.json`, không chọn job mới nhất. Thiếu/đổi
bằng chứng cho phép, job binding, dữ liệu hoặc cache vẫn dừng. Xem
[ASR_HANDOFF](ASR_HANDOFF.md).

### Cập nhật sau lần chạy thực tế dừng ở early-probe

ASR hiện đã hoàn tất **4.083 Fit +953 Validation turns**; config local đã trỏ hai
cache hoàn chỉnh, lệnh sẽ reuse chúng. Người dùng đã chạy prepare/token audit, có2.120 Fit
và539 Validation SFT rows token-valid; không phải mọi gold row đã được chấp nhận.

Run `L0-L3-20261101T174435Z-7bfdbfc5` dừng trước optimizer update đầu tiên ở
early LoRA probe (fixture dài9.648 total tokens) do CUDA OOM. Đã sửa lỗi mode:
`from_pretrained` để base ở eval, nên checkpointing không hoạt động dù đã enable;
training loader nay bật train cho toàn bộ decoder và kiểm tra checkpointing.
Regression tiny save/reload đã fail trước sửa, pass sau sửa. Probe thật sau sửa
vẫn chạm khoảng0,2GB free device và Windows ghi nhận thêm shared GPU memory;
probe chẩn đoán được dừng, **không phải acceptance pass**.

Để chủ động chọn genuine NF4+LoRA cho **cả L1/L2/L3**, dùng một lệnh:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "D:\JarvisMate_5\JarvisMate\CHAY_TUNING_LLM.ps1" -Method nf4
```

NF4 không thay corpus/context/rank/budget hoặc weighting treatments, không warm-start;
vẫn phải pass early/full qualification và các gate khác. Script không tự chuyển
method khi LoRA lỗi. Ở lần sửa early-LoRA này, NF4 actual4B qualification chưa chạy;
xem cập nhật full-probe NF4 ngày 02/11/2026 bên dưới.

### Lần dừng full-probe NF4 (02/11/2026)

Run `L0-L3-20261101T235929Z-81348f10` đã hoàn thành cả5 optimizer updates,
constrained generation và adapter save/reload. Nó dừng ở resource gate:
reserved peak13.287.555.072 bytes, device min-free38.522.880 bytes, thấp hơn
headroom1GiB. Các warning TF32 và generation flags không phải nguyên nhân dừng.
L0 chưa bắt đầu trong run đó.

PEFT k-bit preparation đã upcast frozen tied embedding/head và RMSNorm weights
sang FP32, khiến Qwen giữ activation FP32 dù profile chọn BF16. Loader nay giữ
genuine NF4 double quantization, rồi khôi phục các frozen weights này về compute
dtype đã chọn. Qwen RMS normalization arithmetic và completion cross entropy
vẫn dùng FP32; LoRA A/B vẫn FP32. Không thay corpus/context/rank/accumulation,
không hạ headroom và không tự đổi method.

Phép đo ngắn trên đúng hai worst Fit rows tái hiện lỗi trước sửa và pass memory
assessment sau sửa; đây không thay thế full qualification. Kiểm thử:133 LL tests
(124 pass,9 opt-in skip),5 tiny-Qwen CPU tests pass. Kết quả full probe sau sửa
được ghi tại `.agent-work/llm-implementation/qwen-oom-20261102/nf4-followup.json`.

**Full probe sau sửa đã PASS:** `full-20261102T011304Z-0b5291a4` trong cùng run,
5 updates × accumulation16, generation và adapter save/reload đều qua. Allocated
peak7.077.215.232 bytes, reserved peak7.725.907.968 bytes, sampled device peak
9.134.481.408 bytes; sampled min-free3.686.457.344 bytes (**3,43GiB**), vượt1GiB.
Exact per-process NVML memory vẫn null theo WDDM; gate dùng conservative device
bound đã mô tả bên dưới. Không hạ ngưỡng chấp nhận. Đây là qualification trên
worst clean Fit rows; L3 còn cần qualification gồm approved noisy rows.

Chạy lại lệnh NF4 ở đầu trang để điều phối L0–L3; entrypoint sẽ kiểm tra gate cho
run mới và reuse ASR cache. Lần sửa này không khởi động L0 hoặc train500 updates.

Trên Windows WDDM, NVML không hỗ trợ per-process usedGpuMemory ([NVIDIA](https://docs.nvidia.com/deploy/archive/R550/nvml-api/structnvmlProcessInfo__v1__t.html)).
Metric đó tiếp tục là null. Nếu xác minh đúng UUID/own PID/driver WDDM và đủ mẫu
device, resource gate dùng all-device peak như biên trên bảo thủ, **không** giả
lập process peak. Reserved và all-device peaks vẫn phải <=cap−1GiB, free device
vẫn >=1GiB. Residual device-vs-Torch usage ghi riêng, không gán hết cho process.
Thiếu dữ liệu device, cap/headroom lỗi hoặc driver chưa xác minh vẫn unverified.
Evidence sửa lỗi: `.agent-work/llm-implementation/qwen-oom-20261102/diagnosis.json`.
Kiểm tra sau sửa:132 LL tests (124 pass,8 opt-in skip),4 tiny-Qwen CPU tests pass;
small-GPU WDDM telemetry check pass. Các kết quả này không phải NF4/4B qualification.

Để xem plan hoặc kiểm tra file prerequisite mà không chạy model:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "D:\JarvisMate_5\JarvisMate\CHAY_TUNING_LLM.ps1" -Preview
```

`-CheckInputs` chỉ kiểm tra sự hiện diện handoff/cache, không phải qualification.
Default method là LoRA. `-Method nf4` là lựa chọn **explicit** cùng một phương
pháp cho cả L1–L3, vẫn phải qualification; không có fallback tự động. Optional
`-AsrReviews PATH` trỏ Fit full-prefix reviews đã có, tách khỏi clean quality review.

Khi prerequisites ASR đã đủ và người dùng chạy lệnh chính, script kiểm tra lock37
package đã có, chỉ bổ sung measurement provider **nvidia-ml-py13.595.45** nếu chưa
cài. Wheel URL/SHA256 pin ở `requirements-nvml.lock`, lấy từ
[metadata chính thức PyPI](https://pypi.org/pypi/nvidia-ml-py/13.595.45/json).
Không đổi version package đang có: provider khác pin sẽ block. Script ghi full
derived38-wheel lock/manifest cho profile `windows-py312-cu128-nvml` trong run,
chạy pip check, kernels và full qualification cho profile đó. Lock37 gốc giữ nguyên;
không tải model/data. Profile bổ sung/provider chưa được cài hoặc qualification
trong đợt authoring này. Thiếu Windows process-memory evidence vẫn dừng.

Controlled tests bao gồm đúng thứ tự ASR→L0–L3, resume đúng job, reuse cache có sẵn,
không chạy LLM sau ASR lỗi, mỗi treatment chỉ train một lần, tám closed-loop rows,
qualification/pilot/RV018 gates và provider pin. Lần chạy ASR thật trước khi dừng
đã ghi175 lượt, không phải full cache hay full-suite acceptance. Evidence tích hợp
mới: `.agent-work/llm-implementation/combined-ASR-L0-L3-delivery.json`.
Kiểm tra sau tích hợp:123 LL tests,116 pass và7 opt-in skip;16 test điều phối pass.

## Các lệnh từng phase (tùy chọn)

Resource ASR E0–E4 và snapshot Qwen đã được chuyển local, xem
[TRANSFER](../asr/fine-tuned/TRANSFER.md). Đây là lệnh vận hành, **chưa chạy
corpus preparation, probe model 4B hoặc training LLM**. Các block thủ công bên
dưới chạy từng phase riêng; entrypoint toàn bộ suite được nêu ở đầu tài liệu.

## 1. Thiết lập PowerShell

```powershell
Set-Location 'D:\JarvisMate_5\JarvisMate'
$llmPython = (Resolve-Path '.venv-llm/Scripts/python.exe').Path
$llmConfig = Join-Path (Get-Location) '.agent-work/llm-finetune/local-suite.json'
$llmSuite = Join-Path (Get-Location) '.agent-work/llm-finetune/suite-01'
$llmSettings = Join-Path (Get-Location) 'fine-tune-llm/configs/training.json'
```

Venv đã có; không tạo lại/copy environment ASR cũ. Profile đang kiểm tra là
Python3.12.10/Torch2.9.0+cu128. Native CPU decoder proof và rendering acceptance đã
có, ràng buộc code/tokenizer; nếu đổi các binding đó phải chạy lại proof riêng.

## 2. Chuẩn bị và nghiệm thu corpus

```powershell
& $llmPython -m lifemate.llm_training prepare --config $llmConfig --suite-dir $llmSuite
```

Đọc audit, xử lý pending/quarantine bằng Fit review đúng policy; không tự approve
gold/mask lỗi. Không dùng draft suite để train. Suite directory đã tồn tại thì
không ghi đè; kiểm tra trạng thái hoặc chọn suite mới có chủ đích.

```powershell
& $llmPython -m lifemate.llm_training seal-selection-policy --suite-dir $llmSuite --policy fine-tune-llm/configs/selection-policy.json
```

```powershell
& $llmPython -m lifemate.llm_training token-audit --suite-dir $llmSuite --scope clean
```

Phải có accepted Fit/Validation support thật, không chỉ `status=passed` cũ.

## 3. Qualification 4B trước full training

Chỉ chạy model khi đã chủ động chọn scope này. Full probe dùng accepted worst
rows, ít nhất 5 updates, accumulation16, generation/save/reload; không train500.

```powershell
& $llmPython -m lifemate.llm_training probe --suite-dir $llmSuite --experiment L1 --scope full --settings $llmSettings
```

Phải nhận **status `passed`**. `passed_early_smoke`, `resource_unverified`, OOM hoặc
kernel pass không thay qualification. Đặc biệt lock hiện chưa có NVML Python
provider: trước full probe phải chọn/lock/verify provider phù hợp và chạy lại checks
cho profile đó. Windows thiếu process-memory evidence vẫn block. Quy trình lock và
probe early/NF4 riêng trong [RUNBOOK](RUNBOOK.md); không tự cài package không pin
hoặc đổi LoRA/rank/context để vượt gate. Các bước này chưa được chạy thay người dùng.

Đặt biến bằng **đường dẫn outcome thực tế vừa passed**, không dùng placeholder:

```powershell
$llmQualification = Read-Host 'Dán đường dẫn outcome.json của full probe có status passed'
if (-not (Test-Path -LiteralPath $llmQualification)) { throw 'Không có qualification outcome' }
```

## 4. Quyết định audio latency của operator

Trước full L1/L2 cần pilot reviewed hoặc quyết định chủ động tiếp tục khi audio
latency còn chưa đo. E4 WER/roundtrip không thay full-audio native pilot. Candidate
E4 chưa có selected-ASR handoff chuẩn nên pilot/A hiện còn gate riêng.

**Chỉ chạy block dưới nếu chính bạn chọn tiếp tục với audio latency unresolved.**
Block ghi lựa chọn của operator; không phải kết quả pilot hoặc quyền do agent tự cấp.
Nếu muốn chạy/duyệt pilot trước, dùng schema/commands trong RUNBOOK thay block này.

```powershell
$llmLatencyDecision = Join-Path $llmSuite 'operator-audio-latency-decision.json'
if (Test-Path -LiteralPath $llmLatencyDecision) { throw 'Decision đã tồn tại; đọc lại, không ghi đè' }
$llmReason = Read-Host 'Lý do bạn chọn tiếp tục trước khi đo full-audio latency'
if ([string]::IsNullOrWhiteSpace($llmReason)) { throw 'Cần lý do của operator' }
$llmSeal = Get-Content -Raw -Encoding utf8 (Join-Path $llmSuite 'SEAL.json') | ConvertFrom-Json
$llmDecisionBody = @{
    schema = 'lifemate-audio-latency-decision-v1'
    suite_seal = $llmSeal.identity
    operator = $env:USERNAME
    decision = 'proceed_with_unresolved_audio_latency'
    reason = $llmReason
} | ConvertTo-Json
[System.IO.File]::WriteAllText($llmLatencyDecision, $llmDecisionBody + [Environment]::NewLine, (New-Object System.Text.UTF8Encoding($false)))
```

## 5. Preflight rồi train L1 hoặc L2 độc lập

```powershell
& $llmPython -m lifemate.llm_training preflight --suite-dir $llmSuite --experiment L1 --settings $llmSettings --resource-qualification $llmQualification --latency-decision $llmLatencyDecision
```

Chỉ khi preflight `ready`, chạy **một** treatment được chọn:

```powershell
& $llmPython fine-tune-llm/scripts/run_l1.py train --suite-dir $llmSuite --settings $llmSettings --resource-qualification $llmQualification --latency-decision $llmLatencyDecision
```

L2 bắt đầu độc lập từ cùng pretrained base, không warm-start từ L1:

```powershell
& $llmPython fine-tune-llm/scripts/run_l2.py train --suite-dir $llmSuite --settings $llmSettings --resource-qualification $llmQualification --latency-decision $llmLatencyDecision
```

Không chạy cả hai chỉ vì cùng có lệnh. Mỗi run500 optimizer updates/16 rows;
checkpoint/NLL cadence100/final, earliest-step tie. Resource/corpus/profile phải
giữ chung. L3 cần RV018 và approved Fit ASR views/cache, chưa đủ điều kiện hiện tại.
Export, G/A evaluation và promotion là lệnh riêng trong RUNBOOK, không tự nối sau train.
