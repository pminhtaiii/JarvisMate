"""Build the Kaggle notebook from lifemate_infer.py + system_prompt.txt, starting from the v1 notebook layout.

    python kaggle/build_notebook.py            # -> kaggle/push/lifemate-funreason-asr.ipynb + kernel-metadata.json

v4 comparison (after public: v1 23.00, v2 34.66, v3 33.99): v2 baseline vs v2 + plan hint vs Qwen3.5-4B, on 200 train
samples WITH the ASR transcripts, scored per sample and compared on the ids every config finished.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
src = json.load(open(HERE / "lifemate_kaggle.ipynb", encoding="utf-8"))
cells = src["cells"]


def code(text):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": text.splitlines(keepends=True)}


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def find(prefix):
    for i, c in enumerate(cells):
        if "".join(c["source"]).lstrip().startswith(prefix):
            return i
    raise SystemExit(f"cell not found: {prefix}")


cells[find("%%writefile system_prompt.txt")] = code("%%writefile system_prompt.txt\n" + (HERE / "system_prompt.txt").read_text(encoding="utf-8"))
cells[find("%%writefile lifemate_infer.py")] = code("%%writefile lifemate_infer.py\n" + (HERE / "lifemate_infer.py").read_text(encoding="utf-8"))

PREP = r'''# 2a) Chuẩn bị: ASR (+ N-best) cho N_EVAL mẫu train một lần, tải sẵn cả hai LLM
import subprocess, sys
N_EVAL, MAX_SEC = 200, 75          # MAX_SEC: s/mẫu tối đa trên T4
Q35 = "Qwen/Qwen3.5-4B"
base_prep = [sys.executable, "lifemate_infer.py", "--split", "train", "--limit", str(N_EVAL), "--prepare-only",
             "--prompt-file", "system_prompt.txt"]
subprocess.run(base_prep, check=True)
r = subprocess.run(base_prep + ["--llm-model", Q35], capture_output=True, text=True)
print(r.stdout[-1500:], r.stderr[-1500:])
Q35_OK = r.returncode == 0
print("Qwen3.5 tải được:", Q35_OK)
'''

PLAN = r'''# 2b) Kế hoạch gợi ý: mẫu train giống nhất (bỏ chính nó) có cùng chuỗi tool với gold không, theo độ giống
import json, collections, sys
sys.path.insert(0, ".")
import lifemate_infer as L
root = L.find_data_root("train", None)
tr = [json.loads(l) for l in open(root / "train" / "train.jsonl", encoding="utf-8") if l.strip()]
idx = L.FewShotIndex(tr)
seq = lambda it: [c["name"] for c in it["label"]["tool_calls"]]
bins = collections.defaultdict(lambda: [0, 0])
for it in tr:
    top = idx.top_scored(it["audio_text"], set(it["context"]["installed_apps"]), 1, skip_id=it["id"])
    if top:
        b = min(int(top[0][0] * 20), 19) / 20
        bins[b][0] += 1
        bins[b][1] += seq(top[0][1]) == seq(it)
print("độ giống  n   cùng chuỗi tool%")
for b in sorted(bins):
    print(f"  {b:.2f}  {bins[b][0]:4d}  {100 * bins[b][1] / bins[b][0]:5.1f}")
# smallest threshold above which the plan is right at least 75% of the time
PLAN_SIM = 0.9
for b in sorted(bins):
    n = sum(bins[x][0] for x in bins if x >= b)
    ok = sum(bins[x][1] for x in bins if x >= b)
    if n and ok / n >= 0.75:
        PLAN_SIM = b
        break
print("PLAN_SIM =", PLAN_SIM)
'''

CMP = r'''# 2c) So sánh cấu hình trên N_EVAL mẫu train (transcript ASR), mỗi GPU một hàng đợi; chấm từng mẫu, so trên id chung
import json, os, subprocess, sys, time, torch
TB = ["--time-budget", "150"]
CONFIGS = {"v2": TB, "v2_plan": ["--plan-sim", str(PLAN_SIM)] + TB}
if Q35_OK:
    CONFIGS["q35"] = ["--llm-model", Q35] + TB
QUEUES = [["v2", "v2_plan"], ["q35"] if Q35_OK else []]
LIMIT_SEC = {"q35": 3 * 3600}       # Qwen3.5 re-prefills every step (no KV reuse): cap its wall time
n_gpu = max(torch.cuda.device_count(), 1)
if n_gpu == 1:
    QUEUES = [sum(QUEUES, [])]
def cmd(n):
    c = " ".join([sys.executable, "lifemate_infer.py", "--split", "train", "--limit", str(N_EVAL), "--eval",
                  "--prompt-file", "system_prompt.txt", "--out", f"exp_{n}.jsonl", "--trace", f"exp_{n}_traces.jsonl"]
                 + CONFIGS[n]) + f" > exp_{n}.log 2>&1"
    return f"timeout {LIMIT_SEC[n]} {c}" if n in LIMIT_SEC else c
procs = [subprocess.Popen("; ".join(cmd(n) for n in q), shell=True, env=dict(os.environ, CUDA_VISIBLE_DEVICES=str(g)))
         for g, q in enumerate(QUEUES) if q]
for p in procs:
    p.wait()
per = {}
for n in CONFIGS:
    rows = [json.loads(l) for l in open(f"exp_{n}_traces.jsonl", encoding="utf-8")] if os.path.exists(f"exp_{n}_traces.jsonl") else []
    per[n] = {r["id"]: (r.get("score", 0.0), r.get("seconds", 0.0)) for r in rows}
    if not rows:
        print(n, "không có kết quả:"); print(open(f"exp_{n}.log", encoding="utf-8").read()[-2000:] if os.path.exists(f"exp_{n}.log") else "")
done = [n for n in CONFIGS if len(per[n]) >= N_EVAL // 2]
common = set.intersection(*(set(per[n]) for n in done)) if done else set()
results = {}
for n in done:
    sc = [per[n][i][0] for i in common]
    sec = [per[n][i][1] for i in per[n]]
    results[n] = (sum(sc) / max(len(sc), 1), sum(sec) / max(len(sec), 1))
    print(f"{n:10s} n={len(per[n]):3d}  score(chung {len(common)})={results[n][0]:.4f}  {results[n][1]:.1f}s/mẫu", flush=True)
if "v2" in results:
    for n in results:
        if n != "v2":
            d = [per[n][i][0] - per["v2"][i][0] for i in common]
            print(f"  {n} - v2: {sum(d) / len(d):+.4f}  (hơn {sum(x > 0 for x in d)}, kém {sum(x < 0 for x in d)})")
ok = {n: r for n, r in results.items() if r[1] <= MAX_SEC} or results
BEST = max(ok, key=lambda n: (ok[n][0], -ok[n][1]))
BEST_FLAGS = CONFIGS[BEST]
print("BEST =", BEST, BEST_FLAGS)
'''

DIAG = r'''# Chẩn đoán: 25 mẫu điểm < 1 đầu tiên của mỗi cấu hình (dự đoán so với nhãn)
import json, os
for n in CONFIGS:
    path = f"exp_{n}_traces.jsonl"
    if not os.path.exists(path):
        continue
    bad = [json.loads(l) for l in open(path, encoding="utf-8")]
    bad = [t for t in bad if t.get("score", 1) < 1][:25]
    for t in bad:
        print("=" * 100)
        print(f"[{n}] {t['id']} score={t.get('score')} stop={t.get('stop')} plan={t.get('plan_sim')} {t.get('seconds')}s")
        print("  REQ :", t.get("request", "")[:200].replace("\n", " "))
        print("  GOLD:", [c["name"] + json.dumps(c.get("arguments") or {}, ensure_ascii=False)[:120] for c in t.get("gold", [])])
        print("  PRED:", [c["name"] + json.dumps(c.get("arguments") or {}, ensure_ascii=False)[:120] for c in t.get("tool_calls", [])])
'''

cmp_i = find("# So sánh cấu hình LLM")
cells[cmp_i:cmp_i + 1] = [code(PREP), code(PLAN), code(CMP)]
cells[find("import json, sys\nsys.path.insert(0, \".\")\nimport lifemate_infer as L\nroot = L.find_data_root(\"train\"")] = code(DIAG)

cells[0] = md("# LifeMate v4: ASR (zaic Whisper) + LLM trên Kaggle\n\n"
              "Điểm public: v1 23.00, v2 34.66, v3 33.99. v4 lấy v2 làm gốc (prompt v2, tính năng v3 tắt) và so trên 200 mẫu "
              "train dùng transcript ASR:\n"
              "- `v2`: bản 34.66\n- `v2_plan`: thêm kế hoạch gợi ý (chuỗi tool của mẫu train gần như giống hệt), ngưỡng độ "
              "giống tự chọn ở bước 2b\n- `q35`: Qwen3.5-4B (Apache-2.0, 4.66B tham số kể cả phần ảnh, phát hành 27/02/2026)\n\n"
              "Cấu hình điểm cao nhất (≤ 75 s/mẫu trên T4) chạy toàn bộ public_test.")

out = HERE / "push"
out.mkdir(exist_ok=True)
json.dump(dict(src, cells=cells), open(out / "lifemate-funreason-asr.ipynb", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
meta = {"id": "hiunguyn1703/lifemate-funreason-asr", "title": "lifemate-funreason-asr",
        "code_file": "lifemate-funreason-asr.ipynb", "language": "python", "kernel_type": "notebook",
        "is_private": True, "enable_gpu": True, "enable_tpu": False, "enable_internet": True, "keywords": ["gpu"],
        "dataset_sources": ["hiunguyn1703/lifemate-asr-zaic", "hiunguyn1703/lifemate-full-data"],
        "kernel_sources": [], "competition_sources": [], "model_sources": []}
json.dump(meta, open(out / "kernel-metadata.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("notebook ->", out)
