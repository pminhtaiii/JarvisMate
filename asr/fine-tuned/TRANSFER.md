# ASR từ JarvisMate_4 sang JarvisMate_5

Đích thực tế: `D:\JarvisMate_5\JarvisMate`, branch `fine-tune-llm`.
Ngày chuyển: 2026-11-01. Không train, export lại hoặc inference model thật.

Đã copy **6.783 file / 30.022.528.633 bytes** và đối chiếu SHA-256 từng file:
checkpoints, optimizer/RNG state, exports, logs, evaluations, comparisons E0–E4;
prepared ASR data, split42, base PhoWhisper-large, noise và manifest E4;
Train JSONL/catalog/audio. Không copy E5, ZIP, venv, public-test runs hoặc hidden
environment. Nguồn được giữ nguyên. Data/weights/logs đều ignored.

Receipt và hash từng file:
`.agent-work/asr-transfer-20261101/receipt.json`.
Bổ sung source/reporting/tests từ `_4` có backup và hash trước/sau trong
`source-sync.json` cùng thư mục. Không ghi đè các thay đổi planner/runtime ở `_4`
lên kiến trúc LLM native của `_5`.

## Đường dẫn vận hành

Suite: `.agent-work/asr-finetune/suite-01`.
E4 export dùng local:

```text
.agent-work/asr-finetune/suite-01/E4/run-20261030-181019-690223-4edc064ec9/exports/best
```

`operational-paths.json` trong suite liệt kê đầy đủ checkpoint/evaluation/export
E0–E4 đã quy về `_5`. `relocation.json` khai báo mapping `_2`/`_4` → project hiện
tại, ràng buộc SHA-256 của suite gốc. ASR loader, status, compare và các boundary
đọc asset dùng mapping này. File manifest/log lịch sử giữ nguyên bytes/identity;
đường dẫn cũ trong đó là provenance, không phải đường dẫn cần sửa tay. Không
search/replace rồi seal lại kết quả cũ. Mapping không cho thoát root hoặc đọc
`*_environment/`/`*_enviroment/`.

```powershell
Set-Location 'D:\JarvisMate_5\JarvisMate'
& ./.venv-llm/Scripts/python.exe -m lifemate.asr_training status --suite-dir .agent-work/asr-finetune/suite-01
```

Status đã xác nhận cả E0–E4 `completed`. Artifact-only comparison đã chạy riêng,
nhận **5 valid runs**, tại:
`.agent-work/asr-finetune/suite-01/comparisons/20261101-155755-931467-8987e9`.
E4 ghi 2.560 updates, best step 2.048. Recommendation E4 vẫn **provisional** vì
thiếu semantic-slot metric; di chuyển không biến nó thành deployment acceptance.
Checkpoint cũ giữ code/environment binding cũ, không tự được phép resume sau
đổi source/profile. Tuning LLM là suite khác, không resume ASR hoặc adapter Qwen cũ.

## Kiểm tra sau chuyển

- 52 ASR tests pass, gồm fixtures reporting từ `_4`, relocation với path chứa
  khoảng trắng, containment, stale-map rejection và random tiny Whisper CPU.
- LLM regression chạy riêng; exact outcome trong
  `.agent-work/llm-implementation/checks/LLM-after-ASR-import-*`.
- ASR status và artifact-only compare là hai invocation riêng; không load model.
- Qwen snapshot hiện có cũng được copy local, giữ đúng weight/acquisition identity;
  receipt riêng `qwen-receipt.json`: 24 file / 8.060.909.270 bytes. Tổng hai đợt
  chuyển là 38.083.437.903 bytes. Không tải model.

## Kết nối với tuning LLM

Config local: `.agent-work/llm-finetune/local-suite.json`. Data/split/model paths
đã trỏ resource local `_5`; `asr_model_dir` trỏ **candidate E4** ở trên.
Formal selected-ASR `llm-handoff.json` và Fit/Validation turn caches vẫn chưa được
chứng nhận/tạo. Không tự dựng selection certificate từ tên directory hoặc chuyển
309 current transcripts thành cache current+history đầy đủ. Xem
[ASR_HANDOFF](../../fine-tune-llm/ASR_HANDOFF.md).

Clean L1/L2 dùng gold audio_text và không cần ASR cache. A/full-audio/L3 vẫn phải
đáp ứng handoff/selection/cache riêng. Lệnh tuning nằm ở
[TUNING_LOCAL.md](../../fine-tune-llm/TUNING_LOCAL.md).
