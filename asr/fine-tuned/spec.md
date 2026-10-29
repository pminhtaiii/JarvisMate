# Specification: PhoWhisper-large E0–E4

**Version:** 1.0. **Ngày:** 29/10/2026. **Status:** design only.
Phạm vi được yêu cầu là viết specs; các yêu cầu dưới đây dành cho implementation tiếp theo.

## Mục tiêu và phạm vi

Fine-tune `vinai/PhoWhisper-large` bằng parameter-efficient adaptation trên audio
LifeMate Train và `audio_text`. So sánh với chính pretrained large bằng cùng
Validation, tập trung giữ đúng nội dung và các thông tin quan trọng trong lời nói.
Qwen3-4B giữ nguyên weights/prompt khi đánh giá tác động của ASR.

Không full fine-tune 1,55B mặc định, không train planner, không tự mở rộng dữ liệu
bằng Public/Private Test, không gọi external ASR/LLM để tạo nhãn. Không cần ToolEnv
cho training ASR, WER/CER hoặc annotation slot từ lời nói.

## Split và dữ liệu

Manifest duy nhất: `.agent-work/asr-benchmark/split42.json` tính từ repo root.

| Thuộc tính | Giá trị đã kiểm tra |
|---|---|
| Seed / policy | 42, `asr-grouped-split-v1`; grouping đã lưu trong manifest |
| Split identity | `da6b2725c4a7136e66e6ee93d2cda9a30561edd0905b4a78b258de35996dfcfa` |
| Source JSONL SHA256 | `24c42c79fbe8db932fe9817d041c0d0ca422ac8177b413cc1be0cda1fd8941a8` |
| Source samples | 1.545; Train 1.236, Validation 309 |
| User utterances | Train 4.083, Validation 953, tổng 5.036 |
| Primary evaluation | 309 lượt `current` của Validation, thứ tự manifest |
| Primary selection identity | `eae949cf454e0d064d1c939303d4cde65a947dc2a2b40f18bcb9c8227ddff01c` |

**DATA-01.** Không tạo lại split, shuffle membership hoặc dùng seed planner 20261027.
Xác minh identity, source hash, group membership và selected WAV/PCM hashes trước run.
Manifest không có trên máy GPU thì chuyển nguyên manifest cùng dataset; không tái chia.

**DATA-02.** Default fit scope là `with-history`: current và từng user-history của
1.236 sample Train. E1–E4 dùng cùng fit manifest đã freeze. Không lấy bất kỳ lượt
history nào thuộc source sample Validation vào fit, dù nó giống một câu Train.
Primary Validation giữ scope `current`; scope `with-history` 953 lượt là diagnostic
riêng, không trộn vào bảng chính. E0 không dùng fit rows để cập nhật model.

**DATA-03.** Mỗi row chỉ chiếu `sample_id`, `group_id`, `partition`, `turn_id`,
`utterance_id`, đường dẫn/hash WAV, duration và `audio_text` của **chính object
user-turn đó**. Current transcript không được gán cho history. Assistant text,
context, label, gold tool calls/results không đi vào ASR training/inference.

**DATA-04.** Kiểm tra WAV PCM mono 16 kHz 16-bit, payload đủ, 0 < duration <=30s,
reference không rỗng và giới hạn token decoder thực tế. Không crop audio, truncate
labels, tự sửa transcript hoặc skip im lặng. Ghi từng lỗi alignment/asset; lỗi
chưa giải quyết chặn suite, không chỉ bỏ hàng Validation để tăng score.

**DATA-05.** Audit duplicate PCM/cặp audio-text, shared utterances và group overlap.
Training có thể dedup cùng PCM + cùng normalized reference, giữ provenance mọi ID
và đại diện theo thứ tự manifest; audio khác cùng transcript vẫn giữ. PCM giống
nhưng transcript mâu thuẫn cần review. Freeze policy/danh sách fit trước E1 và dùng
lại E2–E4. Không dedup Validation hoặc đổi partition để xử lý trùng liên partition.

**DATA-06.** Nếu phát hiện lỗi gold cần sửa, giữ nguyên bản gốc và ghi audit;
dataset đã sửa là version/experiment mới, chạy lại E0–E4 liên quan. Không đối chiếu
điểm của hai phiên bản reference như cùng một benchmark.

**DATA-07.** Không đọc/copy/parse/index bất kỳ file dưới `*_environment/` hoặc
`*_enviroment/`. Không dùng Public/Private Test cho training, tuning, augmentation,
annotation phục vụ tuning, prompt examples hoặc chọn checkpoint.

## Experiments và tài nguyên

**EXP-01.** Thực hiện E0 → E1 → E2 → E3 → E4 theo [experiments.md](experiments.md).
Experiment sau chỉ bắt đầu khi trạng thái experiment trước được ghi rõ; `skipped`
hoặc `unsupported` hợp lệ khi có lý do/evidence, không giả thành một lần chạy thành công.

**EXP-02.** E0 dùng snapshot pretrained large gốc. E1/E2/E3 khởi tạo lại từ cùng
snapshot, không nối tiếp checkpoint của nhau. E4 cũng khởi tạo từ pretrained large;
chỉ khác augmentation so với cấu hình LoRA đối chứng đã chọn từ E1/E2.

**EXP-03.** Trên single GPU có giới hạn vận hành 12 GiB: probe phải đo card name,
total/free VRAM, CUDA capability/driver và test kernel thật. Không nạp Qwen đồng
thời với training ASR. LoRA/QLoRA không được mặc định chạy vừa GPU chỉ vì ít trainable parameters.

**EXP-04.** FP16 hoặc BF16 đã probe, batch nhỏ, gradient accumulation và gradient
checkpointing; log toàn bộ effective config. LoRA base frozen, optimizer chỉ giữ
trainable adapter. Test gradient/update đúng module; không có gradient thì fail.

**EXP-05.** QLoRA phải chứng minh 4-bit modules được nạp thật, Whisper forward với
`input_features`, backward, optimizer, generation và adapter save/reload hoạt động.
Không suy tương thích 4-bit từ tutorial Whisper int8 hoặc ví dụ LLM.

**EXP-06.** Augmentation chỉ tác động audio Train và giữ cặp transcript; không
augment Validation, không fit transform/noise distribution bằng Validation.
Không thêm tiếng nói ngoài không rõ nhãn/giấy phép. Hash/seed mỗi phiên bản dữ liệu.

## Đánh giá, artifacts và tái lập

**EVAL-01.** Full primary coverage 309/309, cùng ASR input/decoding/timing protocol,
raw + normalized corpus WER/CER, mean/P95 latency, RTF, training/inference peak VRAM.
Thiếu mẫu/lỗi/OOM/timeout giữ nguyên denominator, ghi status và lý do.

**EVAL-02.** Critical Slot Accuracy (CSA) có annotation/reference và extractor
version hóa theo [evaluation.md](evaluation.md). Báo cáo theo từng loại, precision/
recall/F1 và coverage để không giấu hallucination. Thiếu gold thì `null`/`unavailable`;
regex chưa kiểm chứng chỉ được ghi `proxy`, không đổi tên thành accuracy chuẩn.

**EVAL-03.** Không giả định model thắng. Checkpoint selection và promotion dùng
policy freeze trước E1. Model tốt nhất không đạt điều kiện cải thiện thì giữ E0;
có thể kết luận fine-tuning chưa đem lại lợi ích.

**ART-01.** Có `comparison.csv` đủ E0–E4 kể cả không chạy, per-utterance predictions,
manifest, hyperparameters, adapter/best checkpoints, source/environment/code hashes,
OOM logs, augmentation provenance và export metadata; xem [plan.md](plan.md).

**REP-01.** Seed training/inference mặc định 42; ghi Python/NumPy/Torch/CUDA,
sampler, augmentation RNG, deterministic flags, optimizer/scheduler/scaler state.
Resume phải explicit và kiểm tra hashes/config/partition; không tự retry OOM bằng
config khác rồi giữ nguyên tên run. Log số lần xem Validation/chọn hyperparameters.

## Deployment và giới hạn BTC

**DEP-01.** Model, processor/tokenizer, adapter hoặc merged weights phải load local
offline, `trust_remote_code=False`; thiếu file/hash sai thì fail, không tải ngầm.
Giữ contract `ASR.transcribe(audio_path, remaining_seconds) -> str` cùng metadata
của [Python runtime](../../python/src/lifemate/contracts.py); deadline được tôn trọng,
không fallback ground truth/context. Export có round-trip test.

**DEP-02.** Guard ASR <1B còn trong benchmark/preparation là policy nội bộ,
**không phải rule BTC**. Runtime `LocalASR` trên `main` đã nới guard; giữ hỗ trợ đó
và cho phép checkpoint PhoWhisper-large được xác minh ở các đường còn lại;
vẫn đếm riêng LLM <5B, tổng deployed models <6B, context planner <=16.384.
Phép tính khoảng 1,55B+4B chỉ là ước lượng; đếm shared tensors đúng một lần trong
mỗi model, tính adapter chưa merge và mọi model bổ sung. Không trừ parameters
vì INT8/4-bit hoặc vì unload model tạm thời.

**DEP-03.** Giữ Qwen prompt/tool policy và một ToolEnv/sample. Nếu pipeline/evaluator
đã sẵn sàng, so E0 với candidate bằng Tool-call F1 và Final State Match trên cùng
sample IDs, actual predicted calls; không đưa gold prefixes vào planner. Chưa có
authoritative evaluator thì metrics này `unavailable`, không suy hash từ `label.final_state`.

**DEP-04.** Khả năng train trên GPU 12 GB và đạt parameter budget không chứng minh
inference chung Qwen vừa VRAM hoặc kịp 30 giây/mẫu. Phải đo toàn pipeline riêng
trên target A30; dùng model/data/license phù hợp và source model công bố trước
26/10/2026 theo [benchmark rules](../../context/benchmark.md).

## Acceptance scenarios

| Tình huống | Kết quả bắt buộc |
|---|---|
| Manifest/asset thay đổi hoặc user-history ghép sai | Fail trước khi nạp model/train; audit chỉ rõ ID |
| E0 valid nhưng E1 OOM ở probe | Giữ E0, ghi `failed_oom`; không tự train E2; xem gate E3 |
| E1 chỉ chọn decoder nhưng encoder có adapter/gradient | Fail kiểm tra scope, không ghi E1 thành công |
| E2 không vừa VRAM | Giữ checkpoint E1, ghi lỗi; E3 chỉ thử sau compatibility probe |
| E3 có loss nhưng adapter không update hoặc generate lỗi | `unsupported`/failure, không báo QLoRA tương thích |
| E4 biến đổi WAV vượt 30s hoặc clipping | Từ chối transform đó theo policy cố định, log fallback; không truncate |
| Validation inference lỗi một lượt | Row lỗi và coverage <100%; không eligible promotion |
| Không có slot annotations hoặc pipeline scorer đáng tin | CSA/pipeline metric unavailable, không dựng số liệu |
| Không checkpoint nào cải thiện đủ evidence | Giữ E0; vẫn có report/CSV đầy đủ trạng thái E0–E4 |
