# Benchmark ASR pretrained

CLI độc lập tại `asr/pretrained/`, chạy từ repo root `JarvisMate/`.
Không sửa hành vi `lifemate`, không training/fine-tuning, không dùng ToolEnv,
context, label hay phản hồi assistant để nhận dạng giọng nói.

## Máy Raccoon và các cấu hình

Máy Intel Core Ultra 5 225H, RAM 32 GB, Intel Arc 130T dùng **CPU** trong
benchmark này. Hai backend dưới đây không được cấu hình cho Intel GPU/NPU.
Shared GPU memory không được coi là CUDA VRAM. Không chọn `--device cuda`
trên máy này. `--threads 8` là điểm bắt đầu có thể điều chỉnh, chưa được đo tối ưu.

| Tên CLI | Checkpoint nguồn | Backend | Mặc định CPU |
|---|---|---|---|
| `whisper-small` | `openai/whisper-small` | Transformers | FP32 |
| `phowhisper-small` | `vinai/PhoWhisper-small` | Transformers | FP32 |
| `phowhisper-medium` | `vinai/PhoWhisper-medium` | Transformers | FP32 |
| `whisper-turbo` | `openai/whisper-large-v3-turbo` | Transformers | FP32 |
| `whisper-small-ct2` | Cùng snapshot `openai/whisper-small` | faster-whisper/CTranslate2 | INT8 |

faster-whisper là engine, không phải checkpoint thứ năm. So sánh CPU mặc định
đồng thời thay engine và precision; không quy mọi khác biệt về engine.
Có thể chạy lại cặp small với `--dtype float32 --compute-type float32`.
Conversion lưu FP32 để cùng một bản CT2 có thể chạy FP32 hoặc INT8.

Nguồn chính thức đã đối chiếu model IDs và API:
[Whisper-small](https://huggingface.co/openai/whisper-small),
[PhoWhisper-small](https://huggingface.co/vinai/PhoWhisper-small),
[PhoWhisper-medium](https://huggingface.co/vinai/PhoWhisper-medium),
[Turbo](https://huggingface.co/openai/whisper-large-v3-turbo),
[Transformers Whisper 4.57.1](https://huggingface.co/docs/transformers/v4.57.1/en/model_doc/whisper),
[faster-whisper 1.2.1](https://github.com/SYSTRAN/faster-whisper/tree/v1.2.1),
[CT2 converter](https://opennmt.net/CTranslate2/python/ctranslate2.converters.TransformersConverter.html).
Model card hiện ghi Apache-2.0 cho Whisper-small, BSD-3-Clause cho PhoWhisper,
MIT cho Turbo. `prepare` lưu metadata license, snapshot SHA, ngày commit và
hash tài nguyên; giữ cả README/LICENSE upstream nếu có. Đối chiếu giấy phép
và quy định BTC trước khi dùng cho submission.

## Cài trên Windows

Python 3.11–3.13 x64. Chỉ cài các dependency bên dưới khi chuẩn bị chạy model.
Các lệnh cài đặt cần mạng; không có lệnh cài hay tải nào được thực thi tự động
bởi `run`.

```powershell
Set-Location 'C:\Users\Windows\Downloads\ZaloAI\JarvisMate'
py -3.13 -m venv .venv
$python = '.\.venv\Scripts\python.exe'
& $python -m pip install --upgrade pip
& $python -m pip install -e ./python

# Transformers + chuẩn bị/conversion checkpoint; lấy PyTorch bản CPU.
& $python -m pip install torch==2.9.0 --index-url https://download.pytorch.org/whl/cpu
& $python -m pip install -r asr/pretrained/requirements-transformers.txt

# Backend faster-whisper/CTranslate2.
& $python -m pip install -r asr/pretrained/requirements-ct2.txt
& $python -m asr.pretrained --help
```

Launcher `py` trong phiên authoring trỏ tới đường dẫn đã mất. Nếu `py -3.13`
báo `cannot find the file specified`, executable đã xác nhận hoạt động tại máy
này là đường dẫn dưới; dùng nó thay dòng tạo venv bên trên:

```powershell
$basePython = 'C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.13_3.13.3824.0_x64__qbz5n2kfra8p0\python3.13.exe'
& $basePython -m venv .venv
```

Đường dẫn WindowsApps có thể thay đổi sau khi cập nhật Python. Mỗi backend import
dependency một cách lazy; split, metrics và test không cần Torch/NumPy/GPU.
Chỉ chạy Transformers thì không cần file requirements CT2. Chạy CT2-only với
snapshot đã chuẩn bị trên máy khác chỉ cần requirements CT2 và package `./python`.

## Tạo và giữ nguyên split

Data root phải trực tiếp chứa `train/`:

```powershell
$dataRoot = (Resolve-Path '../train+public_test/train+public_test').Path
& $python -m asr.pretrained split --data-root $dataRoot
```

Lệnh chỉ đọc `train/train.jsonl` và WAV dưới `train/audio/`, kiểm tra mono 16 kHz,
16-bit PCM, WAV không rỗng/không truncated, tối đa 30 giây. Transcript phải thuộc
chính object của lượt user tương ứng; thiếu asset/reference thì dừng, không skip.
Mọi user-history được kiểm tra để grouping ngay cả khi chỉ benchmark lượt hiện tại.
Không đọc file dưới `*_environment/`; không dùng public_test.

Grouping chạy trước khi chọn/expand scope benchmark:

1. Giữ toàn bộ utterance của source sample cùng nhóm.
2. Nối các sample dùng PCM cùng SHA256, user text normalized trùng, hoặc template
   trùng sau khi thay chuỗi chữ số bằng `#`.
3. Nối gần trùng nếu character-trigram Jaccard >=0.85 **và** SequenceMatcher
   ratio >=0.92. Shared user-history/prefix cũng nối các conversation.
4. Lấy thành phần liên thông, shuffle nhóm bằng seed 42, phân bổ nguyên nhóm
   gần 20% validation nhất theo thuật toán greedy đã version hóa.

Không phá nhóm để ép 80/20. Nếu chỉ còn một nhóm thì dừng và yêu cầu xem lại
dataset/policy trong một experiment mới. Detector là heuristic, chưa phát hiện
được mọi paraphrase, biến thể tên riêng hay bản thu khác của cùng lời nói;
template và câu user chung cũng có thể gom quá nhiều sample. Manifest ghi
policy, link counts, largest group, số lượng/tỉ lệ thực tế và hash nguồn.

Đầu ra mặc định `.agent-work/asr-benchmark/split42.json` có transcript, WAV/PCM
hash, sample/turn IDs, group, partition và identity. File có sẵn sẽ không bị ghi đè.
Tái sử dụng nguyên file cho mọi model; đổi dataset/policy phải tạo experiment mới.
Đây là split **ASR seed 42**, tách biệt seed planner 20261027 trong roadmap.

Trong workspace này split đã được tạo bằng lệnh trên, **không cần chạy lại**:
1.545 source sample, 5.036 user WAV, 1.323 nhóm, largest group 126;
Train 1.236 sample, Validation 309 sample (20%). Scope `current` có 309 utterance;
`with-history` có 953 utterance. Identity:
`da6b2725c4a7136e66e6ee93d2cda9a30561edd0905b4a78b258de35996dfcfa`.
Các con số này mô tả audit/split dữ liệu, không phải kết quả nhận dạng.

## Chuẩn bị local model trước benchmark

Đây là bước **chủ động tải weights qua mạng**, chỉ chạy khi bạn chuẩn bị benchmark:

```powershell
# Bắt đầu với small chạy CT2; chuẩn bị cả HF source và conversion CT2 cùng SHA.
& $python -m asr.pretrained prepare --models whisper-small-ct2

# Hoặc chuẩn bị toàn bộ 4 checkpoint nguồn và conversion small.
& $python -m asr.pretrained prepare --models all
```

Snapshots nằm trong `.agent-work/asr-benchmark/models/<name>/`. `prepare` resolve
`main` thành immutable commit SHA, kiểm tra ngày commit **trước 2026-10-26 UTC**,
tải tokenizer/processor/config/weights, ghi `provenance.json` và hash từng file.
Nếu revision mới hơn cutoff thì chọn một commit cũ có đủ license/eligibility:

```powershell
# Thay bằng SHA từ provenance hoặc lịch sử publisher; mỗi source có SHA riêng.
& $python -m asr.pretrained prepare --models phowhisper-small --revision '<40-character-commit-SHA>'
```

Không dùng SHA của Whisper cho PhoWhisper/Turbo. Khi tái lập, dùng đúng SHA gốc,
không resolve lại `main`. Snapshot hoàn chỉnh được xác minh hash rồi reuse.
Nếu download đã hoàn tất nhưng bước ghi metadata lỗi, chạy lại `prepare` để tiếp tục:
code giữ revision trong metadata cache của config và để Hub reuse các file đã tải,
không cần xóa weights. Snapshot đã có provenance nhưng hash bị đổi vẫn fail.
Dùng `--models-dir .agent-work/asr-benchmark/models-new` khi muốn chuẩn bị revision
khác; không trộn revision vào một snapshot đang dở.

Sau lỗi `KeyError: 0` ở phiên bản cũ, chỉ cần chạy lại sau khi cập nhật code:

```powershell
& $python -m asr.pretrained prepare --models all
if ($LASTEXITCODE -eq 0) {
    & $python -m asr.pretrained run --models whisper-small-ct2 --limit 5
}
```

Conversion dùng `TransformersConverter(local_snapshot, copy_files=["tokenizer.json",
"preprocessor_config.json"], trust_remote_code=False).convert(...,
quantization="float32")`. Sau conversion lưu source SHA/hash, API và package versions.
`run` xác minh tài nguyên local, không dùng model ID online. Khi chạy cặp small,
khác revision hoặc source hashes thì từ chối so sánh. Thiếu tokenizer CT2 cũng
bị từ chối, tránh fallback download trong backend.

## Chạy benchmark

Luôn chạy từ repo root. `$python` là `.\.venv\Scripts\python.exe` đã cài ở trên.
Mỗi lần dùng thư mục kết quả mới; bỏ `--run-dir` để tự tạo tên theo thời gian.

```powershell
# Smoke với 5 lượt validation, kiểm tra cài đặt; chưa phải benchmark đầy đủ.
& $python -m asr.pretrained run --models whisper-small-ct2 --limit 5

# Toàn bộ 309 lượt hiện tại của Validation trên máy Raccoon.
& $python -m asr.pretrained run --models whisper-small-ct2 --device cpu --threads 8

# Một checkpoint khác, sau khi đã prepare nó.
& $python -m asr.pretrained run --models phowhisper-small --device cpu --threads 8

# Toàn bộ 5 cấu hình, tuần tự mỗi lần một model.
& $python -m asr.pretrained run --models all --device cpu --threads 8

# Cặp cùng checkpoint, cùng FP32; vẫn có khác biệt backend được ghi trong manifest.
& $python -m asr.pretrained run --models whisper-small whisper-small-ct2 --dtype float32 --compute-type float32

# Experiment bổ sung history: dùng cùng split, báo cáo scope riêng.
& $python -m asr.pretrained run --models all --scope with-history
```

`--data-root`, `--split-manifest`, `--models-dir` cho phép chỉ định vị trí khác;
weights, split và artifacts phải ở dưới `.agent-work/` ignored. `--limit` lấy prefix
của Validation theo manifest và luôn ghi `partial_selection=true` cùng selection
identity riêng. Không so kết quả prefix/current với full/with-history như cùng corpus.

Máy NVIDIA A30: cài PyTorch CUDA phù hợp trên host đó, cùng các runtime CUDA/cuDNN
theo [hướng dẫn faster-whisper](https://github.com/SYSTRAN/faster-whisper/tree/v1.2.1#gpu).
Copy nguyên split và đúng snapshots, giữ versions, rồi chạy:

```powershell
& $python -m asr.pretrained run --models all --device cuda --dtype float16 --compute-type float16
```

Mặc định 1 warm-up, inference seed 42, timeout mỗi utterance 600 giây và model-load
timeout 600 giây. Điều chỉnh bằng `--warmup`, `--seed`, `--timeout-seconds`,
`--load-timeout-seconds`; không thay split. Budget này dành cho benchmark CPU,
không phải giới hạn 30 giây của pipeline thi.

## Protocol đo và metrics

Worker chỉ nhận config và đường dẫn WAV. Reference được evaluator dùng sau prediction.
Mỗi model nạp một lần, warm-up bằng WAV đầu tiên, rồi đo tuần tự. Seed cố định,
Vietnamese transcription, greedy beam 1, temperature 0, tối đa 440 token mới;
VAD, timestamps, conditioning từ lượt trước, prompts/hotwords và temperature
fallback đều tắt. CT2 tắt cả silence/log-prob/compression skip. Suppression defaults
được ghi riêng vì cách HF/CT2 xử lý blank/token có thể khác nhau.

Latency đo trong worker bằng `perf_counter`, gồm đọc WAV, decode PCM, feature
extraction, copy device, generate và text decoding. CUDA đồng bộ trước/sau đo;
CT2 consume hết iterator segment trước khi kết thúc. Hash/preflight, load model,
warm-up, IPC, evaluator và ghi artifact nằm ngoài latency. Model-load và warm-up
ghi riêng. WAV đã được preflight/warm-up nên đây không phải cold-disk benchmark.

Parent giám sát timeout cứng bằng tiến trình: terminate/kill worker đang kẹt,
không retry; dừng cấu hình đó, đánh dấu phần còn lại `not_run`, rồi mới nạp model
kế tiếp. Timeout đo bằng parent wall clock có cả IPC, được nêu riêng trong protocol.
Load/warm-up failure lưu lỗi ở manifest và đánh dấu mọi utterance `not_run`.

- Corpus WER = tổng `(S+D+I)` / tổng số reference token, không lấy trung bình WER câu.
  Token WER tách theo whitespace, tức gần đơn vị âm tiết tiếng Việt, không word segmentation.
- Corpus CER dùng Unicode code point, **tính cả khoảng trắng**. Raw giữ nguyên case,
  Unicode và punctuation; normalized dùng NFC, lower, punctuation thành space,
  collapse whitespace. Version `vi-nfc-lower-punctuation-space-v1`.
- Giữ dấu và chữ số; không đổi số thành chữ. Ví dụ `12:30` thành `12 30`, không
  bị xóa. Ký hiệu không thuộc Unicode punctuation, như `₫`, được giữ.
- Reference rỗng vẫn tính insertions; nếu toàn corpus có denominator 0, WER/CER
  là `null`/ô CSV trống và manifest vẫn giữ error counts.
- Lỗi/timeout/`not_run` được chấm với prediction rỗng; giữ nguyên denominator
  toàn bộ selection, kèm coverage. Không coi những dòng đó là prediction thành công.
- Mean latency, P95 nearest-rank `ceil(.95*N)` và RTF chỉ dùng các dòng đã đo,
  gồm inference errors/timeouts, loại `not_run`. RTF = tổng giây inference / tổng
  giây WAV của chính các dòng đã đo. Không dùng thời lượng chưa chạy để làm đẹp RTF.

Không báo entity accuracy vì chưa có ground truth entity đáng tin cậy. Số tham số
HF lấy từ model đã nạp; CT2 ghi số tham số kiến trúc source trên meta device và
nêu phương pháp, không giả định INT8 làm giảm số tham số. Có thể truyền
`--planner-parameters <actual-count>` để ghi kiểm tra planner <5B và ASR+planner <6B;
không có planner count thì trạng thái là chưa kiểm chứng. Kiểm tra này không
chứng minh context planner <=16.384 hoặc tổng thời gian Agent Pipeline <=30 giây.

## Artifacts và tái lập

```text
.agent-work/asr-benchmark/
  split42.json
  models/<configuration>/provenance.json
  runs/<timestamp>/
    manifest.json
    comparison.csv
    <configuration>/
      manifest.json
      transcripts.jsonl
```

CSV có một dòng/config đã chạy, raw/normalized WER/CER dạng tỉ lệ (0.1 = 10%),
mean/P95 giây, RTF, coverage, status, count lỗi/timeout/not_run, SHA và split identity.
Transcript JSONL có sample/turn/group/audio IDs, reference/prediction và normalized
text, WAV/PCM hashes, duration, latency/RTF, edit counts, status và lỗi.

Run manifest lưu Git revision/dirty status, command, split/selection identity,
scope, settings, hardware/driver khi đọc được, Python và package versions, protocol.
Manifest từng config lưu source SHA, conversion, hashes, actual compute type,
parameter-count method và thời gian load/warm-up. CSV thiếu model chưa bắt đầu nếu
người dùng ngắt toàn suite; kiểm tra manifest `interrupted` và danh sách configurations.
Exit `0`: đủ mọi lượt/config; `1`: inference/load không hoàn tất; `2`: input/preflight/
dependency error; `130`: người dùng ngắt.

Trước khi so kết quả, kiểm tra `completed`, coverage, scope và selection identity.
Để tái lập máy khác: copy nguyên split, cùng dataset/audio hashes, model snapshots
và provenance; checkout cùng Git revision, cài cùng versions, ghi lại device/threads
và chạy cùng command. Lưu môi trường đầy đủ sau khi cài:

```powershell
& $python -m pip freeze | Set-Content -Encoding utf8 .agent-work/asr-benchmark/requirements-resolved.txt
```

Không commit WAV, corpus transcript, split, weights hay cache. `.agent-work/` đã
được repo ignore. Chưa có benchmark model thật nên chưa chọn model thắng;
chỉ quyết định accuracy/speed trade-off từ kết quả đo có coverage đầy đủ.

## Test và trạng thái xác minh

```powershell
& $python -m unittest discover -s asr/pretrained/tests -p 'test_*.py' -v
```

Ngày 27/10/2026: đã chạy 25 test nhẹ thành công bằng Python 3.13.14, gồm metrics,
normalization, grouping transitive/numeric/near text, source/asset integrity,
input whitelist, engine provenance và supervisor timeout/load failure; các WAV
trong test đều tự tạo. Test preparation giả lập download, kiểm tra metadata card,
resume sau lỗi, giữ weights/revision cũ và từ chối snapshot hoàn chỉnh bị sửa.
Đã chạy audit/split trên Train thật với số lượng ở trên.

Người dùng đã cài dependencies và tải Whisper-small. Đã xác minh getter license
với `ModelCardData` thật trong `.venv`, và kiểm tra cấu hình local bằng meta device:
241.734.912 tham số kiến trúc, không nạp weights. Chưa kiểm chứng conversion CT2,
chạy nhận dạng thật, GPU/A30, repeatability hoặc WER/CER/latency model.

Lệnh kiểm chứng đã chạy trong workspace (không cần cài inference dependencies):

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'python/src')
& $basePython -m unittest discover -s asr/pretrained/tests -p 'test_*.py' -v
& $basePython -m asr.pretrained split
```

Lỗi thường gặp: `No module named lifemate` → `pip install -e ./python` bằng đúng
interpreter; thiếu model/provenance → chạy `prepare` tách biệt trước `run`;
`Split manifest already exists` → reuse; asset/source hash đổi → khôi phục dataset
hoặc tạo experiment mới; CPU chậm → smoke `--limit 5` trước, xem timeout/coverage,
không bỏ mẫu lỗi hoặc suy diễn timing laptop sang A30.
