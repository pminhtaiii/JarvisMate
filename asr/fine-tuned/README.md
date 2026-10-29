# Fine-tuning PhoWhisper-large cho LifeMate

**Ngày:** 29/10/2026. **Trạng thái:** đã có scripts, configs, shared engine và tests.
Chưa chạy PhoWhisper-large/GPU, chưa đo VRAM 12 GiB, chưa full training E0–E4.
Đọc [RUNBOOK.md](RUNBOOK.md) để cài và chạy thật, [review.md](review.md) cho review/evidence.
Mỗi lệnh chỉ vận hành **một experiment**, kết thúc rồi dừng; không có chế độ chạy all E0–E4.

Mục tiêu là cải thiện nhận dạng tiếng Việt, nhất là số tiền, thời gian, địa chỉ,
tên riêng và tiếng Anh xen tiếng Việt, trên cùng Validation đã benchmark.

## Giới hạn parameters: phân biệt rules với code

Theo [rules đang dùng](../../context/benchmark.md), **toàn hệ thống <6B**, **LLM <5B**,
context LLM <=16.384 token. Không có quy định riêng ASR phải <1B trong tài liệu này.
PhoWhisper-large khoảng 1,55B + Qwen3-4B khoảng 4B = **khoảng 5,55B danh nghĩa**,
có thể đáp ứng giới hạn nếu không có thành phần bổ sung làm vượt ngưỡng.

Guard cũ ASR <1B đã được thay bằng kiểm tra logical parameters theo budget LifeMate
trong benchmark/preparation; `phowhisper-large` đã được đăng ký. Runtime `LocalASR`
vẫn hỗ trợ large/offload và CLI vẫn kiểm tra tổng ASR + planner.
Adapter LoRA chưa merge và model bổ sung phải được tính;
quantization không giảm số tham số. Đủ parameters không chứng minh đủ VRAM hoặc
đạt giới hạn 30 giây/mẫu trên A30.

## Tài liệu

| File | Nội dung |
|---|---|
| [RUNBOOK.md](RUNBOOK.md) | Commands thực tế cho Prepare, E0–E4 độc lập, resume, status, skip, export và compare |
| [review.md](review.md) | Những thiếu hụt đã xử lý, test evidence và hardware acceptance còn thiếu |
| [SLOT_FORMAT.md](SLOT_FORMAT.md) | Schema optional cho annotation và extractor, không dựng slot accuracy |
| [spec.md](spec.md) | Phạm vi, split cố định, yêu cầu và acceptance scenarios |
| [experiments.md](experiments.md) | E0–E4, hyperparameters đề xuất, thứ tự và gate VRAM |
| [evaluation.md](evaluation.md) | WER/CER, Critical Slot Accuracy, timing, chọn checkpoint |
| [plan.md](plan.md) | Thiết kế module/artifacts/offline; RUNBOOK là CLI vận hành hiện tại |
| [tasks.md](tasks.md) | Công việc triển khai tuần tự, điều kiện nghiệm thu |
| [research.md](research.md) | Nguồn chính thức, điều đã biết và tương thích chưa kiểm chứng |

## Trình tự thực hiện

1. Audit manifest/audio và chuẩn bị môi trường trên GPU được báo là RTX 5070 Ti,
   VRAM 12 GB; đo GPU/VRAM thật, không suy từ tên card.
2. Chuẩn bị snapshot PhoWhisper-large local với immutable revision; chạy E0 đầy đủ.
3. Với mỗi experiment tiếp theo: kiểm tra config, probe forward/backward/optimizer,
   generation và VRAM; chỉ train khi probe cùng config đã pass.
4. Ghi kết quả hoặc lý do không chạy cho **mọi E0–E4**; không mặc định E2/E3 khả thi.
5. Export/reload offline và kiểm tra với Qwen trước khi tuyên bố dùng được cho submission.

**Dữ liệu đã kiểm tra khi viết specs:** manifest seed 42 có 1.545 source sample,
Train 1.236 / Validation 309. Dùng user-history thuộc Train cho tối đa 4.083 lượt
fit trước audit/dedup; đánh giá chính trên 309 lượt hiện tại, scope history riêng.
Identity và policy đầy đủ ở [spec.md](spec.md#split-và-dữ-liệu).

Benchmark CPU trước đó có PhoWhisper-small/medium, **chưa có PhoWhisper-large**;
không lấy điểm của medium làm E0. Validation đã được xem để phân tích lỗi nên
đây là development validation, không phải một test set chưa từng được quan sát.

## Đầu ra của implementation

- Script độc lập cho E0, E1, E2, E3, E4; common engine và config version hóa.
- CSV so sánh đủ 5 experiment, predicted transcripts, lịch sử đánh giá và peak VRAM.
- Best adapter/checkpoint, bản export offline, source/model/environment hashes.
- README/Runbook cài dependency đã khóa, khôi phục và tái lập; GPU compatibility vẫn cần probe.

Artifacts thực tế chỉ lưu dưới `.agent-work/asr-finetune/` ignored; không commit
audio, transcript corpus, annotation, weights, checkpoint hay cache. Các bảng số
liệu chỉ được tạo từ run thật; hiện chưa có điểm/checkpoint PhoWhisper-large của suite này.
