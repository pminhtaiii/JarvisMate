"""Kaggle notebook: the team's fine-tuned ASR (PhoWhisper-large LoRA, merged fp16) + Qwen3-4B SFT planner.

    python kaggle/build_native_notebook.py     # -> kaggle/push_native/{lifemate-native-sft.ipynb, kernel-metadata.json}

Models come from the team's Google Drive folder (gdown). Planner prompts are rendered by the team's own
`lifemate.adapters.qwen_native` (dataset hiunguyn1703/lifemate-team-src), so inference matches the SFT format.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def code(text):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": text.splitlines(keepends=True)}


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


LLM_FILES = {  # Drive folder LLM_finetuned/merged_fp16
    "config.json": "1MQda0GgW2HPcUrmsz2tGz3q1VHjWDI5L",
    "generation_config.json": "18pijti4LFKXuTSBC8MHUJX0yQZBd7ZXd",
    "merges.txt": "1kHc4hWoUhF2_S9_eaesdfHfxhWtKCXEQ",
    "model-00001-of-00002.safetensors": "137IsRkhZz_tnpb1jmfrYS_1PKIiLx1WH",
    "model-00002-of-00002.safetensors": "1DsXr7ldXKx1HE0GLYmhUjAfHJNiCHYFM",
    "model.safetensors.index.json": "1vaZb7pjaAwmma1h8jsdIc-3cAG1MapYD",
    "tokenizer.json": "1QYcKLhiNB1jb3j5LYI-HkBUTUuksmW78",
    "tokenizer_config.json": "1Cc0JxU6mkoungBV2KaaPFvwj5Ph5F67z",
    "vocab.json": "1mqCRirf4xCTU9KauI6edQ3dSF_2jKzPs",
}
ASR_FILES = {  # Drive folder ASR/checkpoint_finetune/merged-fp16
    "added_tokens.json": "1afGBAMM2B6oz5kieTamL68l1ZVUGpn7O",
    "config.json": "1f5ukI53dvKdByOczRk1UG0sDWoweriO8",
    "export-manifest.json": "1fpHte-vJv4Goc4c_FqIiBX7VwWpjO4fp",
    "generation_config.json": "1bX9CNkx2BdwjaNfCc3e9BbNlkohYT9ir",
    "merges.txt": "193VWbFztY9-pFAleHVLzbTazKwzACLUU",
    "model.safetensors": "1g5bwHVI_hv3BL2-2PzD4L9ZjRnQmkjHk",
    "normalizer.json": "1l7RiPwjRQL0NEkImSV0GknsT_3LwqxUJ",
    "preprocessor_config.json": "12otKimtMWuZpsapprE-Key48P3sh8acv",
    "special_tokens_map.json": "1Qcq6LC0yowg9UbGhtcgGGlinl62MKwjb",
    "tokenizer.json": "1E4PCsJT683UmU5VpIp0SVegmNbj-d3Ci",
    "tokenizer_config.json": "1MCYym1z4bvge92kkwZR1RSyTBT7ShtsV",
    "vocab.json": "19NxWQPzmcIQ7EOGg6NOk6VIw1nTvqkhs",
}

SETUP = r'''# 1) Tải 2 mô hình fine-tune từ Google Drive, tìm source lifemate của nhóm và dữ liệu
import subprocess, sys, json, hashlib, os, glob
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "gdown"], check=True)
import gdown
LLM_FILES = %s
ASR_FILES = %s
def fetch(files, dest):
    os.makedirs(dest, exist_ok=True)
    for name, fid in files.items():
        out = os.path.join(dest, name)
        for attempt in range(4):
            if os.path.exists(out) and os.path.getsize(out) > 0:
                break
            try:
                gdown.download(id=fid, output=out, quiet=True)
            except Exception as exc:
                print("retry", name, exc)
        print(f"{name:40s} {os.path.getsize(out) / 1e6:10.1f} MB")
fetch(LLM_FILES, "/tmp/llm_sft")
fetch(ASR_FILES, "/tmp/asr_sft")
man = json.load(open("/tmp/asr_sft/export-manifest.json"))["files"]
h = hashlib.sha256(open("/tmp/asr_sft/model.safetensors", "rb").read()).hexdigest()
print("ASR sha256 khớp manifest:", h == man["model.safetensors"])
def walk(base, depth=7):
    for d, subs, files in os.walk(base, followlinks=True):
        if d[len(base):].count(os.sep) >= depth:
            subs[:] = []
        subs[:] = [s for s in subs if s != "audio" and not s.endswith("_environment")]
        yield d, files
ZAIC = None
for d, files in walk("/kaggle/input"):
    if "preprocessor_config.json" in files and "config.json" in files:
        if json.load(open(os.path.join(d, "config.json"))).get("model_type") == "whisper":
            ZAIC = d
            break
print("ASR cũ (zaic):", ZAIC)
print("input:", sorted(os.listdir("/kaggle/input")))
!nvidia-smi --query-gpu=name,memory.total --format=csv
''' % (json.dumps(LLM_FILES, indent=1), json.dumps(ASR_FILES, indent=1))

ASR_CMP = r'''# 2) ASR: mô hình mới (GPU0) và zaic cũ (GPU1) trên toàn bộ public_test + 200 mẫu train
#    Train chỉ để tham khảo: ASR mới đã được train trên toàn bộ train nên WER train của nó bị lạc quan.
import subprocess, sys, os
def asr(model, split, cache, gpu, limit=0):
    c = [sys.executable, "native_infer.py", "--split", split, "--asr-model", model, "--llm-model", "/tmp/llm_sft",
         "--lifemate-src", SRC, "--transcripts", cache, "--asr-only"] + (["--limit", str(limit)] if limit else [])
    return f"{' '.join(c)} > {cache}.log 2>&1"
q0 = "; ".join([asr("/tmp/asr_sft", "public_test", "tr_new_public.json", 0), asr("/tmp/asr_sft", "train", "tr_new_train.json", 0, 200)])
q1 = "; ".join([asr(ZAIC, "public_test", "tr_old_public.json", 1), asr(ZAIC, "train", "tr_old_train.json", 1, 200)])
import torch
NG = max(torch.cuda.device_count(), 1)
print("GPU:", NG)
queues = [q0, q1] if NG > 1 else [q0 + "; " + q1]
ps = [subprocess.Popen(q, shell=True, env=dict(os.environ, CUDA_VISIBLE_DEVICES=str(g))) for g, q in enumerate(queues)]
[p.wait() for p in ps]
for f in ["tr_new_public.json", "tr_new_train.json", "tr_old_public.json", "tr_old_train.json"]:
    print(f, open(f + ".log").read()[-600:])
'''

ASR_REPORT = r'''# ASR: WER trên 200 mẫu train (so với audio_text) và mức khác nhau trên public
import json, sys, unicodedata, re
sys.path.insert(0, ".")
import lifemate_infer as L
def words(s):
    s = unicodedata.normalize("NFC", s.lower())
    return re.sub(r"[^\w\s]", " ", s).split()
def wer(ref, hyp):
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)], len(r)
root = L.find_data_root("train", None)
tr = [json.loads(l) for l in open(root / "train" / "train.jsonl", encoding="utf-8")][:200]
ref = {}
for it in tr:
    ref[it["audio"]] = it["audio_text"]
    for t in it.get("history", []):
        if t.get("role") == "user":
            ref[t["audio"]] = t["audio_text"]
import os
for name in ("old", "new"):
    if not os.path.exists(f"tr_{name}_train.json"):
        print("thiếu", name); continue
    tx = json.load(open(f"tr_{name}_train.json", encoding="utf-8"))
    e = n = 0
    for a, r in ref.items():
        x, y = wer(r, tx.get(a, ""))
        e, n = e + x, n + y
    print(f"WER train200 {name}: {100 * e / n:.2f}%")
po = json.load(open("tr_old_public.json", encoding="utf-8")) if os.path.exists("tr_old_public.json") else {}
pn = json.load(open("tr_new_public.json", encoding="utf-8"))
diff = [a for a in pn if words(pn[a]) != words(po.get(a, ""))]
print(f"public: {len(diff)}/{len(pn)} clip khác nhau giữa ASR cũ và mới")
for a in diff[:40]:
    print("  cũ :", po.get(a, "")[:160]); print("  mới:", pn[a][:160])
'''

SMOKE = r'''# 3) Thử nhanh: 4 mẫu train (transcript gốc) + 4 mẫu public, xem model ra đúng định dạng
!python native_infer.py --split train --limit 4 --gold-transcript --eval --asr-model /tmp/asr_sft --llm-model /tmp/llm_sft --lifemate-src {SRC} --transcripts tr_new_train.json --out smoke_train.jsonl --trace smoke_train_traces.jsonl
!python native_infer.py --split public_test --limit 4 --asr-model /tmp/asr_sft --llm-model /tmp/llm_sft --lifemate-src {SRC} --transcripts tr_new_public.json --out smoke.jsonl --trace smoke_traces.jsonl
for l in open("smoke_traces.jsonl", encoding="utf-8"):
    t = json.loads(l); print(t["id"], t["stop"], [s["out"][:200] for s in t["steps"]])
'''

RUN = r'''# 4) Chạy chính, mỗi GPU một shard:
#    a) public_test, ASR mới + LLM mới            -> submission.jsonl (bản nộp)
#    b) 200 mẫu train, ASR mới + LLM mới, chấm điểm (bị lạc quan: cả hai mô hình đã thấy train)
#    c) public_test, ASR cũ (zaic) + LLM mới      -> submission_oldasr.jsonl (tách tác dụng của ASR)
import subprocess, sys, os, time
def job(tag, split, tr, gpu, extra=()):
    c = [sys.executable, "native_infer.py", "--split", split, "--asr-model", "/tmp/asr_sft", "--llm-model", "/tmp/llm_sft",
         "--lifemate-src", SRC, "--transcripts", tr, "--shard", f"{gpu}/2", "--out", f"{tag}_{gpu}.jsonl",
         "--trace", f"{tag}_traces_{gpu}.jsonl"] + list(extra)
    return f"{' '.join(c)} > {tag}_{gpu}.log 2>&1"
# one GPU: both shards run one after the other on GPU0
t0 = time.time()
ps = []
for g in (0, 1):
    q = "; ".join([job("pub", "public_test", "tr_new_public.json", g),
                   job("tr", "train", "tr_new_train.json", g, ["--limit", "200", "--eval"]),
                   job("pubold", "public_test", "tr_old_public.json", g)])
    ps.append(subprocess.Popen(q, shell=True, env=dict(os.environ, CUDA_VISIBLE_DEVICES=str(g if NG > 1 else 0))))
    if NG == 1:
        ps[-1].wait()
[p.wait() for p in ps]
print(f"xong sau {(time.time() - t0) / 60:.0f} phút")
for f in sorted(os.listdir(".")):
    if f.endswith(".log") and f[:3] in ("pub", "tr_"):
        print(f, open(f, encoding="utf-8").read()[-300:])
'''

MERGE = r'''# 5) Ghép shard, kiểm tra, thống kê
import json, collections
def merge(tag, out):
    rows, traces = {}, []
    for g in (0, 1):
        try:
            rows.update({json.loads(l)["id"]: l for l in open(f"{tag}_{g}.jsonl", encoding="utf-8")})
            traces += [json.loads(l) for l in open(f"{tag}_traces_{g}.jsonl", encoding="utf-8")]
        except FileNotFoundError:
            print("thiếu", tag, g)
    return rows, traces
pub_ids = [json.loads(l)["id"] for l in open(str(L.find_data_root("public_test", None) / "public_test" / "public_test.jsonl"), encoding="utf-8")]
for tag, out in (("pub", "submission.jsonl"), ("pubold", "submission_oldasr.jsonl"), ("tr", "train200.jsonl")):
    rows, traces = merge(tag, out)
    if tag.startswith("pub"):
        miss = [i for i in pub_ids if i not in rows]
        print(tag, "thiếu id:", len(miss))
        with open(out, "w", encoding="utf-8") as f:
            for i in pub_ids:
                f.write(rows[i] if i in rows else json.dumps({"id": i, "tool_calls": [], "state_hash": ""}) + "\n")
    stops = collections.Counter(t["stop"].split(":")[0] for t in traces)
    secs = sum(t["seconds"] for t in traces) / max(len(traces), 1)
    sc = [t["score"] for t in traces if "score" in t]
    print(f"{tag}: n={len(traces)} stop={dict(stops)} {secs:.1f}s/mẫu" + (f" score={sum(sc) / len(sc):.4f}" if sc else ""))
    fmt = [t for t in traces if t["stop"] in ("format",) or t["stop"].startswith("error")][:8]
    for t in fmt:
        print("   ", t["id"], t["stop"], [s["out"][:200] for s in t["steps"]][-1:])
a = {json.loads(l)["id"]: json.loads(l) for l in open("submission.jsonl", encoding="utf-8")}
b = {json.loads(l)["id"]: json.loads(l) for l in open("submission_oldasr.jsonl", encoding="utf-8")}
print("public: ASR mới vs cũ khác state_hash ở", sum(a[i]["state_hash"] != b[i]["state_hash"] for i in a), "mẫu")
'''

# The team's lifemate package (stdlib only, ~100 KB) embedded so no extra dataset is needed.
import base64, io, tarfile
_buf = io.BytesIO()
with tarfile.open(fileobj=_buf, mode="w:gz") as _tar:
    _tar.add(HERE / "push_src" / "lifemate", arcname="lifemate",
             filter=lambda t: None if "__pycache__" in t.name else t)
SRC_CELL = ("# Source lifemate của nhóm (commit " + (HERE / "push_src" / "lifemate" / "COMMIT").read_text().strip()
            + "), nhúng sẵn\nimport base64, io, tarfile\nSRC = '/tmp/lifemate_src'\n"
            + "tarfile.open(fileobj=io.BytesIO(base64.b64decode('" + base64.b64encode(_buf.getvalue()).decode()
            + "')), mode='r:gz').extractall(SRC)\nprint('lifemate src:', SRC)\n")

cells = [
    md("# LifeMate: ASR + LLM fine-tune của nhóm\n\n"
       "- ASR: PhoWhisper-large + LoRA (merged fp16)\n- LLM: Qwen3-4B SFT, giao thức `qwen-native-v1` "
       "(prompt render bằng chính code `lifemate` của nhóm)\n\n"
       "Bản nộp: `submission.jsonl` (ASR mới + LLM mới). `submission_oldasr.jsonl` dùng ASR zaic cũ để tách tác dụng."),
    code(SETUP),
    code(SRC_CELL),
    code("%%writefile lifemate_infer.py\n" + (HERE / "lifemate_infer.py").read_text(encoding="utf-8")),
    code("%%writefile native_infer.py\n" + (HERE / "native_infer.py").read_text(encoding="utf-8")),
    code(ASR_CMP),
    code(ASR_REPORT),
    code(SMOKE),
    code(RUN),
    code(MERGE),
]
nb = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                   "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
out = HERE / "push_native"
out.mkdir(exist_ok=True)
json.dump(nb, open(out / "lifemate-native-sft.ipynb", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
meta = {"id": "hiunguyn1703/lifemate-native-sft", "title": "lifemate-native-sft",
        "code_file": "lifemate-native-sft.ipynb", "language": "python", "kernel_type": "notebook",
        "is_private": True, "enable_gpu": True, "enable_tpu": False, "enable_internet": True, "keywords": ["gpu"],
        "dataset_sources": ["hiunguyn1703/lifemate-asr-zaic", "hiunguyn1703/lifemate-full-data"],
        "kernel_sources": [], "competition_sources": [], "model_sources": []}
json.dump(meta, open(out / "kernel-metadata.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("notebook ->", out)
