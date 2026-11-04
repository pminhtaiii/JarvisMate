# Review và implementation handoff — 29/10/2026; status update 04/11/2026

Review bắt đầu từ branch `fine-tuned-asr`, commit `c2aaad7`. Đã đối chiếu toàn bộ
specs/pretrained code, runtime ASR/contracts và benchmark rules trước implementation.
**Historical review:** lúc review ban đầu code đã viết nhưng PhoWhisper-large/GPU/full
training chưa chạy. Transfer note được bổ sung sau đó báo E0–E4 completed; xem phần
status update cuối file và [TRANSFER.md](TRANSFER.md) để tránh đọc nhầm trạng thái cũ.

## Các thiếu hụt đã xử lý

| Nhóm yêu cầu | Gap trước implementation | Thay đổi và kiểm tra |
|---|---|---|
| DATA | Chỉ có split/eval projection, chưa có fit exporter | `asr_training/data.py`: verify frozen identity/source/PCM/WAV, source-turn alignment, fit-with-history, Train dedup/provenance, full 309 current selection; test history không dùng nhầm transcript/context/labels |
| DEP | Pretrained registry thiếu large, guard 1B nội bộ | Đăng ký `phowhisper-large`; helper `lifemate/model_budget.py`, guard ASR standalone <6B và strict LLM <5B/combined <6B/context cap; logical counts không dùng packed NF4 storage |
| EXP | Chưa có E0–E4 scripts/configs | Thin scripts + `configs/common.json/e0..e4.json`, shared LoRA/trainer/evaluator; E1 decoder-only, E2 encoder+decoder, E3 NF4 có gate, E4 matched control + Train augmentation |
| Manual execution | Chưa có operator workflow | Shared CLI chỉ một experiment/invocation; suite lock, predecessor checks, preflight binding; tests E0/E1 dừng, E1 OOM không retry/không chạy E2 |
| ART/REP | Chưa có checkpoint/resume/result manager | `storage.py`, `checkpoints.py`: UUID run, atomic manifest, checksummed adapter+optimizer/scheduler/scaler/RNG/cursor, explicit resume, best/latest pointers, environment lock/code hashes |
| EVAL | Chưa có evaluator fine-tuning/CSA/report | Reuse corpus WER/CER và timing; full denominator khi lỗi; reviewed slot schema, proxy/unavailable phân biệt; model-free status/compare đủ 5 rows và variants, group bootstrap |
| GPU resources | Chưa có actual probe | `resources.py`/`workers.py`: CUDA/kernel/dtype checks, 12 GiB cap/headroom, phase allocated/reserved/free snapshots, hard worker timeout; GPU fitting vẫn chưa được kiểm chứng |
| DEP/export | Chưa có adapter merge/offline round-trip | Fresh nonquantized base + adapter merge, local export/hash, new-process generation/re-evaluation; outbound network blocked trong workers; tiny CPU round-trip test |

Smoke test generation phát hiện `forced_decoder_ids=None` có thể lọt xuống
`Whisper.forward()` khi generation config không có thuộc tính legacy. Đã bỏ
keyword cũ trong shared generation, pretrained adapter và runtime ASR; vẫn truyền
`language=vi`, `task=transcribe`. Tiny real PEFT `generate()` và runtime regression pass.

## Module map thực tế

- Data/config/policy: `data.py`, `config.py`, `augmentation.py`, `slots.py`,
  `selection.py`, `lifemate/model_budget.py`.
- Model/training: `models.py`, `trainer.py`, `resources.py`, `checkpoints.py`.
- Process/lifecycle: `workers.py`, `orchestration.py`, `execution.py`, `exporting.py`.
- Artifacts/operator: `storage.py`, `reporting.py`, `cli.py`, `__main__.py`.
- Scripts/configs/requirements trong `asr/fine-tuned/`; package trong
  `python/src/lifemate/asr_training/`; tests `python/tests/test_asr_training*.py`.

## Execution evidence thực tế

Host kiểm chứng: Python 3.13.14, Torch `2.9.0+cpu`, Transformers `4.57.1`, NumPy
`2.3.4`. PEFT `0.17.1` / Accelerate `1.10.1` cài `--no-deps --target` vào ignored
`.agent-work/asr-test-deps`; không nâng cấp Torch CPU hiện tại hoặc tải model weights.

```powershell
$python = (Resolve-Path '.\.venv\Scripts\python.exe').Path
$env:PYTHONPATH = (Join-Path (Get-Location) '.agent-work/asr-test-deps') + ';' + (Join-Path (Get-Location) 'python/src')
& $python -m unittest discover -s python/tests -p 'test_asr_training*.py' -v
& $python -m unittest discover -s asr/pretrained/tests -p 'test_*.py' -v
& $python -m unittest discover -s python/tests -p 'test_inference.py' -v
```

| Check | Kết quả |
|---|---|
| Fine-tuning policy/data/manual lifecycle/slot/memory/tiny tests | **39 pass**, không skip |
| Pretrained benchmark regression | **25 pass** |
| Runtime adapter regression | **12 pass** |
| Tiny real Whisper + PEFT | Forward/backward, exact decoder/encoder scope, frozen base, optimizer update, checkpointed backward, real generate, merge/reload offline |
| Resume | Optimizer/RNG restore tái tạo chính xác update kế tiếp trên tiny CPU model |
| Shared training loop | Gradient accumulation và last partial batch bằng fixtures/tiny CPU |
| Compare | Chạy khi deny Torch/model construction, giữ failed/skipped/unsupported/not_run và null metrics |
| CLI/config/static | Cả 11 scripts `--help`, 5 config files, compile và giới hạn 20.000 bytes/file pass |

Các warnings generation config trong tiny fixtures không phải kết quả nhận dạng;
không có điểm model/VRAM GPU nào được suy ra từ những tests này.

## Giới hạn và việc người dùng cần chạy

- Export E4 có mặt local, nhưng export file-level không chứng minh GPU/profile
  compatibility trên host nhận. Khi dùng host khác, phải đối chiếu resource evidence
  đúng host/profile; không suy từ tên GPU hoặc standalone export.
- NF4 chỉ được coi là supported sau real quantization + backward/update + generation
  + fresh adapter reload trên GPU đó; không suy từ việc cài được bitsandbytes.
- CSA thật cần annotations 309 lượt và reviewed/validated extractor. Extractor
  declarative không tự hiểu mọi số tiền/thời gian/tên; chưa có gold thì unavailable.
- CUDA device peak toàn hệ thống chưa được NVML lấy mẫu: code báo PyTorch exact
  allocated/reserved peaks và device free snapshots, nêu rõ giới hạn đo context/external allocators.
- Transfer record báo E0–E4 completed, và standalone E4 export đã được hash-verify
  local (xem status update). Run artifacts gốc không có trong checkout này nên không
  thể tái tính WER/CER/selection ở đây. Joint Qwen VRAM, Tool-call F1/authoritative
  Final State Match và A30/container 30 giây/mẫu vẫn chưa được xác nhận trong evidence
  đang xem.
- Cả pipeline scorer và semantic correctness không được dựng từ WER/CER. Candidate
  không đủ evidence thì giữ E0/provisional, không mặc định fine-tuning thắng.

Lệnh thực tế Prepare/E0 rồi từng experiment riêng, skip/resume/export/final compare:
[RUNBOOK.md](RUNBOOK.md). Checklist acceptance trong [tasks.md](tasks.md) cần được
đối chiếu với artifact gốc trước khi đóng.

## Status update — 04/11/2026

- [TRANSFER.md](TRANSFER.md) ghi E0–E4 `completed`, artifact-only comparison có
  5 valid runs; E4 có 2.560 updates và best step 2.048.
- Export standalone hiện có tại
  `C:\Users\Windows\Downloads\ZaloAI\ASR_E4(Lora+Aug)\best` (tương đối từ repo
  root: `..\ASR_E4(Lora+Aug)\best`). `export-metadata.json`
  xác nhận PhoWhisper-large, base revision
  `b9136a44b5f2ca664bd0b8f74baecf1715f6eeeb`, FP16 merged base+adapter, logical
  parameters 1,543,304,960. 12/12 file khớp hash trong `files.json`; hash model
  weights là `acd40183ee145a099538eb72f841fd1795852464b1b1b4acba1c4ab7c952286e`.
- Suite run/comparison artifacts gốc không có trong workspace repo hiện tại, nên
  metrics và toàn bộ provenance của các run chưa được kiểm tra lại ở checkout này.
  Theo transfer record, E4 vẫn provisional vì thiếu semantic-slot metric.
- Chưa có formal `llm-handoff.json`/cache certificate trong artifact standalone;
  sự hiện diện và hash-valid của model không tự tạo selection approval, không
  hoàn thành Fit/Validation ASR caches, và không chứng minh A30/deployment acceptance.
