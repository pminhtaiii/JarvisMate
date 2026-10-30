# Optional critical-slot annotations

CSA không mặc định có trong dataset. Không có cả annotation và reviewed extractor
thì metric `unavailable`; training và WER/CER vẫn dùng được. Cần freeze các file này
khi tạo suite, không sửa theo prediction của từng checkpoint.

`annotations.jsonl`: mỗi primary Validation utterance có đúng một object:

```json
{"utterance_id":"train_x/current","annotation_status":"reviewed","reviewer":"reviewer-id","reference_sha256":"SHA256-cua-reference-UTF8-nguyen-goc","slots":[{"type":"proper_name","span":[0,3],"surface":"Nam","canonical":"nam","alternatives":[]}]}
```

Đây là **schema minh họa**, không phải annotation dữ liệu thật. `span` tính theo
Unicode code points của Python, không bytes hay UTF-16 indices. `surface` phải
khớp chính xác đoạn reference. Các type: `money`, `time`, `address`, `proper_name`,
`english_span`. `canonical`/alternatives là string đã chuẩn hóa có ý nghĩa. Không
resolve thời gian từ context hoặc đoán tool arguments. Mỗi dòng phải được review;
câu không có slot ghi `slots: []`, không bỏ dòng khỏi 309 selection.

Extractor `rules.json` là declarative regex + canonical maps, được xây/review từ
Train và xác minh trên examples độc lập trước khi freeze. Ví dụ cấu trúc:

```json
{
  "version": "rules-v1",
  "source_partition": "train",
  "validated": false,
  "reviewer": "reviewer-id",
  "patterns": [
    {"type": "english_span", "pattern": "\\b(?P<value>team|meeting)\\b"},
    {"type": "money", "pattern": "50[.]000 đồng", "canonical_map": {"50.000 đồng": "50000 vnd"}}
  ]
}
```

Chỉ đổi `validated` thành true khi extractor đã được kiểm tra thật và ghi evidence
review; không suy metric chuẩn từ việc một regex chạy được. Pattern mẫu không đủ
phủ mọi số tiền/thời gian/tên riêng. Không nhét gold values Validation thành search
bank của extractor. Prediction extractor nhận text dự đoán và fixed rules, không
nhận reference hoặc annotation spans. Canonicalization ở đây tách riêng WER normalization.

Matching one-to-one; CSA = TP/(TP+FN), đi kèm FP, precision/F1, per-type support,
annotation coverage và critical utterance exact. `unscorable: true` cần ghi lý do
ambiguity, báo support riêng. Proxy rules chỉ có `CSA_proxy`, không primary CSA.
Không dùng Public/Private Test hoặc external labeling service để tạo nhãn tuning.
