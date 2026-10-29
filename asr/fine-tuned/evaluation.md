# Evaluation và lựa chọn checkpoint

**Version:** `lifemate-asr-ft-eval-v1`. Freeze policy, slot annotations và rule
versions trước E1; không sửa evaluator theo lỗi của từng model để nâng score.

## Corpus và representation so sánh

- Primary: cùng 309 current utterances, thứ tự/IDs/reference/audio hashes của
  manifest benchmark. `with-history` 953 lượt là bảng diagnostic riêng.
- E0 primary dùng base half-precision. E1/E2/E4 primary dùng best adapter export
  merged vào cùng base half-precision; không thêm postprocessing riêng mỗi model.
- E3 primary cũng cần bản export từ **fresh non-quantized base + adapter E3**,
  chuyển sang cùng inference dtype rồi merge/reload. Đây là representation khác
  native NF4; phải đo cả hai, không lấy score native thay score primary.
- Nếu E3 chỉ chạy được native NF4, lưu kết quả vào bảng variants, primary fields
  để `null` với `export_unavailable`; không xếp hạng chung như cùng FP16 backend.
- Mặc định primary backend Transformers eager, FP16, batch 1. Nếu probe buộc phải
  dùng BF16, đổi inference profile cho **tất cả** và chạy lại E0. Không so latency
  CPU benchmark cũ với GPU mới như cải thiện do training.

## WER/CER và coverage

Tái sử dụng [metrics.py](../pretrained/metrics.py): raw và normalized corpus
`sum(S+D+I)/sum(reference_units)`. WER tách whitespace, CER theo Unicode code point
và **có khoảng trắng**. Normalization `vi-nfc-lower-punctuation-space-v1`: NFC,
lowercase, Unicode punctuation thành space, collapse whitespace; giữ dấu và digits,
không chuyển số thành chữ. Denominator 0 thì `null`, vẫn lưu error counts.

Không bỏ failure/timeout/not_run khỏi corpus; chấm chúng với prediction rỗng
và giữ full selected denominator. Coverage và số failed/timeout/not_run luôn đi
kèm metrics. Inference không nhận reference/context/slot annotations.

## Critical Slot Accuracy (CSA)

Đây là metric nội bộ, cần định nghĩa cố định; không mặc định có ground truth slot
trong LifeMate. Gold tool arguments không được dùng để suy ra lời nói đã phát âm.

### Annotation

Tạo local `critical-slots-v1.jsonl` cho toàn bộ 309 lượt primary Validation;
người review đối chiếu transcript và nghe audio khi mơ hồ. Ghi reviewer/version,
reference hash, `annotation_status=reviewed`, `utterance_id`, danh sách slot gồm
`type`, character span `[start,end)`, surface text, canonical value, allowed variants
và ghi chú ambiguity. `slots=[]` chỉ hợp lệ nếu đã review và không có slot.
Một phần độc lập được review chéo; giải quyết bất đồng trước khi freeze.

| Loại | Cần giữ đúng | Canonicalization cho phép |
|---|---|---|
| `money` | Số tiền, đơn vị khi lời nói có xác định | Ví dụ “năm mươi nghìn đồng” và “50.000 đồng” cùng amount/currency |
| `time` | Giờ/ngày/duration và quan hệ trước/sau/tương đối | “bảy giờ tối” = 19:00; “trước một tiếng” giữ offset -3600s và quan hệ |
| `address` | Số nhà, ngõ/đường/phường và tên có trong audio | NFC/case/space, bảng viết tắt đã freeze; giữ dấu phân cách có nghĩa như 5/4 |
| `proper_name` | Người/tổ chức/địa danh được nói | NFC/case/space và alternatives được review; không bỏ dấu bừa |
| `english_span` | Cụm tiếng Anh xen Việt cần nhận đúng | NFC/case/space; chỉ chấp nhận biến thể phát âm/viết khi annotation cho phép |

Không resolve “mai” bằng `context.current_time`, không tự thêm tháng/năm, tên
người/địa chỉ/đơn vị tiền không được nói. Ambiguous slots có tập alternatives
được review trước, hoặc ghi `unscorable` và báo support bị loại; không tự làm
reference dễ hơn sau khi xem prediction. Tránh đếm lặp một tên bên trong cùng
address như hai loại slot nếu không phải hai mention độc lập.

Annotations Validation chỉ cho evaluator/model selection, không làm training rows,
lexicon, prompt, retrieval hoặc augmentation rules. Reference/annotation không vào
extractor nhận prediction. Train annotation nếu cần phải là tập riêng thuộc Train.

### Công thức và giới hạn

Extractor deterministic, offline, version hóa, chỉ nhận **prediction text + rules
đã freeze**, không nhận gold slot values/spans. Đối chiếu maximum one-to-one matching
cùng type và canonical value/allowed variant. Duplicates không được match nhiều lần.

- `TP`: gold slot được nhận đúng; `FN`: gold slot thiếu/sai; `FP`: predicted slot
  dư/sai. Một slot sai có thể tạo cả FP và FN.
- **CSA micro = TP / (TP + FN)**, báo theo từng loại và tổng. Đây là độ đúng trên
  gold slots, **không tự phạt hallucination**, nên bắt buộc đi kèm slot precision,
  recall, F1 và số FP/FN.
- `critical_utterance_exact`: tỷ lệ utterance có gold slots mà tất cả slot đúng
  và không có slot dư. Slot hallucinations ở reviewed utterances không có gold
  vẫn tính FP; không dùng câu không có slot để làm đẹp CSA denominator.
- `annotation_coverage = reviewed / 309`; báo support gold/scorable theo từng loại,
  số ambiguous/unscorable và coverage extractor. Denominator rỗng thì `null`.

Extractor cần test số dạng chữ/digits, currency, thời gian tương đối, địa chỉ,
proper names và code-switch; audit thủ công một subset output độc lập. Nếu chưa
đủ annotation/extractor validation, chỉ ghi `CSA_proxy`/`unavailable`, không dùng
proxy để tuyên bố model cải thiện critical slots. Trạng thái này không chặn training,
nhưng chặn kết luận chính thức về slot accuracy và promotion dựa vào slots.

## Latency và peak VRAM

- Vietnamese transcription, greedy beam 1, temperature 0, seed 42, tối đa 440
  new tokens, VAD/timestamps/previous-text conditioning/prompt/hotwords tắt.
  Lưu suppression defaults và generation config của cùng checkpoint nguồn.
- Một model/process, 1 warm-up đầu corpus, rồi sequential batch 1. CUDA synchronize
  trước/sau `perf_counter`; gồm đọc WAV, preprocessing, transfer, generation, text
  decode; không gồm load/warm-up, metrics, IPC hay ghi artifact. Không preload mel
  cho một model mà bắt model khác tính mel trong cửa sổ đo.
- Ghi load/warm-up riêng. Mean/P95 nearest-rank và total RTF trên các lượt đã đo,
  gồm lỗi/timeout, không thêm duration của not_run vào denominator RTF. Timeout
  parent có IPC phải được gắn protocol như benchmark cũ; không trộn số đo khác nhau.
- Reset PyTorch peak counters trước từng phase và synchronize. Ghi
  `max_memory_allocated` **và** `max_memory_reserved` ở load, training (gồm optimizer
  state/update), eval/generation và export; bao gồm resident weights, không chỉ delta.
  Báo bytes và GiB. Training peak E0 là `null`; inference peak là bắt buộc.
- Ghi thêm device/process peak bằng NVML/nvidia-smi nếu có; nói rõ sampling có thể
  bỏ sót spike. VRAM của framework khác hoặc context CUDA không mặc định nằm hết
  trong PyTorch allocated. Quá headroom thì resource gate fail dù chưa OOM.

## Chọn best checkpoint và candidate

Mỗi epoch tối đa một primary full evaluation. Freeze luật trước E1:

1. Coverage 100%, hashes/protocol/resource pass. Trên các checkpoint có CSA thật,
   ưu tiên CSA cao hơn, rồi normalized WER thấp hơn, CER thấp hơn, latency thấp hơn;
   tie còn lại chọn optimizer step sớm hơn. Patience 3 tính theo tuple này.
2. CSA chưa sẵn sàng thì dùng WER → CER → step để lưu `provisional_best`; ghi
   `slot_metric_unavailable`, không gọi đây là checkpoint đã chứng minh đúng nghĩa.
3. ASR candidate chỉ được đề xuất thay E0 khi WER/CER normalized không tệ hơn,
   CSA tổng không tệ hơn và không có regression quan sát được ở từng loại slot;
   ít nhất WER hoặc CSA cải thiện nghiêm ngặt. So bằng counts chưa làm tròn.
4. Báo paired bootstrap 95% CI theo **source group**, seed 42, 1.000 resamples,
   cho chênh lệch WER và CSA; aggregate counts trong mỗi resample. CI chứa 0 thì
   kết luận “có triển vọng, chưa chắc chắn”, không tuyên bố cải thiện ổn định.
   Loại slot ít support phải nêu giới hạn, không tự suy “ba miền đều tốt”.
5. Chọn đối chứng E4 từ các E1/E2 khả thi bằng cùng tuple; freeze trước khi train E4.
   Đánh giá tác động augmentation so đối chứng này và cả E0, không chỉ so epoch cuối.

Giữ best và latest checkpoint để resume; lưu selection metric/policy/hash và lịch
sử mọi epoch/trial. Confirmation bằng seed training 43/44 là bước bổ sung cho
finalists nếu có tài nguyên; không dùng một seed duy nhất để khẳng định repeatability.
Validation đã dùng nhiều lần để chọn model phải được mô tả là development validation.

## Agent-level diagnostics, có điều kiện

Khi runtime/evaluator đáng tin đã sẵn sàng: chạy E0 và candidate trên cùng source
samples Validation với cùng Qwen snapshot/prompt, limits và deterministic settings.
ASR tất cả current/history-user của từng sample, không replay history actions;
mỗi run/sample chỉ có một ToolEnv, mọi state access qua tool API.

Tool-call F1 theo matcher/rules của BTC; Final State Match chỉ dùng authoritative
reference hash/evaluator. Không xây gold hash từ `label.final_state`, không đọc
environment files. Lưu coverage, empty-gold cases, failures, call logs và total
per-sample latency. Nếu scorer hoặc reference thiếu thì metrics `unavailable`.
ASR tốt hơn không mặc định chứng minh planner/tool score tốt hơn hoặc đạt 30s.
