# Tasks: PhoWhisper-large fine-tuning

**Ngày:** 29/10/2026. **Status:** source implementation và controlled/tiny CPU tests đã có; actual large/GPU experiments chưa chạy.
Checkbox [x] cho task authoring ghi source/controlled tests đã giao, không khẳng định GPU thành công. Tasks yêu cầu actual model/data/GPU vẫn mở. Việc
viết bộ specs không làm training, compatibility hay acceptance thành completed.
Thực hiện tuần tự; không có yêu cầu phân công nhiều agent trong checklist này.

## Phase 0 — Data và contracts

- [x] FT001 Triển khai schema/config loader strict; local paths, immutable model revision, seed và artifact policy theo plan.
- [x] FT002 Đọc/verify đúng split identity/source/WAV hashes; tạo fit-with-history và validation-current mà không re-split.
- [ ] FT003 Audit audio–text từng current/history user, token limits, duplicate/conflicting PCM; freeze fit manifest/dedup policy và counts. Fail thay vì skip im lặng.
- [x] FT004 Tests không GPU cho alignment, assistant/context/label exclusion, no environment reads, partition leakage, source mutation, missing/truncated audio, dedup và label padding/prefix.
- [ ] FT005 Chuẩn bị/review/freeze slot annotations cùng extractor/canonicalization; tests tiền, thời gian tương đối, địa chỉ, tên, code-switch, hallucination, missing gold và denominator 0.

**Gate D:** data integrity pass; 309 primary IDs/hash đúng; annotations có status
rõ. CSA thiếu vẫn cho phép training thử nhưng chưa cho phép kết luận slot/promotion.

## Phase 1 — Môi trường GPU và E0

- [ ] FT006 Chuẩn bị explicit local snapshot PhoWhisper-large, license/release/cutoff, SHA và file hashes; sửa/reuse preparation metadata API đã kiểm chứng.
- [x] FT007 Hoàn thiện policy large ở benchmark/preparation còn guard <1B; giữ hỗ trợ large/offload runtime đã có trên main, total <6B và LLM <5B. Tests đếm adapter/tied/quantized logical counts và biên thresholds.
- [ ] FT008 Tạo môi trường CUDA riêng; đo card/VRAM/capability/driver và test kernels, chọn FP16/BF16, khóa toàn bộ dependency/build versions. Không coi tên GPU là evidence compatibility.
- [x] FT009 Implement per-phase allocated/reserved/device VRAM capture, headroom checks, persistent workers/hard timeouts, failure artifacts.
- [x] FT010 Implement `run_e0.py`, primary metrics/latency protocol, coverage và CSV; tests dùng controlled adapter trước real-model smoke.
- [ ] FT011 Chạy E0 smoke, rồi full 309 validation trên GPU thật; lưu exact command/exit, model counts, latency, slots status và inference peak.

**Gate E0:** full coverage và inference resource/offline checks pass. Điểm medium
trong benchmark cũ không thay thế được E0 large.

## Phase 2 — E1 Decoder-only LoRA

- [x] FT012 Implement target module resolution chính xác decoder self/cross-attention q/v; frozen base và scope assertions, gradient-checkpointing/padding/loss tests.
- [x] FT013 Implement common trainer, optimizer/accumulation, evaluation history, best/latest checkpoint, RNG/sampler/scaler resume và deterministic seeds.
- [ ] FT014 Implement `run_e1.py`; kiểm tra forward/backward/update/save/reload và generation trong resource probe, bao gồm optimizer allocation và longest Train cases.
- [ ] FT015 Nếu probe pass, train E1; nếu fail lưu OOM/unsupported evidence. Export/reload candidate và full primary evaluation, không báo thành công từ smoke.

**Gate E1:** có run/status/evidence; E2 full training chỉ khi E1 có đối chứng hợp lệ.

## Phase 3 — E2 Encoder + Decoder LoRA

- [x] FT016 Implement `run_e2.py`, encoder+decoder q/v scope, không no-grad encoder; tests cả hai adapter phía có gradient/update.
- [ ] FT017 Probe E2 cùng budget/dtype/hyperparameters đối chứng. OOM thì lưu `failed_oom`; thiếu prerequisite thì `skipped_dependency`, không giả là OOM.
- [ ] FT018 Khi pass, train/export/evaluate E2 và so E1 bằng shared manifests/protocol; lưu mọi config adjustment thành run ID riêng.

**Gate E2:** có completed/failed/skipped record trước khi xét E3.

## Phase 4 — E3 QLoRA, có điều kiện

- [ ] FT019 Xác định mục tiêu VRAM/fallback, target scope và đối chứng E1/E2; hoặc ghi skipped_not_needed.
- [ ] FT020 Implement `run_e3.py`/NF4 k-bit preparation đúng Whisper input_features; test quantized modules, frozen base, adapter gradients, optimizer, generate, adapter reload trên stack/GPU thật.
- [ ] FT021 Không pass tương thích thì ghi unsupported; pass thì probe VRAM rồi train. Đo native NF4 và fresh-half-base export riêng, không tự chuyển int8.
- [ ] FT022 Full primary evaluation E3 nếu export đạt; native-only ghi variants và primary unavailable; báo actual memory savings chỉ khi có đối chứng đo được.

**Gate E3:** kết quả hoặc skip/unsupported có evidence, không mặc định QLoRA khả thi.

## Phase 5 — E4 LoRA + augmentation

- [ ] FT023 Chọn/freeze control E1/E2, update budget/config và tập noise non-speech hợp lệ; không có control thì ghi skipped.
- [x] FT024 Implement deterministic speed/noise/volume Train-only; tests no clipping, duration <=30s, reference unchanged, seed/resume, counts và không đụng Validation/Test.
- [ ] FT025 Implement `run_e4.py`, fresh pretrained initialization và matched control budget; probe worst augmented shapes, nghe kiểm tra Train rồi mới full train nếu pass.
- [ ] FT026 Export/evaluate E4 cùng corpus/protocol, so cả control và E0; không dùng thêm epochs/steps ngầm để tăng score.

## Phase 6 — Báo cáo và tích hợp

- [x] FT027 Implement compare/report: đủ E0–E4 status rows, null cho unavailable, CSA/support/per-type/FP, WER/CER, timing, train/infer peak và checkpoint IDs; recompute từ per-row artifacts.
- [ ] FT028 Áp dụng selection/promotion policy, group-bootstrap uncertainty, log mọi Validation-guided trial; giữ E0 nếu không có cải thiện đủ evidence.
- [ ] FT029 Best export round-trip, fresh-process network-blocked loading/generation, processor completeness và thiếu-asset failure tests; không upload checkpoint tự động.
- [ ] FT030 Tích hợp ASR contract vào runtime, reuse current/history model và deadline/errors; regression kiểm tra total parameters, context bound, prompt/tool behavior giữ nguyên.
- [ ] FT031 Nếu pipeline/scorer sẵn sàng: paired E0/candidate Tool-call F1, authoritative Final State Match, coverage và total latency; nếu không, ghi unavailable và lý do.
- [ ] FT032 Đo joint VRAM với Qwen thực tế; chạy acceptance A30 offline/container và giới hạn 30s/sample trước submission claim. Nếu chưa có host thì ghi unverified, không coi train success là deployment success.
- [x] FT033 Viết README thực thi đã kiểm chứng: install/lock, commands E0–E4 tuần tự, gate/skip/resume, source/data hashes, best artifacts, report và giới hạn còn lại.

**Definition of done:** scripts/configs/tests được giao, E0–E4 đều có trạng thái thật,
best/retain-E0 decision có evidence, artifacts tái lập được. Training hoặc hardware
acceptance chưa chạy phải được nêu rõ; không đóng task execution bằng việc chỉ viết code.
