# E0–E4 và các gate thực thi

**Status:** cấu hình khởi đầu đề xuất, chưa đo VRAM/accuracy. Script contracts ở
[plan.md](plan.md), điều kiện chọn checkpoint ở [evaluation.md](evaluation.md).

## Cấu hình chung cần freeze trước E1

| Hạng mục | Giá trị ban đầu |
|---|---|
| Base | Cùng local snapshot `vinai/PhoWhisper-large`, immutable SHA và hashes |
| Fit / primary Validation | Fit manifest theo spec / 309 current utterances cố định |
| Training seed / data seed | 42 / 42; augmentation có seed con ổn định theo epoch + utterance ID |
| Precision training | BF16 nếu kernel probe pass; nếu không dùng FP16 + GradScaler |
| Micro-batch / accumulation | 1 / 16; single GPU, effective batch tối đa 16 utterances/update |
| Eval/generation batch | 1 |
| Optimizer | AdamW Torch, chỉ adapter; LR `1e-4`, betas `(0.9,0.999)`, eps `1e-8`, weight decay `0.01` |
| Schedule / clipping | Linear decay, warm-up 5% optimizer updates; max grad norm 1.0 |
| Training cap | Tối đa 10 epochs; evaluate/save mỗi epoch; early stopping patience 3 theo policy selection |
| LoRA | Rank 8, alpha 16, dropout 0.05, bias `none`, không `modules_to_save` mặc định |
| Freeze | Tất cả base parameters, embedding, output projection, layer norms; chỉ LoRA A/B trainable |
| Gradient checkpointing | Bật, ưu tiên non-reentrant nếu stack hỗ trợ; training `use_cache=False` |
| Attention | Eager cho reference profile; SDPA là profile riêng nếu được probe/rebaseline |
| Labels | Transcript gốc NFC/trim, giữ dấu/số/English; không dùng WER normalization làm target |
| Decoder prefix | Vietnamese transcription, không timestamps; BOS/decoder-start không bị nhân đôi |
| Padding | Audio theo Whisper processor; label padding `-100`, attention mask đúng với audio |
| Logging/checkpoints | Loss, LR, finite/nonzero gradients, optimizer steps, throughput, RNG, memory; giữ best + latest |

Thay dtype/rank/batch/attention/fit scope sau probe là **config ID mới**, cần probe
lại; freeze cùng giá trị cho các đối chứng có thể so sánh. Ghi actual update count,
last partial accumulation window và số label tokens, không mặc định accumulation
giảm activation của một micro-batch. Không thay LR/rank liên tục dựa trên Validation.
Nếu tuning thêm, đăng ký trước danh sách nhỏ và log mọi trial kể cả thất bại.

## Gate tài nguyên cho từng profile

1. Ghi OS, GPU name, compute capability, driver, CUDA runtime, Torch wheel và
   total/free VRAM thực tế; test CUDA matmul + model forward. CPU-only wheel của
   laptop Raccoon không dùng để xác nhận GPU 5070 Ti.
2. Đặt cap `min(total_VRAM, 12 GiB)`. Chừa headroom `max(1 GiB, 10% cap)`; không
   chiếm GPU đang có workload khác. Budget process là
   `min(cap, free_at_start + process_reserved_at_start) - headroom`; so với peak
   reserved, đồng thời ghi global device memory khi đo được.
3. Model load rồi training probe trên Train: ít nhất 10 optimizer updates với
   accumulation thật, có batch dài nhất theo duration, batch dài nhất theo label,
   và batch điển hình. Audio Whisper thường pad tới cửa sổ 30s; audio ngắn không
   bảo đảm tiết kiệm encoder activations. Không chỉ probe audio 1–2 giây.
4. Sau bước optimizer đầu tiên mới đủ evidence về allocation optimizer states.
   Đo load, train forward/backward/update, generation eval và save/reload riêng;
   test finite loss, gradients, adapter update khác 0, base weights không thay đổi.
5. Reset peak counters đúng phase, synchronize CUDA; lưu max allocated/reserved,
   free-at-start/end và device peak lấy mẫu. Gate pass nếu mọi phase nằm trong
   budget, không OOM, không NaN/Inf và không zero-update training.

OOM: dừng worker, lưu phase/config/shape/VRAM, giải phóng process rồi quyết định
profile tiếp theo. Không tự retry bằng batch/sequence nhỏ hơn, không crop speech
hoặc bật CPU offload để tuyên bố cùng profile vừa 12 GB. Có thể đăng ký profile
rank thấp hơn hoặc offload riêng; phải ghi thay đổi và đối chứng tương ứng.

Preflight record gắn `config_hash`, fit/split/model/environment/code hashes và
GPU. Config/GPU/software thay đổi làm record cũ hết hiệu lực. Probe thành công
chỉ cho phép bắt đầu full training; full run vẫn phải ghi peak/exception thực tế.

## E0 — Pretrained Baseline

- Không optimizer, không adapter, không cập nhật bất kỳ weights nào.
- Đánh giá large gốc đầy đủ theo protocol; smoke subset chỉ là integration check.
- Xuất transcripts, slot scores nếu có gold, latency/RTF, inference peak VRAM,
  measured parameter count; training peak là `null`, không ghi 0 GiB.
- Gate: model/processor load offline được, full primary coverage, budget inference
  pass. E0 lỗi thì sửa nguyên nhân/rebaseline trước khi train; không lấy điểm
  PhoWhisper-medium hoặc điểm CPU cũ thay E0 trên GPU mới.

## E1 — Decoder-only LoRA

- Resolve đầy đủ tên module trước PEFT wrapping; chỉ chọn
  `model.decoder.layers.<n>.{self_attn,encoder_attn}.{q_proj,v_proj}`.
- Không dùng bare `q_proj`/`v_proj` toàn model vì sẽ gắn vào cả encoder.
- Encoder frozen; có thể tính encoder features trong no-grad ở profile E1 nếu
  kiểm tra gradient decoder pass. Không tái dùng tối ưu này cho E2.
- Probe gate rồi train, chọn best checkpoint, export và full evaluation.
- E1 OOM/không tương thích phải lưu evidence; E2 được ghi `skipped_dependency`
  nếu chưa thể thiết lập đối chứng E1, rồi xem điều kiện E3.

## E2 — Encoder + Decoder LoRA

- Bổ sung `model.encoder.layers.<n>.self_attn.{q_proj,v_proj}` vào đúng target E1.
- Giữ base frozen; không bọc encoder forward bằng no-grad. Assert có gradient
  và weight update trên adapter ở **cả hai phía**.
- Chỉ thay target scope so với E1; cùng rank/LR/fit order/effective batch/dtype,
  không augmentation. Ghi số trainable/total parameters riêng.
- Chỉ train khi E1 đã có kết quả và probe E2 pass headroom. OOM thì ghi
  `failed_oom`; giữ E1 làm candidate, không ép chạy bằng profile khác mà giấu thay đổi.

## E3 — QLoRA 4-bit, có điều kiện

E3 được xét sau khi E2 đã có trạng thái. Chạy khi E1/E2 thiếu VRAM hoặc có mục
tiêu so sánh bộ nhớ được ghi trước. Nếu không cần, ghi `skipped_not_needed`.

- Chọn target scope E2 nếu E2 đã train thành công; nếu không dùng scope E1 và
  ghi rõ E3 so với E1. Nếu cả LoRA thường đều OOM, scope E1 vẫn là fallback probe,
  nhưng không có đối chứng training thành công để tuyên bố mức tiết kiệm so E1.
- Base 4-bit NF4, double quantization; compute BF16/FP16 đã probe. Ghi dtype thật
  của quantized linears, convolutions, layer norms, embedding và adapter.
- Dùng API k-bit preparation của phiên bản PEFT đã khóa; kiểm tra wrapper nhận
  `input_features`/`labels` và generation Whisper. Không chọn task wrapper cho LLM
  hoặc đẩy `input_ids` thay audio. Không gọi `.half()`/`.to()` bừa trên model đã quantize.
- Gate bổ sung: xác nhận Linear4bit thực sự có trong target architecture,
  base frozen, adapter có gradient/update, loss finite, optimizer step, greedy
  generation, save adapter và fresh-process reload đều pass.
- Native 4-bit inference và export half-precision có thể khác output. Đánh giá
  riêng hai representation theo [evaluation.md](evaluation.md); không gộp dtype.
- Không tương thích kernel, wrapper, backward hoặc reload: `unsupported` và lý do.
  Không âm thầm chuyển thành int8 rồi ghi là QLoRA 4-bit.

## E4 — LoRA + Data Augmentation

- Chọn LoRA đối chứng khả thi từ E1/E2 theo cùng checkpoint-selection policy;
  freeze `control_experiment_id`, config và training budget trước E4. Không chọn
  E3 thay thế E1/E2 một cách ngầm định; không có LoRA thường khả thi thì E4 skipped.
- Khởi tạo **lại** từ pretrained large, cùng adapter initialization seed và toàn
  bộ hyperparameters của đối chứng. Khác biệt duy nhất là augmentation Train.
- Freeze optimizer-update budget theo run đối chứng, không cho E4 train thêm
  steps/epochs. Nếu early stopping tạo số updates khác, báo thêm checkpoint ở
  last common scheduled evaluation step của hai run trước khi quy khác biệt cho
  augmentation; giữ cả best-checkpoint comparison và matched-budget comparison.
- Online augmentation theo seed từ SHA256 của `(root_seed, epoch, utterance_id,
  transform_name)`; không dùng Python `hash()` hay timestamp/run ID. Không sinh thêm
  hàng làm tăng số optimizer steps. 50% lượt giữ clean; nhánh còn lại thử từng
  phép dưới đây với xác suất 0.5 độc lập, thứ tự speed → volume → noise.

| Phép | Cấu hình ban đầu | Điều kiện |
|---|---|---|
| Speed | Chọn đều factor 0.9 / 1.0 / 1.1, giữ sampling rate 16 kHz | Speech/transcript không đổi; nếu >30s thì fallback speed 1.0, log lý do |
| Volume | Gain chọn đều từ -6 đến +6 dB | Giới hạn peak để không clipping; ghi gain thực tế |
| Background noise | SNR chọn đều 15–30 dB | Chỉ nguồn non-speech local được kiểm tra license; log noise hash, offset, SNR |

Không có noise hợp lệ thì profile thiếu noise phải được đặt tên/ghi rõ và không
được coi là E4 kết hợp đầy đủ. Không dùng audio Validation/Test làm background.
Từ chối biến đổi gây clipping, mất lời, audio rỗng hoặc NaN; log fallback clean,
không bỏ row. Thực hiện kiểm tra nghe một tập nhỏ **Train** trước full E4.

## Thứ tự và điểm dừng

| Sau bước | Được làm tiếp khi |
|---|---|
| Data/environment | Hashes/alignment pass; môi trường GPU đã khóa |
| E0 | Có kết quả full coverage làm baseline |
| E1 | Kết quả hoặc failure record; chỉ E2 full training nếu E1 thành công |
| E2 | Kết quả hoặc skipped/OOM record; xem eligibility E3 |
| E3 | Completed, unsupported hoặc skipped có lý do |
| E4 | Có đối chứng E1/E2, probe augmentation/profile pass |
| Finalize | CSV đủ E0–E4, chọn/giữ baseline theo evidence, export/reload được |

Không cần chờ người dùng xác nhận ở mỗi gate: gate là kiểm tra bằng evidence,
không phải permission prompt. Chưa có evidence thì record trạng thái chưa đạt;
không đánh dấu một experiment hoàn tất chỉ vì đã có script.
