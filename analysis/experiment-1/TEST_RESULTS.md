# Kết quả kiểm tra Experiment 1

Ngày: 11/11/2026. Local Windows, Python **3.13.9**; target UIT cần Python 3.11+ và venv inference đã freeze. Source snapshot lấy đúng Git object **047879eb0931e5fa85930d640fb4c0b71d9268bc**. Không chạy model thật, ASR, planner inference GPU, training hoặc submit Slurm.

## Unit tests CPU

| Nhóm | Tests | Kết quả |
| --- | ---: | --- |
| Harness: preparation/oracle/scorer/paired runner | **35** | PASS |
| 011: test_integration_config.py | 25 | PASS |
| 011: test_asr_once.py | 6 | PASS |
| 011: test_integration_pipeline.py | 15 | PASS |
| 011: test_integration_diagnostics.py | 8 | PASS |
| Tổng | **89** | PASS |

Log đầy đủ: [harness unit tests](test-results/unit-tests.log), [pinned integration tests](test-results/pinned-integration-tests.log). Metadata commands/exit codes: [unit-tests.json](test-results/unit-tests.json), [pinned-integration-tests.json](test-results/pinned-integration-tests.json).

Tests dùng doubles cho model/inference và artifact fixtures, không xác nhận GPU timing hoặc memory. Có kiểm case hash mismatch/F1 hoàn hảo, Gold-empty, missing predictions, oracle result mismatch, invalid oracle hash, typed arguments, ambiguous maximum vs greedy matching, ngưỡng fuzzy đúng 0.6, duplicate/schema-rejected calls, failed denominator, signed latency delta, fixed history không ASR, current labels bị loại, source/config/helper integrity, server path guard, main smoke gate, không retry và partner vẫn chạy sau lỗi. Positive trace fixtures có tool results; flagged truncation chặn evidence gate. Injected test oracle không được coi như real Train oracle.

## Kiểm tra bằng Train/runtime thực

CPU-only experiment cuối: `local-checks/train-cpu-release/` (ignored, không đóng gói để triển khai). Source và helpers được freeze bên trong experiment; toàn bộ actual data đọc từ Train local. Không mở hidden files trực tiếp trong harness; chỉ ToolEnv load initial state qua public API.

| Kiểm tra | Kết quả |
| --- | --- |
| Preparation trên Train | **1545/1545** fixed base inputs; 1434 Gold non-empty, 111 Gold-empty |
| TOML/schedule | **7 block main**, luân phiên OFF→ON/ON→OFF; cùng selection/inputs, KV=true/debug=true/transcript ở hai arm; chỉ flag retrieval và output root khác |
| Gold oracle CPU-check smoke | **16/16 valid**, 27 Gold calls; returned results và authoritative calls khớp exact typed JSON với labels |
| Gold oracle CPU-check main | **1545/1545 valid**, 3541 Gold calls; 0 reference inconsistencies/errors |
| Integrity sau replay | PASS: 57 protected visible/runtime/submission inputs, source/helpers/protocol và model inventory; không có model local được cung cấp |
| Thử gọi runner trên local profile | Expected exit **2**, đúng lỗi `GPU runner refuses CPU-local/unverified model profile`; không tạo `runs/` hoặc launch integration |

Tóm tắt máy đọc được: [cpu-checks.json](test-results/cpu-checks.json). Experiment digest cuối: `02f87fe9e002fba971cb768924ee7602e08e39235fd930ad01196295ddb2cfc9`.

Digest kết quả reference toàn Train: `3facfdba6c184e29806a81cb350a44bb03a7c7df851e02f1dc1bb24fdadbaa33`. Reference hash rows: `2eb27d9a03a71766999cdd1f177385347f82de1d9cf66784e9bf47ffbc5cab75`.

Các outputs ở `gold/cpu-check-smoke/` và `gold/cpu-check-main/` **không dùng làm reference chấm hai arm**; scorer chỉ đọc normal evaluation oracle sau paired inference. Không có Control/Treatment model predictions thực hoặc score ablation thực trong kết quả này. `train-cpu-001/` và `train-cpu-final/` là các artifact CPU trung gian trước đợt kiểm cuối, cũng ignored và không dùng cho kết luận triển khai. CPU release commands được ghi tại [cpu-release-commands.json](test-results/cpu-release-commands.json).

## Chưa kiểm được tại local

- Không có checkpoint/venv inference thật dưới asset layout UIT mới, nên chưa chạy header/weight preflight của chính checkpoint đó. Server preparation yêu cầu manifest 011 gốc để đối chiếu weight/tokenizer/template/parameter-count/code/Library identity; không thay bằng model giả.
- Chưa xác minh CUDA, GPU memory fit, actual model decoding, same-allocation latency/soft deadlines hoặc smoke inference 16 mẫu. Các kết quả này chỉ có sau khi operator chốt chạy UIT.
- Đã thử `bash -n harness/exp1.sbatch`, nhưng Windows Bash executable không truy cập được (`NativeCommandFailed`). **Không ghi pass**; phải chạy `bash -n` trên UIT trước submit. Partition/GRES/account/QoS/walltime chưa được xác nhận; job không có tên tài nguyên phỏng đoán.
- Official scorer chưa có trong gói được review. Maximum bipartite matching + regex/NFC F1 và local macro score được công khai là local policy, không gọi là official LB.
- Chưa có holdout provenance của checkpoint; Train diagnostic không chứng minh cải thiện trên dữ liệu chưa fit.

## File được tạo/sửa

Tạo: `_common.py`, `prepare.py`, `gold_oracle.py`, `score.py`, `run_pair.py`, `exp1.sbatch` trong `harness/`; `tests/support.py` và ba test modules; README, test report, `.gitignore`, các logs/JSON trong `test-results/`. Artifact kiểm CPU được tạo riêng trong `local-checks/`, gồm source archive, inputs/configs và Gold CPU-check outputs có provenance đầy đủ.

Sửa: `analysis/experiment_1_skill_retrieval_ablation_plan.md` để ghi trạng thái implementation, link runbook và chuyển các asset paths server sang TMP. Không sửa file trong repository JarvisMate, source 009/011, submissions hoặc checkpoint. Branch hiện vẫn 010/HEAD `8510d51ef1648a39a8e27bcecc05851447a64b39`, staged changes cũ được giữ nguyên. Không commit/push trong task này.

Lệnh CPU, triển khai UIT, smoke16 và các gate trước full experiment ở [README](README.md).
