# Specs: Fine-tuning PhoWhisper-large cho LifeMate

**Ngày:** 29/10/2026. **Trạng thái:** specs đã viết; training scripts, dependency lock,
VRAM probe và experiments E0–E4 **chưa được triển khai/chạy** trong hạng mục này.
Các tên script/config dưới đây là hợp đồng cho bước implementation, chưa phải lệnh chạy ngay.

Mục tiêu là cải thiện nhận dạng tiếng Việt, nhất là số tiền, thời gian, địa chỉ,
tên riêng và tiếng Anh xen tiếng Việt, trên cùng Validation đã benchmark.

## Giới hạn parameters: phân biệt rules với code

Theo [rules đang dùng](../../context/benchmark.md), **toàn hệ thống <6B**, **LLM <5B**,
context LLM <=16.384 token. Không có quy định riêng ASR phải <1B trong tài liệu này.
PhoWhisper-large khoảng 1,55B + Qwen3-4B khoảng 4B = **khoảng 5,55B danh nghĩa**,
có thể đáp ứng giới hạn nếu không có thành phần bổ sung làm vượt ngưỡng.

ASR <1B là guard nội bộ còn trong `asr/pretrained/`, không phải rule BTC.
Sau khi đồng bộ `main` tại `2006a02`, runtime `LocalASR` đã nới guard và CLI vẫn
kiểm tra tổng ASR + planner. Implementation fine-tuning cần xử lý đường benchmark/
preparation còn lại và giữ kiểm tra số tham số thực tế của LLM/toàn hệ thống.
Adapter LoRA chưa merge và model bổ sung phải được tính;
quantization không giảm số tham số. Đủ parameters không chứng minh đủ VRAM hoặc
đạt giới hạn 30 giây/mẫu trên A30.

## Tài liệu

| File | Nội dung |
|---|---|
| [spec.md](spec.md) | Phạm vi, split cố định, yêu cầu và acceptance scenarios |
| [experiments.md](experiments.md) | E0–E4, hyperparameters đề xuất, thứ tự và gate VRAM |
| [evaluation.md](evaluation.md) | WER/CER, Critical Slot Accuracy, timing, chọn checkpoint |
| [plan.md](plan.md) | Module, CLI/script dự kiến, artifacts, offline export và tích hợp |
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

## Đầu ra cần có sau implementation

- Script độc lập cho E0, E1, E2, E3, E4; common engine và config version hóa.
- CSV so sánh đủ 5 experiment, predicted transcripts, lịch sử đánh giá và peak VRAM.
- Best adapter/checkpoint, bản export offline, source/model/environment hashes.
- README chạy thực tế, cài dependency đã kiểm chứng, khôi phục và tái lập kết quả.

Artifacts thực tế chỉ lưu dưới `.agent-work/asr-finetune/` ignored; không commit
audio, transcript corpus, annotation, weights, checkpoint hay cache. Các bảng số
liệu chỉ được tạo từ run thật; specs này không tạo checkpoint hoặc điểm giả.
