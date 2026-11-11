# LifeMate 011 — Experiment 1 harness

Harness ngoài repository, pin source **047879eb0931e5fa85930d640fb4c0b71d9268bc**. Không sửa Planner, Agent, KV cache, Skill Library, ToolEnv hoặc Git branches. Control = retrieval OFF/KV ON; Treatment = retrieval ON/KV ON. Chỉ Train transcript mode; debug payloads bật ở cả hai arm.

Đã implement và kiểm tra CPU. **Chưa chạy planner inference, training hoặc GPU/Slurm job.** Kết quả đã chạy và giới hạn tại [TEST_RESULTS.md](TEST_RESULTS.md). Thiết kế gốc trong workspace: `analysis/experiment_1_skill_retrieval_ablation_plan.md`; runbook hiện hành là README này.

## Các file

| File | Vai trò |
| --- | --- |
| [harness/prepare.py](harness/prepare.py) | Xuất Git archive đúng commit, freeze code/helpers/model/visible data/runtime và fixed inputs; chia block theo group, tạo smoke16 và TOML. |
| [harness/gold_oracle.py](harness/gold_oracle.py) | Gold Train qua public ToolEnv APIs; exact tool-results verification trước khi reference hợp lệ. |
| [harness/score.py](harness/score.py) | Kiểm journal/manifest/published predictions/trace/provenance; hash gate, transitions, maximum bipartite F1 và greedy diagnostic. |
| [harness/run_pair.py](harness/run_pair.py) | Preflight metadata, rồi chạy integration tuần tự theo AB/BA; không submit job/retry/resume. |
| [harness/_common.py](harness/_common.py) | Strict JSON, typed equality, path/integrity checks, chỉ nhập pure modules từ source snapshot. |
| [harness/exp1.sbatch](harness/exp1.sbatch) | Orchestration smoke, oracle, score; main chỉ khi explicitly opt in và smoke audit pass. |
| [harness/tests/](harness/tests/) | Unit tests CPU với doubles và artifact fixtures; không load model. |

Stdlib Python **3.11+** cho harness. Inference sau này cần environment đã freeze tương thích run 011 (torch 2.9.0, transformers 4.57.1, numpy 2.3.4, LMFE 0.11.3 cùng các transitive dependencies). Không upgrade venv baseline để chạy thí nghiệm. `--check-config` không xác nhận GPU memory fit.

## Triển khai lên UIT

Chỉ chuyển `harness/`, README và test report của bundle; không chuyển `local-checks/` như một experiment server có sẵn. Các experiment đã freeze dùng absolute paths và không được di chuyển. Preparation sẽ tự xuất source và copy helpers vào root mới.

Tất cả project assets/configs/checkpoint và output server phải nằm **thực sự** dưới `/datastore/binhvp/BuiTrongTan/tmp/`; helper từ chối data/model/runtime symlink trỏ ra ngoài. Không dùng lại paths cũ. Chuẩn bị trước:

```text
/datastore/binhvp/BuiTrongTan/tmp/
  assets/
    JarvisMate-011/               Git repo có object 047879e; chỉ đọc
    data/train+public_test/       official Train package, đầy đủ, chỉ ToolEnv đọc initial state
    models/planner-011/           bản sao checkpoint/tokenizer đã được kiểm identity, chỉ đọc
    provenance/public-011-manifest.json  manifest gốc của run 011 để so code/Library/model digests
  venvs/lifemate/bin/python       environment riêng đã freeze; giữ đúng venv executable path
  exp1-bundle/harness/            scripts + tests trong bundle này
  experiments/                   parent của các experiment mới
  cpu-tmp/                       optional TMPDIR cho unit tests
```

Không tự tạo checkpoint giả để qua server preflight. So weight/tokenizer hashes với manifest nguồn được tin cậy; không sửa, merge hoặc save vào checkpoint. Nếu thiếu assets hoặc split manifest của training, ghi rõ thay vì tuyên bố đã sẵn sàng hoặc có validation chưa thấy. Full Train là paired diagnostic, không là bằng chứng unseen generalization nếu checkpoint đã fit Train.

Các biến dưới đây chỉ là path triển khai mới; kiểm tra trên UIT trước khi chạy. Partition/GRES/account/QoS và walltime phải theo cluster thực tế, không có giá trị được phỏng đoán trong job.

```bash
set -euo pipefail
BASE=/datastore/binhvp/BuiTrongTan/tmp
BUNDLE="$BASE/exp1-bundle/harness"
PYTHON="$BASE/venvs/lifemate/bin/python"
SOURCE_REPO="$BASE/assets/JarvisMate-011"
DATA="$BASE/assets/data/train+public_test"
PLANNER="$BASE/assets/models/planner-011"
REFERENCE="$BASE/assets/provenance/public-011-manifest.json"
TASK="$BASE/experiments/lifemate-exp1-011-$(date -u +%Y%m%dT%H%M%SZ)"
test -x "$PYTHON"
test -f "$DATA/train/train.jsonl"
test -f "$DATA/train/zaic_tools/__init__.py"
test -f "$PLANNER/config.json"
git -C "$SOURCE_REPO" cat-file -e 047879eb0931e5fa85930d640fb4c0b71d9268bc^{commit}

# TASK không được tồn tại; prepare tự tạo, không mkdir TASK trước.
"$PYTHON" "$BUNDLE/prepare.py" prepare \
  --experiment "$TASK" --source-repo "$SOURCE_REPO" --data-root "$DATA" \
  --planner-model "$PLANNER" --model-reference-manifest "$REFERENCE" --seed 42 --block-size 256
"$PYTHON" "$TASK/harness/prepare.py" verify --experiment "$TASK"
```

Preparation chỉ đọc visible JSONL/catalog, runtime source, checkpoint files/headers, reference manifest và Git objects. Không model load hoặc ToolEnv instances. Server profile yêu cầu weight/tokenizer/template/parameter-count digests khớp manifest 011 gốc, code/Library identity trong reference cũng phải khớp commit đã pin; không lấy tên folder model làm bằng chứng. Reference manifest được đặt tại path TMP mới; các path lịch sử nằm trong nội dung manifest không được dùng để mở model/data. Nó lưu request/context/history/eligible schemas trong `inputs/base_inputs.jsonl`, **không lưu current label trong fixed planner input**. History calls/results hợp lệ vẫn là context và không replay thành current actions.

`--protect-file PATH` có thể lặp để bảo vệ thêm submission copy hoặc artifact cụ thể **nằm dưới TMP**. Các bản baseline gốc ở ngoài TMP không được mở làm output, chỉnh quyền hoặc sửa nội dung. Không walk/hash/parse `*_environment/` trực tiếp. ToolEnv tự load initial state, mutate trong bộ nhớ.

TOML strict schema không có `--transcripts` hay `gold_hash` key; generator dùng `mode="transcript"`, KV true, debug true, seed42, 16 steps, 16384 context, 512 output, 28s soft/30s hard, startup900s/recovery1. Paired configs chỉ khác retrieval flag và output root; false flag bị omit ở effective config theo code 011.

## Kiểm tra CPU

Trên UIT, trước GPU:

```bash
export PYTHONPATH="$TASK/harness:$TASK/harness/tests"
export PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
export EXPERIMENT1_TEST_SOURCE_REPO="$SOURCE_REPO"
export EXPERIMENT1_TEST_DATA_ROOT="$DATA"
mkdir -p "$BASE/cpu-tmp"
export TMPDIR="$BASE/cpu-tmp"
"$PYTHON" -B -m unittest discover -s "$TASK/harness/tests" -p 'test_*.py' -v
bash -n "$TASK/harness/exp1.sbatch"

# Inspect tất cả smoke config/model metadata/header/hash, không chạy model hoặc tools:
"$PYTHON" "$TASK/harness/run_pair.py" --experiment "$TASK" --phase smoke \
  --python "$PYTHON" --check-only

# Optional CPU oracle check; không cần inference và không trở thành reference chấm arm:
"$PYTHON" "$TASK/harness/gold_oracle.py" --experiment "$TASK" --phase smoke --cpu-check
"$PYTHON" "$TASK/harness/prepare.py" verify --experiment "$TASK"
```

`--check-only` không tiêu thụ phase; preflight logs có thư mục riêng. `--cpu-check` lưu vào `gold/cpu-check-smoke/`, scorer không đọc nó. Chạy `--phase main --cpu-check` có thể kiểm toàn bộ Gold Train bằng CPU nhưng không phải ablation inference. Mỗi oracle destination chỉ chạy một lần; không overwrite/replay để chọn reference tốt hơn.

Local Windows, không có checkpoint/GPU, dùng profile CPU-only:

```powershell
$env:PYTHONPATH = "$PWD\analysis\experiment-1\harness;$PWD\analysis\experiment-1\harness\tests"
.\.python\python.exe -B -m unittest discover -s analysis/experiment-1/harness/tests -p 'test_*.py' -v
.\.python\python.exe -B analysis/experiment-1/harness/prepare.py prepare `
  --experiment analysis/experiment-1/local-checks/NEW-CPU-CHECK `
  --source-repo JarvisMate --data-root train+public_test/train+public_test `
  --planner-model analysis/experiment-1/no-local-checkpoint --local --skip-model-check
.\.python\python.exe -B analysis/experiment-1/local-checks/NEW-CPU-CHECK/harness/gold_oracle.py `
  --experiment analysis/experiment-1/local-checks/NEW-CPU-CHECK --phase smoke --cpu-check
```

CPU-only profile **không được chạy GPU bằng paired CLI**, ngay cả khi có Slurm variables. `--skip-model-check` bị cấm ở server profile. Unit test injection không phải một CLI bypass để chạy model.

## Smoke 16 mẫu trong allocation

**Chưa thực hiện các lệnh inference dưới đây.** Hai arm dùng fresh integration subprocess/ToolEnv cho mỗi sample; không dùng chung state hoặc cache qua arm. Không chạy inference trên login node.

```bash
# Chỉ trong GPU allocation rõ ràng; helper yêu cầu SLURM_JOB_ID/CUDA_VISIBLE_DEVICES.
"$PYTHON" "$TASK/harness/run_pair.py" --experiment "$TASK" --phase smoke --python "$PYTHON"
"$PYTHON" "$TASK/harness/gold_oracle.py" --experiment "$TASK" --phase smoke
"$PYTHON" "$TASK/harness/score.py" --experiment "$TASK" --phase smoke
"$PYTHON" "$TASK/harness/prepare.py" verify --experiment "$TASK"
```

Hoặc Slurm smoke-only, sau khi chọn resource flags thật:

```bash
: "${UIT_PARTITION:?Set approved GPU partition}"
: "${UIT_GRES:?Set actual one-GPU or one-MIG GRES syntax}"
: "${UIT_WALLTIME:?Set allowed reservation for smoke}"
mkdir -p "$TASK/slurm"
sbatch --partition="$UIT_PARTITION" --gres="$UIT_GRES" --cpus-per-task=16 \
  --mem=64G --time="$UIT_WALLTIME" --export=ALL \
  --output="$TASK/slurm/%j.out" --error="$TASK/slurm/%j.err" \
  "$TASK/harness/exp1.sbatch" "$TASK" "$PYTHON"
```

Thêm account/QoS nếu UIT yêu cầu. Script không submit job khác. Job mặc định dừng sau smoke. Có thể opt in `EXPERIMENT1_RUN_MAIN=1` **trước một job mới trên một TASK mới** để job chạy smoke rồi main khi smoke audit pass. Không submit cùng script lại trên TASK đã có phase: helper/job cố ý từ chối retry/overwrite. Nếu smoke-only đã hoàn tất, chạy riêng main commands trong allocation tiếp theo; ghi thay đổi allocation, không giả định timing hai allocation giống nhau.

```bash
# Sau smoke thực sự pass; giữ frozen cohort/config/model/helpers nguyên trạng.
"$PYTHON" "$TASK/harness/run_pair.py" --experiment "$TASK" --phase main --python "$PYTHON"
"$PYTHON" "$TASK/harness/gold_oracle.py" --experiment "$TASK" --phase main
"$PYTHON" "$TASK/harness/score.py" --experiment "$TASK" --phase main
"$PYTHON" "$TASK/harness/prepare.py" verify --experiment "$TASK"
```

Main dùng full Train, block membership deterministic/grouped; OFF→ON và ON→OFF luân phiên theo block. Actual sample order theo Train JSONL, không theo shuffle selection file. Mọi run root phải chưa tồn tại. Nếu arm lỗi, partner vẫn chạy; driver giữ exit codes. Sau failure script vẫn thử oracle/scorer để có báo cáo lỗi; không xóa failed samples khỏi denominator, không resume hoặc best-of.

Ước lượng full 1545×2×30s = 25h45 agent budget, cộng smoke16, startups/preflight/model hashing và CPU evaluation. Block256 thường khoảng 7 blocks nhưng group packing có thể nhiều hơn. Tính walltime từ actual plan, không tăng sample timeout. Same allocation và GPU/MIG cho cả arm; không array chạy song song.

## Điều kiện trước full experiment

1. Assets/data/catalog/runtime/checkpoint mới dưới TMP; checkpoint fingerprint đã đối chiếu nguồn 011; venv/packages và source/helpers frozen. Không có thay đổi inventory hoặc paths trỏ về vùng cũ.
2. Tests CPU và header/preflight checks pass; memory fit được kiểm bằng **smoke GPU thực**, không suy từ CPU tests.
3. Smoke có 16 IDs, hai arm đủ accepted/terminal accounting, cùng actual inputs/schema/source/model/hardware, KV ON cả hai; ON có ít nhất một branch E thực sự được chọn. OFF không retrieve.
4. Request/tool-results/final trace không omitted/truncated/redacted; mọi step/action/result/attempt/hash binding khớp journal và published file. Sanitizer không bị tắt. Thiếu evidence thì dừng full.
5. Normal evaluation oracle có exact Gold tool-results/calls match; CPU-check references không thay thế oracle này. Oracle failures không được chuyển thành model hash mismatch hoặc bị lọc đi.
6. `reports/smoke/summary.json` có `evidence_valid=true` và đúng experiment digest. Treatment thua score **không** làm smoke audit fail; gate đo chất lượng evidence, không ép kết quả.

## Scoring và output

Trong mỗi phase, normal oracle chỉ chạy khi mọi sample ở cả hai arm đã có terminal record. Nếu run crash trước khi đủ terminal accounting, oracle gate fail; scorer vẫn xuất missing/oracle/provenance issues, không bịa Gold reference. Oracle lỗi khiến non-empty hash/score unavailable, không thành model score0. Inference failure với reference hợp lệ nhận operational score0 và hash unknown; accepted partial vẫn chấm actual output.

Tool matching: typed exact non-fuzzy arguments/key set/array order; fuzzy NFC+lowercase regex `\w+` multiset token-F1 **>0.6**. Maximum-cardinality bipartite matching; mỗi call chỉ match một lần. Ghi thêm greedy counts/F1 dưới cùng edge policy. Flag `matching_ambiguous` nghĩa maximum count khác greedy count. Đây là local policy, **official scorer compatibility chưa được xác minh**.

Với Gold non-empty: call-F1=`2M/(|P|+|G|)`; sample score bằng F1 nếu predicted hash khớp reference, ngược lại0. Gold-empty: score1 chỉ khi accepted predicted calls=[]; không áp hash gate cho special case này. `local_macro_score_100=100*sum(sample_score)/N` là aggregate nội bộ được khai báo, không gọi là official leaderboard score.

Hash success rate dùng toàn bộ Gold non-empty denominator; missing/failed prediction không có numerator nhưng được ghi hash unknown. Transition n10=OFF match→ON mismatch, n01=OFF mismatch→ON match; unknowns giữ riêng. Có observed-only rate/coverage, macro non-empty F1, observed micro-F1, signed paired latency deltas, soft deadlines/failures, known/unknown tool-call counts, branch exposure associations.

Artifacts chính:

```text
experiment.json + experiment.sha256
inputs/base_inputs.jsonl, cohorts.json, smoke/main selection blocks
configs/<phase>/<block>/<arm>.toml
evidence/inputs-before.json, integrity-*.json, <phase>-run-index.json, preflight-* logs
src/                       frozen Git archive; không chứa staged edits
harness/                   frozen helpers/tests
runs/<phase>/<block>/<arm>/ manifest, journal, staging traces, predictions[.partial].jsonl
gold/<phase>/              reference_hashes.jsonl, reference_results.jsonl, reference_audit.json
gold/cpu-check-<phase>/     riêng, không chấm điểm arm
reports/<phase>/            summary.json/md, per_sample.csv/jsonl,
                           hash_transitions.csv, branch_exposure.csv, trace_audit.json
```

Tất cả writer mở exclusive. Nếu muốn thay protocol hoặc helper, tạo TASK mới; không sửa experiment đang chạy để vượt integrity. Trace nằm theo đúng runtime 011 `staging/<attempt_id>/trace.jsonl`; failed/quarantined artifact vẫn ở run root, không bị dọn.

Exit codes: prepare 0 thành công/2 input-integrity lỗi; oracle0 tất cả reference hợp lệ/1 có oracle errors/2 guard hoặc IO lỗi; runner0 các lệnh thành công/1 inference arm nonzero/2 preflight/protocol lỗi; score0 evidence hợp lệ/1 evidence incomplete-invalid/2 guard hoặc IO lỗi. Score thấp của ON không tự làm exit nonzero. Không tự bật/tắt deployment từ report.

Giữ ON làm ứng viên khi score tăng, Gold hash success không giảm, recoveries ít nhất bằng regressions và không thêm failure/financial hoặc deadline regression chưa giải thích. Tắt làm ứng viên nếu score/hash success giảm; signal không rõ thì giữ OFF làm control và thiết kế replicate riêng. Train đã thấy/không có holdout provenance thì chưa kết luận hiệu quả generalization.
