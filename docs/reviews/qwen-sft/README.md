# Qwen planner SFT: review và bàn giao

Ngày: **2026-11-01**. Source được review: **`f9226c4`**.

Đây là gói **review/design**, chưa phải implementation hoặc kết quả training.
Checkpoint được thống nhất: **`Qwen/Qwen3-4B-Instruct-2507`**; đề xuất Qwen3.5 trước đó đã được thay thế.

## Agent tiếp theo cần đọc

1. [review.md](review.md): báo cáo tổng hợp hai lượt review, evidence số tiền/IDs,
   phản biện L3, P1, LoRA, L0–L3, evaluation và các quyết định còn mở.
2. [reports/data-audit.json](reports/data-audit.json): thống kê tính trực tiếp từ
   Train JSONL/catalog và manifest split seed 42; phân biệt source samples và action rows.
3. [reports/sample-evidence.json](reports/sample-evidence.json): tám sample minh họa,
   line nguồn, gold calls, trích dẫn field cần thiết và vấn đề `train_1696`.
4. [reports/validation-review-set.json](reports/validation-review-set.json): mười
   sample thực sự thuộc Validation, được chọn trước predictions để so sánh L0–L3.
5. [reports/experiment-plan.json](reports/experiment-plan.json) và
   [reports/evaluation-template.json](reports/evaluation-template.json): kế hoạch
   thí nghiệm và mẫu báo cáo; **không phải config trainer chạy được**. Metrics `null`
   là chưa đo, không phải zero.
6. Đối chiếu [Train-to-SFT design](../../design/train-to-sft.md),
   [benchmark rules](../../../context/benchmark.md),
   [architecture](../../../context/architecture.md) và
   [testing](../../../context/testing.md), rồi đọc các hàm được dẫn trong review.

## Phạm vi bàn giao

- Đã thực hiện: đọc source và dữ liệu, tính thống kê, kiểm tra membership của mười
  Validation IDs, ghi nhận rủi ro và đề xuất.
- Chưa thực hiện: exporter SFT, trainer LLM, inference L0–L3, probe GPU, lựa chọn
  checkpoint PhoWhisper-large hoặc xác minh evaluator Final State Match.
- Không đọc file dưới `*_environment/` hoặc `*_enviroment/`.
- JSON reports là evidence/đặc tả để review; không đưa reports, Validation examples
  hoặc gold references vào inference prompt, SFT fit hay retrieval.
- Raw dataset, audio, full contexts/history, hidden state, model weights và local
  split manifest không nằm trong commit này. Sample evidence chỉ trích phần cần cho review.

## Kiểm tra gói báo cáo

Ngày 2026-11-01: parse thành công 5 JSON reports; đối chiếu transcript, gold calls,
line và partition của 8 evidence samples cùng 10 diagnostic samples với Train và
manifest local; kiểm tra 48 local Markdown links. Counts source/action rows và
split SHA khớp. Tất cả metric trong evaluation template vẫn là `null`/`not_run`.
Đây là kiểm tra tài liệu/evidence, không phải test pipeline, inference hoặc training.

## Prompt bàn giao gợi ý

> Đọc `docs/reviews/qwen-sft/README.md` rồi các file theo thứ tự ở trên. Review kế
> hoạch Qwen3-4B-Instruct-2507 Next-Action SFT cho JarvisMate. Phân biệt evidence
> đã tính với proposed policy và unmeasured metrics. Ưu tiên kiểm tra L3 row/prefix
> grounding, completion serialization so với constrained decoder, quality exclusions,
> chung split ASR/LLM, fairness L1/L2/L3 và evaluator. Chỉ implementation/training
> khi người dùng yêu cầu riêng; không coi tài liệu này là lệnh chạy experiment.
