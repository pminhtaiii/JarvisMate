# Handoff: chạy train planner QLoRA trên server GPU

**Mục tiêu:** train một adapter theo recipe cố định, xuất snapshot FP16 đã merge, rồi gửi lại evidence.

**Trạng thái hiện tại:** code và test đã xong. Đường NF4/bitsandbytes/GPU **chưa từng chạy thật**, nên lỗi ở đó là điều có thể xảy ra. Hãy dừng và báo lại, đừng tự sửa recipe.

**Bảo mật:** dữ liệu ZAC 2026 chỉ dành cho đội đã đăng ký và không được phát tán. Không commit dữ liệu, dòng SFT, trọng số hay trace vào git.

## Người giao việc điền trước khi gửi

- [ ] Đã `git push` nhánh `codex/006-planner-sft-baseline` (từ commit `7b25503` trở đi).
- [ ] File validation có nhãn, **không trùng với train**: `<đường dẫn>`. Gói dữ liệu v3.2.0 không có sẵn file này. Thiếu nó thì không chạy được bước `prepare`.
- [ ] File train: `<đường dẫn>`. Nếu validation được tách từ train, đây phải là phần còn lại sau khi tách.
- [ ] Quyết định về `train_1696`: loại (đề xuất) hoặc giữ. Xem bước 4.
- [ ] Server, GPU được dùng (RTX 5090 hoặc H200), thư mục lưu kết quả: `<điền>`.

## 1. Cài môi trường

Cần Linux, Python >=3.11 và một GPU. Dùng venv riêng, **không cài extra `training` vào Docker runtime**.

```bash
git clone <repo-url> JarvisMate && cd JarvisMate
git checkout codex/006-planner-sft-baseline
python -m venv .venv-sft && . .venv-sft/bin/activate

# Chọn wheel CUDA hợp với server; RTX 5090 cần CUDA 12.8 trở lên
pip install --index-url https://download.pytorch.org/whl/cu128 torch==2.9.0
pip install "./python[inference,training]"

python -c "import torch; print(torch.cuda.is_available(), torch.version.cuda, torch.cuda.get_device_name(0), torch.cuda.is_bf16_supported())"
python -c "import peft, bitsandbytes, accelerate; print(peft.__version__, bitsandbytes.__version__, accelerate.__version__)"
```

Lệnh đầu phải in `True` và đúng tên GPU. Nếu torch 2.9.0 không có wheel phù hợp với server thì dừng và báo lại, không tự đổi phiên bản đã pin.

## 2. Tải model base

```bash
python -c "from huggingface_hub import model_info; print(model_info('Qwen/Qwen3-4B-Instruct-2507').sha)"
hf download Qwen/Qwen3-4B-Instruct-2507 --revision <sha-vừa-in> --local-dir /models/Qwen3-4B-Instruct-2507
```

Ghi `<sha>` vào `model.revision` ở bước 3.

## 3. Tạo config

Copy `configs/planner-sft.example.toml` ra một file ngoài repo, ví dụ `/config/sft.toml`, rồi sửa:

| Trường | Giá trị |
|---|---|
| `data.train_jsonl`, `data.train_catalog` | File train và catalog của nó |
| `data.validation_jsonl`, `data.validation_catalog` | File validation và catalog của nó |
| `model.base_path`, `model.revision` | Thư mục và sha từ bước 2 |
| `training.device` | `cuda:0` (số thứ tự trong các GPU đang nhìn thấy) |
| `output.experiment_dir` | Thư mục mới, **nằm ngoài** thư mục model và thư mục chứa dữ liệu |

Không đổi `recipe`, `seed` và `limits`. Giữ `microbatch = 1`, `accumulation = 16`. Đường dẫn tương đối được tính từ thư mục chứa file config.

## 4. Xử lý mẫu bị gắn cờ (nếu dùng `train_1696`)

Mẫu này chặn `prepare`, vì gold gọi `chat_6142`, một ID chưa từng xuất hiện, và kết quả trả về là không tìm thấy. Nếu người giao việc chọn loại, tạo `/config/sft-resolutions.json`:

```json
{"resolutions": [{"source_id": "train_1696", "reason": "UNGROUNDED_ID",
                  "decision": "exclude", "note": "Gold invents chat_6142; its result reports not found"}]}
```

Rồi thêm vào `[data]` trong config:

```toml
audit_resolutions = "/config/sft-resolutions.json"
```

Nếu file train không chứa mẫu này thì đừng thêm dòng resolution của nó: resolution không khớp với mục audit nào sẽ bị từ chối. Nếu `prepare` gắn cờ mẫu khác, gửi `sft/audit.jsonl` cho người giao việc quyết định, đừng tự thêm.

## 5. Chạy từng bước

Chạy từ thư mục gốc của repo, trong `tmux` hoặc `screen`. Chỉ sang bước sau khi bước trước trả exit code 0.

```bash
export CUDA_VISIBLE_DEVICES=0   # chỉ để lộ đúng GPU đã chọn
CFG=/config/sft.toml
EXP=<output.experiment_dir>

python -m lifemate.sft preflight --config "$CFG"
python -m lifemate.sft prepare   --config "$CFG"
python -m lifemate.sft train     --config "$CFG" --smoke
```

**Kiểm tra trước khi train đầy đủ:**

- `prepare` in `state: ready`, `overlap.status: disjoint`, và `sources_unresolved` của train bằng 0.
- `$EXP/smoke/smoke_report.json` có `frozen_unchanged: true`.
- `$EXP/smoke/environment.json` ghi đúng GPU và có `feasibility.peak_allocated_bytes`. So số này với bộ nhớ GPU.

Smoke chỉ chạy 2 update, nên đây **không phải** kết quả train. Muốn chạy lại smoke, hãy chuyển thư mục `$EXP/smoke` sang chỗ khác trước.

```bash
python -m lifemate.sft train    --config "$CFG"
python -m lifemate.sft export   --config "$CFG" --selection "$EXP/selection.json"
python -m lifemate.sft diagnose --config "$CFG" --selection "$EXP/selection.json"
```

**Kết quả mong đợi:**

- `train` chạy 500 update, lưu checkpoint tại 100, 200, 300, 400, 500 rồi ghi `selection.json`. Chưa có số đo về thời gian chạy.
- Chỉ checkpoint đã phủ hết mọi dòng train mới được chọn. Update đủ điều kiện đầu tiên là bội số 100 nhỏ nhất đạt `rows / 16`. Với khoảng 4800–4865 dòng, đó là 300 hoặc 400. Update sớm có NLL thấp hơn mà không được chọn là **đúng thiết kế**.
- `export` chạy trên CPU và tạo `$EXP/merged_fp16`, với `export_manifest.json` ở `state: reload_verified`. Ước tính cần khoảng 16 GB RAM trở lên khi merge; con số này chưa được đo.
- `diagnose` dùng GPU và ghi `export_diagnostics.json`. Bản merge khác adapter vẫn có thể xảy ra, chỉ cần ghi nhận, không phải lỗi.

## 6. Khi có sự cố

Mọi lỗi đều in một dòng JSON ra stderr với `code`, `stage`, `message`, và exit code khác 0. Hãy giữ nguyên dòng đó và cả thư mục experiment.

| Dấu hiệu | Xử lý |
|---|---|
| `SFT_BLOCKED` ở `prepare` | Xem `sft/export_manifest.json` (`blocked_reasons`, `overlap`) và `sft/audit.jsonl`, rồi báo người giao việc |
| `INPUT_INVALID`, `ASSET_MISSING` | Kiểm tra config và đường dẫn. Đường dẫn có thư mục tên `public_test` sẽ bị từ chối theo chủ ý |
| `MODEL_UNAVAILABLE` | Kiểm tra GPU, BF16, snapshot, extra `training` |
| `SFT_TRAINING` do hết bộ nhớ GPU | Dừng và báo lại. Không giảm độ dài, không đổi recipe, không đổi batch |
| `SFT_TRAINING` do loss hoặc gradient không hữu hạn | Dừng và báo lại, gửi kèm `training_metrics.jsonl` |
| `SFT_IDENTITY` | Dữ liệu, model, gói Python hoặc checkpoint đã đổi so với lúc chạy. Không sửa tay các file manifest |
| `SFT_SELECTION` | Không có checkpoint đủ điều kiện. Không tự chọn tay |
| `SFT_EXPORT` | Gửi lỗi. Nếu `merged_fp16` đã tồn tại, chuyển nó đi trước khi export lại |

**Train bị ngắt giữa chừng:** tiếp tục từ checkpoint mới nhất, trong cùng môi trường Python:

```bash
python -m lifemate.sft train --config "$CFG" --resume "$EXP/checkpoints/step-0300"
```

Nếu ngắt trước update 100 thì chưa có checkpoint: chạy lại lệnh `train` không kèm `--resume`.

**Muốn đổi dữ liệu sau khi đã có checkpoint:** `prepare` sẽ từ chối. Hãy dùng `experiment_dir` mới.

## 7. Gửi lại

Gửi qua kênh nội bộ của đội, không qua git:

- [ ] Các lệnh đã chạy và exit code tương ứng; commit đã chạy (`git rev-parse HEAD`); sha của model.
- [ ] `effective_config.json`, `environment.json`, `selection.json`, `training_metrics.jsonl`, `export_manifest.json`, `export_diagnostics.json`, `sft/export_manifest.json`, `sft/audit.jsonl`, `smoke/smoke_report.json`.
- [ ] Thời gian thực tế của mỗi bước và lượng GPU peak.
- [ ] Vị trí lưu `merged_fp16/` và `adapter/`.
- [ ] Mọi lỗi đã gặp, kể cả lỗi đã vượt qua.

`environment.json` đã có sẵn `pip freeze`, đây là lock của lần chạy.

## Ngoài phạm vi handoff này

- Không tìm hyperparameter, không đổi recipe, không chạy lần train thứ hai khi chưa trao đổi.
- Không dùng public test hay private test để tune hoặc chọn checkpoint.
- Validation NLL **không phải** điểm thi, nên đừng báo cáo nó như điểm thi.
- Chấm thật trên validation với audio và ToolEnv (T021) cùng kiểm tra Docker/A30 (T022) là bước sau, đi qua runtime của feature 002 với `planner.model_path` trỏ tới `merged_fp16`.

## Tham khảo

[Recipe](plan.md) · [Hợp đồng CLI](contracts/training.md) · [Evidence đã đo](quickstart.md#recorded-evidence) · [ADR 012](../../docs/adr/012-native-planner-sft-baseline.md)
