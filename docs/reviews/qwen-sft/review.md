# Review kiến trúc fine-tuning Qwen cho JarvisMate / LifeMate 2026

**Ngày:** 2026-11-01. **Source review:** `f9226c4`.
**Checkpoint:** `Qwen/Qwen3-4B-Instruct-2507`, thay thế đề xuất Qwen3.5 theo quyết định của người dùng.
**Phạm vi:** tổng hợp hai lượt phản biện trong chat; chỉ đọc source/data, thống kê và thiết kế.
Chưa implementation/training/inference/probe GPU trong công việc review này.

**Kết luận:** giữ Next-Action SFT và planner/runtime hiện tại; chạy Natural SFT
trước balancing; L3 cần kiểm tra từng next-action row cùng prefix, không loại cả
source một cách máy móc và không giữ target đã mất căn cứ trong input.

## 1. Evidence dữ liệu và cách biểu diễn arguments

Nguồn: official Train `train/train.jsonl`, `train/train_tools_catalog.json`.
SHA-256, counts và split identity ở [data-audit.json](reports/data-audit.json).
Trong workspace lúc review, dataset root tương đối từ repo là
`../train+public_test/train+public_test`; đường dẫn này là ví dụ local, không phải yêu cầu bố trí dữ liệu.
Không đọc bất kỳ file environment nào để tính báo cáo.

### 1.1 Source samples khác next-action rows

Train có **1.545 samples**, **3.541 gold calls**, catalog **46 apps / 147 tools**;
**1.018 samples có history**, với **3.491 historical user turns có audio/audio_text**.

| Nhóm source sample, loại trừ nhau | Số lượng | Tỷ lệ |
|---|---:|---:|
| Có calls, không chứa `sys.ask_missing_info` | 1.217 | 78,77% |
| Chứa `sys.ask_missing_info`, có thể kèm calls khác | 217 | 14,05% |
| Gold calls `[]` | 111 | 7,18% |

Chỉ **60/217** ask samples hỏi ngay từ đầu; **157** có calls khác trước ask;
**153** có read call trước ask. Không thể coi ba nhóm source là ba lớp action độc lập.

Theo terminal policy hiện tại, counts **trước quality/token filtering**:

| Next-action target | Rows | Tỷ lệ |
|---|---:|---:|
| Call thông thường | 3.324 | 68,27% |
| `sys.ask_missing_info` | 217 | 4,46% |
| `finish` sau calls | 1.217 | 25,00% |
| `finish` ngay từ đầu | 111 | 2,28% |
| Tổng | 4.869 | 100% |

Công thức: `3541 + 1545 - 217 = 4869`. Cả 217 ask results đều có
`ok:true, waiting_for_user:true` và kết thúc trajectory; runtime tự dừng nên không
thêm finish sau ask. Gộp hai loại finish sẽ che mất độ hiếm của initial finish.

Gold `[]` không chỉ có nghĩa thiếu app/tool: còn có rút lại yêu cầu, yêu cầu giữ
nguyên, trò chuyện và các trường hợp khác. Ví dụ `train_0036` rút lại thao tác tắt
đèn, `train_0038` yêu cầu đừng tắt đèn, `train_0057` chỉ khen trợ lý. Không có count
đã gán nhãn thủ công theo từng lý do; đừng suy ra các tỷ lệ semantic từ vài ví dụ.

### 1.2 Số tiền, currency, người nhận và thời gian

| Tool | Arguments quan trọng | Amount | Gold calls |
|---|---|---|---:|
| `banking.transfer` | `from_account_id`, `beneficiary_id`, `amount`, optional `note` | integer > 0 | 82 |
| `banking.open_savings` | `from_account_id`, `amount`, `term_months` | integer > 0 | 5 |
| `ewallet.transfer` | `amount`, một trong `contact_id`/`phone`, optional `note` | integer > 0 | 33 |
| `ewallet.topup_mobile` | `phone`, `amount` | integer > 0 | 10 |
| `ewallet.pay_qr` | `merchant_id`, `amount` | integer > 0 | 4 |
| `exchange_rate.convert` | `amount`, `from_currency`, `to_currency` | integer >= 0 | 12 |
| `bill_payment.pay` | `bill_id`, `source` (`bank`/`ewallet`) | Không có argument amount | 104 |

Cả **146** calls có `arguments.amount` trên đều có giá trị số nguyên, không có
string hoặc giá trị số lẻ. `500000` là dạng target; không phải `"500000"` hay
`"500 nghìn"`. Amount ở top level của arguments, không nằm trong nested money object.

Banking/ewallet không có currency argument riêng; context chuẩn cũng không có
`context.currency`. Giao dịch nội địa trong các mẫu kiểm tra dùng số tiền đồng
theo ngữ cảnh. Không được tự thêm currency vào schema. Exchange-rate tools có
currency riêng; không áp dụng mặc định VND cho mọi amount trong catalog.

`bill_payment.pay` lấy số tiền từ bill trong simulator, không nhận amount từ LLM.
Đúng `bill_id` và đúng nhánh `source` vẫn phụ thuộc vào amount quan sát được.

Trong results, outgoing `transaction.amount` âm trong khi input amount dương.
Không đánh dấu đó là inconsistency bằng cách so literal hai số. Simulator source:
[Banking](../../../tools/train/apps/banking.py),
[Ewallet](../../../tools/train/apps/ewallet.py),
[BillPayment](../../../tools/train/apps/bill_payment.py),
[ExchangeRate](../../../tools/train/apps/exchange_rate.py).

### 1.3 Tám samples thật

Gold calls dưới đây đầy đủ cho từng current request. Results/history chỉ trích
field cần thiết; JSON evidence lưu provenance/path cụ thể, không phải full records.
Line là số dòng 1-based trong JSONL có hash ở data audit.

#### A. `train_0030`, line 25: tiền từ lời nói, IDs từ lookup

> Ơi, chuyển giúp tôi một triệu hai cho chủ nhà Phạm Hùng nhé.

```json
[
  {"name":"banking.get_balance","arguments":{}},
  {"name":"banking.list_beneficiaries","arguments":{}},
  {"name":"banking.transfer","arguments":{"from_account_id":"acc_01","beneficiary_id":"ben_01","amount":1200000}}
]
```

Result 1: `accounts` chứa `acc_01`, Tài khoản thanh toán, balance `12500000`.
Result 2: `beneficiaries` chứa `ben_01`, Chủ nhà - Phạm Hùng.
Result 3: `transaction.amount=-1200000`, `balance=11300000`.
"Một triệu hai" được chuẩn hóa thành `1200000`. Account ID dùng được sau call 1,
beneficiary ID sau call 2; không đưa future results vào input bước đầu.

#### B. `train_0015`, line 14: amount không có trong transcript

> Chuyển tiền mạng tháng này cho chú Phạm Hùng nha, nếu tài khoản thanh toán không đủ thì lấy từ tiết kiệm dùm tôi hen.

```json
[
  {"name":"bill_payment.list_bills","arguments":{}},
  {"name":"banking.get_balance","arguments":{}},
  {"name":"banking.list_beneficiaries","arguments":{}},
  {"name":"banking.transfer","arguments":{"from_account_id":"acc_02","beneficiary_id":"ben_02","amount":218000}}
]
```

Result 1: bill `internet` có amount `218000`. Result 2: `acc_01` thanh toán có
`112425`, `acc_02` tiết kiệm có `50000000`. Result 3 xác định `ben_02` là Phạm Hùng.
Result 4: `transaction.amount=-218000`, `balance=49782000`.
`112425 < 218000`, nên chọn tài khoản tiết kiệm. Amount dùng được sau call 1;
nhánh tài khoản cần thêm result 2. Không thấy số trong transcript không có nghĩa thiếu amount.

#### C. `train_0500`, line 469: chuyển ví qua contact ID

> Chuyển cho Hòa một trăm hai mươi nghìn qua ví giúp anh cái.

```json
[
  {"name":"contacts.search","arguments":{"query":"Hòa"}},
  {"name":"ewallet.transfer","arguments":{"contact_id":"c_05","amount":120000}}
]
```

Result 1: contact `c_05`, name Hòa. Result 2: transaction `to=c_05`, `amount=-120000`.
Amount từ request; contact ID từ lookup. Nếu chỉ ASR amount sai, search row có thể
còn hợp lệ nhưng transfer row cần kiểm tra lại.

#### D. `train_0059`, line 48: thanh toán không truyền amount

> Trợ lý ơi, xem giúp tôi tiền điện tháng này bao nhiêu rồi thanh toán bằng ví, nếu thiếu thì trừ luôn qua ngân hàng nhé.

```json
[
  {"name":"bill_payment.list_bills","arguments":{}},
  {"name":"ewallet.get_balance","arguments":{}},
  {"name":"bill_payment.pay","arguments":{"bill_id":"bill_02","source":"bank"}}
]
```

Result 1: bill `bill_02`, type electricity, amount `848000`. Result 2: balance ví
`739892`. Result 3: bill có `paid=true`, `paid_with=bank`.
Amount không ở target pay nhưng quyết định nguồn trả vì `739892 < 848000`.
L3 phải kiểm tra cả điều kiện/selection, không chỉ số trong target.

#### E. `train_0152`, line 132: thiếu amount, làm phần độc lập rồi hỏi

> Đặt báo thức 6 giờ sáng mai cho anh, rồi chuyển ví điện tử cho Lan ít tiền nha.

```json
[
  {"name":"contacts.search","arguments":{"query":"Lan"}},
  {"name":"alarm.create","arguments":{"time":"2026-11-22T06:00:00+07:00"}},
  {"name":"sys.ask_missing_info","arguments":{"tool_name":"ewallet.transfer","params":["amount"]}}
]
```

Context time `2026-11-21T13:10:00+07:00`. Result 1 tìm thấy Lan `c_01`.
Result 2 tạo alarm đúng sáng mai. Result 3: `ok=true, waiting_for_user=true`.
Không đoán "ít tiền" thành một amount. Toàn Train có **21 ask calls chứa `amount` trong params**.
Không thêm finish sau terminal ask.

#### F. `train_1428`, line 1276: amount/account đã có trong history

> Lấy số tiền Greenhaven Foods mới chuyển, gửi tiết kiệm sáu tháng từ tài khoản vựa giùm tôi.

```json
[
  {"name":"banking.open_savings","arguments":{"from_account_id":"acc_205","amount":18500000,"term_months":6}}
]
```

`history[1].tool_results[0]` chứa tài khoản vựa `acc_205`, balance `21300000`.
`history[1].tool_results[1]` chứa Greenhaven Foods amount `18500000` và một giao
dịch khác của Greenhaven Fresh amount `9200000`. Result current: savings amount
`18500000`, term 6, balance `2800000`.
Thông tin dùng được ngay ở decision đầu vì history đã được cung cấp. Không replay.
ASR sai tên công ty có thể đổi amount dù transcript hiện tại không có chữ số.

#### G. `train_1144`, line 1025: nhiều amount và tự sửa currency

> Tính hộ tôi tám mươi nghìn yên, với ba trăm ơ-rô... ấy nhầm, ba trăm đô Mỹ, ra tiền Việt là bao nhiêu.

```json
[
  {"name":"exchange_rate.convert","arguments":{"amount":80000,"from_currency":"JPY","to_currency":"VND"}},
  {"name":"exchange_rate.convert","arguments":{"amount":300,"from_currency":"USD","to_currency":"VND"}}
]
```

Results tương ứng: rate `173`, result `13840000`; rate `25946`, result `7783800`.
USD là currency sau tự sửa, không phải EUR. So cùng tập số hoặc cùng từ currency
không đủ chứng minh semantic equivalence; phải giữ binding và lời đính chính.

#### H. `train_0995`, line 898: merchant từ history, phủ định đổi điểm

> Tớ đang ở quầy Góc Phố 24h nè, quét QR qua ví bốn mươi hai nghìn luôn, không đổi điểm đâu nha.

```json
[
  {"name":"ewallet.pay_qr","arguments":{"merchant_id":"mch_2648","amount":42000}}
]
```

`history[1].tool_results[0].programs` chứa Góc Phố 24h Rewards với
`merchant_id=mch_2648`. Result current có `transaction.amount=-42000`.
Amount từ request, merchant từ history; không gọi redeem vì bị phủ định.
Catalog mô tả merchant từ restaurant lookup, nhưng bằng chứng history ở đây đến
từ loyalty result: không bó nguồn grounding vào duy nhất ví dụ trong description.

F và G thuộc frozen Validation, chỉ dùng review/evaluation, không chuyển sang Fit.

### 1.4 Gold không sạch tuyệt đối

`train_1696`, line 1503: call thứ ba `chat_ott.send_message` dùng `chat_6142` không
xuất hiện trong request/context/history hoặc strict prefix. Result là
`{"ok":true,"done":false,"message":"không tìm thấy chat_id"}`.
Quarantine target thiếu căn cứ và xem lại downstream finish; không tự sửa ID/thêm
lookup rồi gọi đó là gold. Chỉ có một `done:false` trong current gold results được
đếm; điều này không chứng minh những mẫu khác đều đúng ngữ nghĩa.

Audit pair lengths, installed-tool eligibility và terminal consistency không thay
thế full schema validation hoặc replay thực tế. ID-grounding check trong báo cáo
là heuristic kiểm tra xuất hiện literal của `x-ref` string, chưa phải chứng minh
semantic grounding đầy đủ. Không có execution/replay claim.

## 2. Phản biện input/label L3 khi ASR sai số tiền

Gold "500 nghìn", ASR "5 triệu", target `amount=500000`: nếu không có bằng chứng
hợp lệ khác, target mâu thuẫn input. Sinh `5000000` có thể khớp ASR text nhưng vẫn
sai yêu cầu gốc/benchmark. Qwen text-only không thể chắc chắn khôi phục thông tin
âm thanh đã mất; SFT không phải cơ chế đoán giao dịch thật từ văn bản sai.

Không mặc định loại cả source. Một lookup người nhận có thể giữ nếu tên còn đúng;
lookup account cũng cần xét điều kiện amount. Transfer bị ảnh hưởng phải loại/review.
Hành động độc lập như alarm có thể giữ nếu thời gian/điều kiện của nó còn đúng.

**Target giữ nguyên tên tool chưa đủ:** cả arguments, điều kiện, thứ tự quyết định
và prefix phải còn hợp lệ. Một action hợp lệ chưa chắc là *next* action hợp lệ.
Không xóa transfer row rồi giữ finish với gold observation "đã chuyển 500 nghìn"
khi request đang thấy đòi 5 triệu. Không inject result của target để biện hộ amount.

| Lỗi ASR | Phạm vi kiểm tra |
|---|---|
| Amount/currency | Transfer, đủ/thiếu tiền, lựa chọn tài khoản, nhánh phụ thuộc, finish |
| Người nhận/tên gần giống | Lookup query, entity/ID selection, downstream mutations |
| Thời gian | Timestamp theo context, trước/sau, schedule/reminder và điều kiện |
| Phủ định/tự sửa | Có thể đổi toàn bộ ý định và terminal behavior |
| Một nhánh trong nhiều việc | Giữ nhánh độc lập chỉ khi target và prefix được xác nhận còn đúng |

## 3. Structured Prompt P1 và serialization

Giữ kiến trúc prompt hiện tại; chưa cần Request Decomposition/explicit CoT.
P1 hiện là mô tả đề xuất, chưa phải shared training renderer đã được triển khai.
Source đang dùng `PROMPT_VERSION=lifemate-react-v4` trong
[prompting.py](../../../python/src/lifemate/prompting.py).

- [normalize_record/prepare_request](../../../python/src/lifemate/dataset.py):
  whitelist context, chuẩn hóa history; audio mode transcribe cả historical users.
- [planner_input/messages](../../../python/src/lifemate/prompting.py): current
  request/context/history/available_tools, rồi ordered observations.
- [LocalPlanner._action](../../../python/src/lifemate/adapters/planner.py): chat
  template, greedy constrained generation và context/output bounds.

P1 phải giữ `location` ngoài time/timezone/profile, exact installed-tool schemas
cộng sys, chronological history, actual observations. Không replay history.
Runtime serialize observation dưới role user; trainer không tự đổi thành native
tool-call protocol/XML của Qwen khi inference vẫn dùng custom call/finish JSON.

**Rủi ro field order:** [jsonio.dumps](../../../python/src/lifemate/jsonio.py) có
`sort_keys=True`, trong khi [action_parser/ActionConstraint](../../../python/src/lifemate/adapters/constrained.py)
ép `action -> name -> arguments` và `force_json_field_order=True`. Dùng generic
dumps cho completion có thể tạo `action -> arguments -> name`, lệch decoder.
Cần contract riêng cho action completion và check mọi target được grammar chấp nhận.
Prior assistant serialization trong input không phải completion đang bị decoder ép.

Trước freeze, bổ sung system rules về chuẩn hóa amount theo schema, không thêm
amount/currency ngoài schema, không đoán thiếu thông tin, chỉ dùng bằng chứng đã
quan sát, và tôn trọng phủ định/tự sửa. Instructions không phát hiện được mọi ASR
text sai nhưng trôi chảy. Không thêm gold transcript vào noisy prompt làm oracle.

Freeze cả renderer, prompt content, tool/schema order, tokenizer/chat-template
revision và grammar, không chỉ SYSTEM hash. Loss chỉ trên final completion + EOS;
mask system/request/tools/history/prior actions/results. Assistant-only mask mà
vẫn học historical assistants là không đủ.

## 4. Next-Action SFT, LoRA và phần cứng

Next-Action khớp `Planner.next_action` và runtime. Lookup-dependent IDs/amounts/
branching làm full-sequence prediction từ đầu dễ phải đoán. Full-sequence chỉ nên
nghiên cứu sau nếu số lượt LLM là bottleneck đã đo; không đổi baseline lúc này.

Trade-offs: nhiều inference passes; repeated prefill; exposure bias vì gold prefix
khác predicted prefix; gold chỉ có một thứ tự calls dù các reads độc lập có thể
đổi thứ tự. Next-action exact accuracy là diagnostic, không thay closed-loop score.

Checkpoint chính xác `Qwen/Qwen3-4B-Instruct-2507`, non-thinking, `model_type=qwen3`;
metadata công khai ghi 4.022.468.096 parameters, license Apache-2.0, tồn tại trước
cutoff 26/10/2026. Khớp adapter hiện tại. Nguồn chính thức ở cuối tài liệu.

Riêng weights 16-bit khoảng **7,49 GiB**. LoRA vẫn cần activations/logits,
adapter gradients/optimizer, CUDA/workspace. Mask prompt loss không loại bỏ toàn
bộ chi phí forward/backward. **Chưa chứng minh vừa 12 GiB.**

Đề xuất probe: micro-batch 1, rank nhỏ, gradient accumulation/checkpointing, base
frozen và xác nhận gradients đúng scope. Audit token lengths trước khi chốt training
context; không cắt mất lookup/history chứa target evidence để ép vừa VRAM.
QLoRA NF4 là fallback cần kiểm tra CUDA kernels/backward/update/save/reload thật.
Nếu đổi phương pháp, giữ cùng phương pháp cho L1–L3 để tránh confound balancing.
Không sao chép Whisper LoRA wrapper/config sang causal-LM một cách máy móc.

Qwen ~4,02B + PhoWhisper-large ~1,55B = ~5,57B danh nghĩa. Cần count actual
deployed weights và unmerged adapters; quantization không giảm logical parameters.
LLM <5B, tổng <6B, context <=16384 theo provided brief. Model context gốc dài hơn
không nới giới hạn. Đủ parameter budget không chứng minh đủ VRAM hoặc đủ nhanh.

Ưu tiên merged checkpoint để reload qua adapter hiện tại; current loader không có
explicit PEFT/4-bit loading path. Export/requantization phải evaluate lại, không
giả định giữ nguyên output. Freeze local snapshots/packages và kiểm tra offline A30.

## 5. L0–L3 và evaluation công bằng

Manifest seed 42 hiện khớp hash Train. Identity đầy đủ trong reports.

| Partition | Sources | Normal calls | Ask | Finish sau calls | Initial finish | Rows |
|---|---:|---:|---:|---:|---:|---:|
| Fit | 1.236 | 2.684 | 172 | 972 | 92 | 3.920 |
| Validation | 309 | 640 | 45 | 245 | 19 | 949 |

Split theo groups trước expansion; dùng chung membership ASR/LLM để tránh planner
Validation nằm trong ASR fit. Grouping hiện là heuristic audio/text/template,
không chứng minh loại bỏ mọi semantic duplicate. Validation chỉ có 19 no-action
samples: một mẫu đổi recall khoảng 5,26 điểm %. Báo numerator/denominator và
uncertainty, không kết luận winner từ một hoặc hai mẫu.

| Experiment | Đề xuất |
|---|---|
| L0 | Pretrained + chính P1/grammar/decoding sẽ dùng sau SFT |
| L1 | Gold transcript, audited natural rows; đối chứng chính |
| L2 | Cùng data/base/budget, weights normal/ask/post-finish/initial-finish = 1/2/1/2 |
| L3 | Khởi tạo độc lập từ pretrained; policy L1/L2 được chọn; clean + approved noisy views |

L2 2x là ablation nhẹ, chưa tối ưu. Source balancing không tạo row balancing;
đều hóa rows bằng oversampling sẽ cần khoảng 15x ask/30x initial-finish so với
normal calls trên toàn corpus, dễ thuộc mẫu/IDs và lệch phân bố. Weighted sampling
cũng lặp minority; loss weighting có thể khuếch đại nhãn lỗi hoặc short targets.
Chỉ dùng một cơ chế balancing ban đầu, ưu tiên loss weighting với cách normalize
completion loss được định nghĩa như nhau ở L1/L2. Không vừa sampler 2x vừa loss 2x.

Nếu dùng weighted sampling trên raw Fit counts, ask chuyển từ ~4,39% lên ~8,22%,
initial finish từ ~2,35% lên ~4,40%; weight 2x không có nghĩa tỷ lệ sau normalize
tăng đúng 2x. Counts phải tính lại sau quality/token filtering.

Freeze common split, prompt, tokenizer, base revision, LoRA scope/rank, training
method, update/token budget, checkpoint-selection rule, decoding, runtime, ASR,
timeouts và selection_filter. Cùng epochs không đảm bảo cùng training budget.
L3 phải ghi view-selection/mixing policy, không nhân đôi data rồi train thêm mà
quy hết lợi ích cho robustness. Natural L1 cũng cần định nghĩa row/token loss normalization.

ASR fine-tuned trên Fit rồi nhận dạng lại Fit có in-sample errors, có thể quá nhẹ
so với Validation; đó không phải Validation leakage nếu partition đúng nhưng là
distribution mismatch. Out-of-fold predictions đáng cân nhắc sau, chi phí cao hơn.

Trong workspace lúc review chưa có `.agent-work/asr-finetune`; ASR README ghi chưa
có large-suite scores/checkpoint. **Best fine-tuned PhoWhisper-large là dependency
chưa được chứng minh**, không phải checkpoint đã chọn hoặc winner được đo.

### 5.1 Metrics

Mỗi L0–L3 cần G (gold transcript) và A (cùng fixed-ASR transcript cache), trên
cùng Validation IDs. [evaluation-template.json](reports/evaluation-template.json)
để toàn bộ metrics chưa đo là null.

| Metric | Ý nghĩa/giới hạn |
|---|---|
| Tool-call F1 | Closed-loop actual calls, match theo provided rules; ghi rõ có/không state gate |
| Ask precision/recall | Báo presence và strict tool_name/params; không chỉ gọi đúng sys |
| No-action precision/recall | Gold empty calls riêng, không gộp post-call finish |
| Premature finish | Teacher-forced finish khi gold next action là call; closed-loop cần reference đáng tin |
| Next-action accuracy | Teacher-forced gold prefixes, không phải live-agent success |
| Argument accuracy | Joint và conditional on correct tool; object key order không phải semantic error |
| Macro-F1 | Chốt lớp; tách normal call, ask, initial finish, post-call finish theo prefix |
| Final State Match | Chỉ khi reference/evaluator đã xác minh; không hash partial label.final_state |
| Mean/P95 latency | Scope rõ: cached planner+tools khác audio end-to-end |
| Peak VRAM | Scope rõ: planner/training/joint ASR+planner; không suy từ weights |
| Coverage/errors/timeouts | Báo toàn denominator, không chỉ các mẫu thành công |

Teacher-forced diagnostics dùng gold prefixes chỉ trong evaluation riêng. Closed-loop
dùng predicted actions + actual results, không gold observations. Non-fuzzy arguments
phải đúng; fuzzy scoring token-F1 >0,6 sau lowercase/NFC theo provided brief.
Không tự đặt aggregate organizer score khi brief chưa xác định aggregation.

Cached-ASR mode giúp cô lập planner; không gọi cached latency là end-to-end. Cần
acceptance audio thật gồm historical ASR, planner, tools và joint VRAM trên A30,
30 giây/sample. Failures/timeouts giữ trong denominator, không giả thành empty calls.

### 5.2 Mười Validation cases cho bảng predicted calls

Đã kiểm tra membership; chọn trước predictions, dùng minh họa không thay full 309 IDs:

| ID | Trọng tâm |
|---|---|
| train_0072 | Điều kiện giá vàng và chuyển khoản |
| train_0003 | Topup + wallet transfer theo bill amount |
| train_0074 | Chọn nguồn bill payment và reminder |
| train_0173 | Thiếu amount sau actions khác |
| train_0052 | Thiếu/không xác định được contact ID |
| train_0038 | Phủ định, initial finish |
| train_0447 | Yêu cầu không thực hiện, gold empty |
| train_1428 | Amount/account từ history |
| train_1144 | Tự sửa currency |
| train_0105 | History dài, schedule và reminder |

Lưu gold/current-ASR input, predicted calls L0–L3, actual observations, stop reason,
argument diffs và timings. Không chọn lại sau khi thấy model thắng/thua.

## 6. L3 filtering và xây dựng data

Giữ clean audited dataset làm nền; thêm noisy views **ở cấp row** khi target và
prefix còn được input hỗ trợ. Không ghép gold+ASR text trong cùng training prompt
nếu inference chỉ có ASR: đó là privileged input và train/inference mismatch.

1. Freeze groups chung ASR/LLM, rồi expand trajectories.
2. Sinh ASR cho Fit current và historical users, ghi revision/config/provenance.
3. Tách clean/noisy views, provenance không vào prompt.
4. Xác định amount+currency+recipient/action binding, IDs, phone, time, conditions,
   negation và corrections; nguồn có thể là history/prior results, không chỉ transcript.
5. Kiểm tra từng next target và toàn strict prefix. Schema-valid hoặc literal ID
   xuất hiện chưa đủ chứng minh đúng ý định/selection.
6. Keep verified rows; unknown vào review/exclude. Không invent labels, results,
   chain-of-thought, ID hoặc extra finish. Kiểm tra cả downstream terminal rows.
7. Báo accepted/excluded counts theo tool/type/reason/tokens; recompute distributions.

`train_0030` sai riêng amount có thể giữ account/beneficiary lookups, không giữ
transfer/finish máy móc. `train_1144` sai riêng phần 300 USD có thể giữ row 80000
JPY nếu cấu trúc/điều kiện request vẫn tương đương cho row đó. Các ví dụ này là
đề xuất xử lý hypothetical ASR errors, không phải ASR predictions đã đo.

Semantic checks: normalize số và đơn vị; giữ currency/recipient/action binding;
resolve relative time theo sample context; kiểm tra corrections/negation/conditions;
đối chiếu history/results trước target; manual review các cases không chắc chắn.
WER, embedding similarity, cùng tập số hay LLM judge đơn lẻ không đủ đảm bảo.
Parser của "một triệu hai"/"một trăm rưỡi" cũng cần context, không universal regex.

Để budget công bằng, có thể chọn clean/noisy view cho mỗi base row mỗi lượt theo
tỷ lệ cố định, thay vì nhân đôi data và giữ nguyên epochs. Tỷ lệ là lựa chọn chưa
chốt; không gán một tỷ lệ tối ưu khi chưa đo.

Counterfactual relabeling không thuộc L3 đầu tiên. Brief cho phép synthetic
development data nhưng sửa amount kéo theo balance, branches, results và terminal
behavior. Phải kiểm chứng intent mới + arguments + trajectory, không giữ old results/
state hoặc coi tool execution success là semantic correctness. Nếu làm sau này,
tách synthetic experiment có provenance, chỉ dùng Fit, tuân thủ one-ToolEnv per
sample/run và không dùng Public/Private Test. Không gọi đó là khôi phục audio gốc.

## 7. Kiến trúc và workflow đề xuất

```text
Offline: Train Fit -> quality audit -> next-action rows -> clean/approved ASR views
        -> LoRA hoặc QLoRA -> checkpoint -> offline export/reload/evaluate

Inference: Audio + context/history -> fixed ASR -> P1 -> Qwen next action
                                                   ^          |
                                                   |          v
                                              observation <- ToolEnv
```

Một general planner, cùng call/finish grammar. Python giữ validation/dispatch/
bounds/authoritative call log/hash; một ToolEnv/sample, không replay history.
ASR và training tách khỏi agent runtime. Không thêm decomposition/explicit CoT.
Constrained decoding đã có; SFT cần cải thiện semantics, không chỉ JSON syntax.

Mặc định tắt optional selection_filter cho P1 experiments; nó có prompt phụ và
thêm decision pass. Nếu bật, freeze ở mọi experiment và audit tương ứng, không
quy lợi ích của filter cho SFT.

L1–L3 độc lập từ cùng pretrained revision; L3 lấy policy thắng L1/L2, không tự
warm-start checkpoint thắng. Checkpoint selection dựa Validation vẫn là development
selection, không phải độc lập test score; predeclare rules và báo multiple comparisons.

Workflow tương lai theo mẫu [ASR RUNBOOK](../../../asr/fine-tuned/RUNBOOK.md):
prepare/audit suite một lần; mỗi invocation một experiment; lưu best/latest,
optimizer/RNG/sampler và evaluation artifacts; resume explicit, kiểm tra identity;
compare chỉ đọc results, không load model/train/infer lại. Failed/skipped/missing
rows vẫn hiển thị. Các JSON ở đây **chưa phải implementation của workflow đó**.

## 8. Những việc cần chốt trước implementation

1. P1/renderer/template/completion field order và token loss mask contract.
2. Gold quality policy, nhất là train_1696; không biến mọi gold call thành positive sạch.
3. ASR checkpoint/export/provenance/Validation evidence thật trước L3.
4. Token length và argument grounding audit, đặc biệt history/conditions/corrections.
5. Một cơ chế L2 weighting, loss normalization, budget và checkpoint-selection rule.
6. L3 row+prefix acceptance criteria, unknown/manual review và downstream finish policy.
7. 12-GiB resource probe để chọn LoRA/QLoRA chung L1–L3.
8. Evaluator/reference, split ownership, fixed-ASR cache và mười diagnostic IDs.

Không promote checkpoint chỉ vì training loss/teacher-forced accuracy thấp/cao hơn.
Giữ pretrained fallback nếu closed-loop gains, eligibility, reproducibility hoặc
A30 offline/30-second acceptance chưa được chứng minh.

## Nguồn và code cần đối chiếu

- [Train-to-SFT design](../../design/train-to-sft.md),
  [roadmap](../../../context/roadmap.md),
  [architecture](../../../context/architecture.md),
  [benchmark](../../../context/benchmark.md),
  [provided competition brief](../../reference/lifemate-competition.md),
  [testing](../../../context/testing.md).
- [dataset.py](../../../python/src/lifemate/dataset.py),
  [prompting.py](../../../python/src/lifemate/prompting.py),
  [planner.py](../../../python/src/lifemate/adapters/planner.py),
  [constrained.py](../../../python/src/lifemate/adapters/constrained.py),
  [agent.py](../../../python/src/lifemate/agent.py),
  [model_budget.py](../../../python/src/lifemate/model_budget.py).
- [Official Qwen model card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507),
  [config](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/raw/main/config.json),
  [parameter metadata](https://huggingface.co/api/models/Qwen/Qwen3-4B-Instruct-2507).
- [PEFT quantization](https://huggingface.co/docs/peft/v0.17.0/en/developer_guides/quantization),
  [TRL SFT Trainer](https://huggingface.co/docs/trl/en/sft_trainer).
  Tài liệu thư viện xác nhận API/phương pháp, không chứng minh VRAM, chất lượng
  hoặc tốc độ của JarvisMate. Final competition instructions vẫn cần được đối chiếu.
