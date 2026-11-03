# LifeMate trên Kaggle

Pipeline: ASR `zaic` (Whisper-medium fine-tune, 764M tham số) → LLM `Qwen/Qwen3-4B-Instruct-2507` (4,02B, gọi tool kiểu `<tool_call>`) → `zaic_tools`.
Tổng khoảng 4,8B tham số, dưới giới hạn 6B (LLM < 5B). Decode greedy, seed cố định.

LLM ban đầu là `Bingguang/FunReason-MT`. Sau 10 lần chạy, model này bị thay vì nó luôn suy nghĩ dài và xuất tool call theo hơn 10 định dạng khác nhau. Trên Train (transcript gốc) nó chỉ đạt 0,00–0,10 điểm, mất 40–100 giây mỗi mẫu trên T4. Vẫn dùng lại được bằng `--llm-model Bingguang/FunReason-MT --think-budget 256`.

| File | Vai trò |
|---|---|
| `lifemate_infer.py` | Script chính. Chạy được độc lập: `python lifemate_infer.py --help` |
| `lifemate_kaggle.ipynb` | Notebook để upload lên Kaggle. Được sinh từ script và chứa sẵn script cùng ô prompt |
| `output/` (gitignored) | `submission.jsonl`, `traces.jsonl`, log và transcript ASR của lần chạy Kaggle gần nhất |

## Chạy trên Kaggle

1. Tạo 2 Kaggle Dataset: một cái từ `train+public_test.zip`, một cái từ `zaic-20261102T164447Z-1-001.zip`. Kaggle tự giải nén.
2. *New Notebook* → *File → Import Notebook* → chọn `lifemate_kaggle.ipynb`. *Add Input* cả 2 dataset.
3. Settings: GPU T4 x2, bật Internet (để tải Qwen3-4B-Instruct-2507, khoảng 8 GB).
4. Dán prompt của bạn vào ô `%%writefile system_prompt.txt`. Sau đó *Save Version → Save & Run All*.
5. Các bước notebook tự chạy:
   - Smoke test 5 mẫu. Dừng nếu không có tool call nào.
   - So sánh có/không few-shot trên 30 mẫu Train, chọn cấu hình tốt hơn.
   - Chỉ chạy toàn bộ public_test nếu điểm Train ≥ `MIN_SCORE` (0,25). Mỗi GPU chạy một nửa số mẫu.
   - Validate file nộp.
6. Tải `/kaggle/working/submission.jsonl` ở tab Output. Log in từng mẫu gồm `nghe:` (transcript ASR) và `gọi :` (tool call).

## Hành vi chính

- **ASR**: chạy theo batch cho mọi lượt user (cả history), cache vào `transcripts_<split>.json`. Trên 40 clip Train, WER là 0,107 so với `audio_text`.
- **Vòng lặp agent**:
  - Mỗi bước, LLM có thể gọi một hoặc nhiều tool.
  - Một lô call chỉ chạy tới call `read` đầu tiên, để model xem kết quả rồi mới quyết định bước tiếp. Đây là cách xử lý yêu cầu "nếu … thì …".
  - Giới hạn tối đa `--max-steps 10` bước.
- **Bảo vệ điểm**: các call dưới đây không được gửi tới env; model nhận lỗi để tự sửa.
  - Call sai schema, kiểm bằng `env.validate()`, vốn không ghi log.
  - Call trùng một call đã thành công.
  - Call có ID (`x-ref`) hoặc số điện thoại chưa xuất hiện trong ngữ cảnh, history, kết quả tool hay lời người dùng. Trên cả 1.545 mẫu Train, bước kiểm này chỉ chặn nhầm 2/3.541 call gold.
- **Tham số tùy chọn hiếm**: tự bỏ những tham số xuất hiện trong dưới 10% call gold Train của tool đó (36 tham số; ảnh hưởng 32/3.541 call gold). Tắt bằng `--no-prune`.
- **Few-shot**: 3 mẫu Train đã giải, lấy từ mẫu thứ 200 trở đi nên không trùng tập đánh giá. Gồm điều kiện sai thì dừng, `contacts.search` trước `phone.call`, `get_status` trước khi set. Tắt bằng `--no-few-shot`.
- Mỗi mẫu dùng đúng một `ToolEnv`, không đọc `state.json`.
- `--eval` (chỉ Train): chấm cục bộ theo cách hiểu công thức của đề. Thêm `--gold-transcript` để đo riêng LLM.

## Kết quả đo

Kaggle, notebook version 12, ngày 2026-11-03, 2× T4:

| Cấu hình | Train 30 mẫu, transcript gốc (`--split train --limit 30 --eval --gold-transcript`) | Tốc độ |
|---|---|---|
| Qwen3-4B-Instruct + few-shot | **0,400** | 12,5 s/mẫu |
| Qwen3-4B-Instruct, không few-shot | 0,333 | 10,7 s/mẫu |

Chạy public_test (634 mẫu, ASR thật):
- `zaic_tools --validate`: 634/634 dòng, 0 lỗi schema.
- 58 mẫu không có tool call; 34 mẫu gọi `ask_missing_info`.
- Trung bình 11,8 s/mẫu (p90 20,4 s) trên T4.
- **Chưa có điểm public_test** vì cần nộp lên leaderboard.

Chưa đạt yêu cầu: giới hạn của đề là 30 s/mẫu trên A30, nhưng chưa đo trên A30. Điểm Train 30 mẫu chỉ là ước lượng có độ nhiễu lớn.
