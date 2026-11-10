"""Build the Kaggle notebook that runs the v2 pipeline (zaic ASR + prompt v2) with empero-ai/Qwen3.8-4B-Distill.

    python kaggle/build_qwen38_notebook.py     # -> kaggle/push_q38/lifemate-qwen38.ipynb + kernel-metadata.json

empero-ai/Qwen3.8-4B-Distill (Apache-2.0, published 2026-08-15) is the safetensors source of the GGUF repo
empero-ai/Qwen3.8-4B-Distill-GGUF: same weights, Qwen3.5-4B architecture, which lifemate_infer.py already loads
(Kaggle v4 ran Qwen/Qwen3.5-4B). Reference on the same 200 ASR train samples (v4): Qwen3-4B v2 0.4499,
Qwen3.5-4B 0.4523. Public: v2 34.66.
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

SMOKE = r'''Q38 = "empero-ai/Qwen3.8-4B-Distill"
!python lifemate_infer.py --split public_test --limit 5 --prompt-file system_prompt.txt --llm-model {Q38} --out smoke.jsonl --trace smoke_traces.jsonl
import json
_smoke = [json.loads(l) for l in open('smoke.jsonl', encoding='utf-8')]
_n = sum(len(r['tool_calls']) for r in _smoke)
print('smoke:', len(_smoke), 'mẫu,', _n, 'tool call')
for r in _smoke: print(r['id'], [c['name'] for c in r['tool_calls']])
for l in open('smoke_traces.jsonl', encoding='utf-8'):
    t = json.loads(l)
    for st in t['steps'][:2]:
        print(t['id'], 'raw:', repr(st.get('raw', '')[:300]))
assert _n > 0, 'Smoke test không ra tool call nào -> dừng (xem smoke_traces.jsonl)'
'''

CMP = r'''# 2) So sánh trên 200 mẫu train (transcript ASR zaic): Qwen3.8 không nghĩ vs nghĩ tối đa 384 token
# Mốc cùng 200 mẫu (Kaggle v4): Qwen3-4B v2 = 0.4499 (24.5 s/mẫu), Qwen3.5-4B = 0.4523 (37.3 s/mẫu)
import json, os, subprocess, sys, torch
N_EVAL, MAX_SEC = 200, 75          # MAX_SEC: s/mẫu tối đa trên T4
REF = {"qwen3_v2 (v4)": 0.4499, "qwen3.5 (v4)": 0.4523}
subprocess.run([sys.executable, "lifemate_infer.py", "--split", "train", "--limit", str(N_EVAL), "--prepare-only",
                "--prompt-file", "system_prompt.txt", "--llm-model", Q38], check=True)
TB = ["--llm-model", Q38, "--time-budget", "150"]
CONFIGS = {"q38": TB, "q38_think": TB + ["--think-budget", "384"]}
QUEUES = [["q38"], ["q38_think"]]
LIMIT_SEC = {"q38": 4 * 3600, "q38_think": 4 * 3600}
if max(torch.cuda.device_count(), 1) == 1:
    QUEUES = [sum(QUEUES, [])]
def cmd(n):
    c = " ".join([sys.executable, "lifemate_infer.py", "--split", "train", "--limit", str(N_EVAL), "--eval",
                  "--prompt-file", "system_prompt.txt", "--out", f"exp_{n}.jsonl", "--trace", f"exp_{n}_traces.jsonl"]
                 + CONFIGS[n]) + f" > exp_{n}.log 2>&1"
    return f"timeout {LIMIT_SEC[n]} {c}"
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
results = {}
for n in CONFIGS:
    if per[n]:
        sc = [v[0] for v in per[n].values()]
        sec = [v[1] for v in per[n].values()]
        results[n] = (sum(sc) / len(sc), sum(sec) / len(sec))
        print(f"{n:10s} n={len(per[n]):3d}  score={results[n][0]:.4f}  {results[n][1]:.1f}s/mẫu  >30s: {sum(s > 30 for s in sec)}", flush=True)
for k, v in REF.items():
    print(f"{k:16s} score={v:.4f}")
ok = {n: r for n, r in results.items() if r[1] <= MAX_SEC and len(per[n]) >= N_EVAL // 2} or results
BEST = max(ok, key=lambda n: (ok[n][0], -ok[n][1]))
BEST_FLAGS = CONFIGS[BEST]
print("BEST =", BEST, BEST_FLAGS)
'''

DIAG = r'''# Chẩn đoán: 20 mẫu điểm < 1 đầu tiên của mỗi cấu hình
import json, os
for n in CONFIGS:
    path = f"exp_{n}_traces.jsonl"
    if not os.path.exists(path):
        continue
    bad = [t for t in (json.loads(l) for l in open(path, encoding="utf-8")) if t.get("score", 1) < 1][:20]
    for t in bad:
        print("=" * 100)
        print(f"[{n}] {t['id']} score={t.get('score')} stop={t.get('stop')} {t.get('seconds')}s")
        print("  REQ :", t.get("request", "")[:200].replace("\n", " "))
        print("  GOLD:", [c["name"] + json.dumps(c.get("arguments") or {}, ensure_ascii=False)[:120] for c in t.get("gold", [])])
        print("  PRED:", [c["name"] + json.dumps(c.get("arguments") or {}, ensure_ascii=False)[:120] for c in t.get("tool_calls", [])])
        if t.get("steps"):
            print("  RAW0:", repr(t["steps"][0].get("raw", "")[:300]))
'''

cells[find("!python lifemate_infer.py --split public_test --limit 5")] = code(SMOKE)
cmp_i = find("# So sánh cấu hình LLM")
cells[cmp_i] = code(CMP)
cells[find("import json, sys\nsys.path.insert(0, \".\")\nimport lifemate_infer as L\nroot = L.find_data_root(\"train\"")] = code(DIAG)

cells[0] = md("# LifeMate: ASR (zaic Whisper) + Qwen3.8-4B-Distill trên Kaggle\n\n"
              "LLM: `empero-ai/Qwen3.8-4B-Distill` (Apache-2.0, phát hành 15/08/2026, kiến trúc Qwen3.5-4B; bản safetensors "
              "của repo GGUF `empero-ai/Qwen3.8-4B-Distill-GGUF`). Pipeline và prompt giống v2 (public 34.66).\n\n"
              "1. Smoke 5 mẫu public.\n2. So sánh trên 200 mẫu train (transcript ASR): không nghĩ vs nghĩ tối đa 384 token; "
              "mốc cùng 200 mẫu: Qwen3-4B 0.4499, Qwen3.5-4B 0.4523.\n3. Cấu hình tốt hơn (≤ 75 s/mẫu trên T4) chạy toàn bộ public_test.\n\n"
              "Settings: **GPU T4 x2**, **Internet On**.")

out = HERE / "push_q38"
out.mkdir(exist_ok=True)
json.dump(dict(src, cells=cells), open(out / "lifemate-qwen38.ipynb", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
meta = {"id": "hiunguyn1703/lifemate-qwen38", "title": "lifemate-qwen38",
        "code_file": "lifemate-qwen38.ipynb", "language": "python", "kernel_type": "notebook",
        "is_private": True, "enable_gpu": True, "enable_tpu": False, "enable_internet": True, "keywords": ["gpu"],
        "dataset_sources": ["hiunguyn1703/lifemate-asr-zaic", "hiunguyn1703/lifemate-full-data"],
        "kernel_sources": [], "competition_sources": [], "model_sources": []}
json.dump(meta, open(out / "kernel-metadata.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("notebook ->", out)
