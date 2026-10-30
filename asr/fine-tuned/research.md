# Nguồn và quyết định kỹ thuật

**Đối chiếu:** 29/10/2026. Nguồn upstream là cơ sở thiết kế, không phải evidence
training thành công trên GPU của người dùng. Khóa version/revision và probe thật
trước khi dùng; không mặc định tài liệu `main` khớp package đã cài.

| Nguồn chính thức | Căn cứ dùng trong specs | Điều chưa được chứng minh |
|---|---|---|
| [VinAI PhoWhisper](https://github.com/VinAIResearch/PhoWhisper), [large model card](https://huggingface.co/vinai/PhoWhisper-large) | Model ID, large khoảng 1,55B; fine-tuned từ Whisper trên 844 giờ giọng Việt đa dạng; BSD-3-Clause metadata | Large tốt hơn medium trên LifeMate, chạy vừa 12 GB, hoặc phù hợp mọi final organizer rules |
| [PEFT Whisper int8 ASR guide](https://huggingface.co/docs/peft/main/en/task_guides/int8-asr) | Có đường LoRA + quantized Whisper; attention q/v là target tham khảo | Tutorial int8 không xác nhận PhoWhisper-large **NF4 4-bit**, wrapper/API hiện cài hoặc RTX 5070 Ti |
| [PEFT quantization](https://huggingface.co/docs/peft/en/developer_guides/quantization) | K-bit preparation rồi train adapter; kiểm tra trainable/frozen scope | Không thay thế test forward/backward/generate/save/reload thật |
| [Transformers bitsandbytes](https://huggingface.co/docs/transformers/quantization/bitsandbytes) | NF4, double quantization, compute dtype là các thành phần profile E3 | Hỗ trợ CUDA/platform chung không đảm bảo đúng binary/kernel/Whisper integration |
| [PyTorch Blackwell support](https://pytorch.org/blog/pytorch-2-7/) | Có dòng Torch hỗ trợ Blackwell và CUDA 12.8 wheels; cần chọn GPU build phù hợp | Không mặc định mọi OS/wheel/bitsandbytes version đều chạy được; không cần hạ xuống Torch 2.7 chỉ vì bài viết này |
| [Transformers Whisper 4.57.1](https://huggingface.co/docs/transformers/v4.57.1/en/model_doc/whisper) | Audio `input_features`, generation language/task, model/processor boundaries | PEFT task wrapper cho text không tự động đúng cho Whisper audio |

## Căn cứ trong repository

- [Benchmark rules](../../context/benchmark.md): toàn models <6B; LLM <5B;
  context <=16.384; offline, A30, 30 giây/mẫu. **Không có ASR <1B riêng.**
- [Pretrained loader](../pretrained/models.py), [preparation](../pretrained/prepare.py):
  guard nội bộ 1B đã được thay bằng budget check và registry đã có large.
- [ASR runtime loader](../../python/src/lifemate/adapters/asr.py) sau khi đồng bộ
  `main` tại `2006a02` đã nới guard model lên 6B và có CPU offload; không cần bỏ
  lại cap 1B ở runtime, vẫn phải kiểm tra tổng ASR + planner và adapter thật.
- [Runtime CLI](../../python/src/lifemate/cli.py): đang kiểm tra tổng số parameters;
  giữ invariant này thay vì coi việc nới cap ASR là bỏ budget hệ thống.
- [Metrics](../pretrained/metrics.py): giữ normalization/corpus counts để so lịch sử.
- [Split loader](../pretrained/data.py): giữ source/group membership, mở rộng Train
  rows ở exporter mới mà không đổi split seed/identity.

## Quyết định của specs, chưa phải kết quả thực nghiệm

1. Giữ source-sample split 42; fit current+history của Train, primary eval current.
2. Bắt đầu rank 8/micro-batch 1/accumulation 16, lựa chọn VRAM phải được đo.
3. Tách nguồn target modules E1/E2 bằng full names, kiểm tra gradient và frozen base.
4. E3 có thể unsupported; native NF4 và merged half là hai representation phải đo riêng.
5. CSA cần gold annotation/extractor đã review; không lấy gold tool calls hoặc proxy
   regex làm accuracy chuẩn. WER/CER đơn thuần không chứng minh giữ ý nghĩa.
6. Có thể giữ E0 nếu fine-tuning không cải thiện; không chọn checkpoint vì training loss thấp.

Chưa tải snapshot PhoWhisper-large hoặc chạy CUDA/bitsandbytes tại đây. Đã kiểm tra
LoRA/PEFT bằng Whisper ngẫu nhiên tiny trên CPU; chưa chạy large resource probes,
training/export/inference của suite này. Các số liệu
benchmark CPU đã có thuộc hạng mục pretrained trước đó, không phải E0 của suite này.
