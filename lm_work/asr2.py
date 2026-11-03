"""ASR improvements for public_test final-request clips.

  python asr2.py nbest            -> asr_nbest.json   {audio: {"greedy": str, "nbest": [[text, score], ...]}}
  python asr2.py pass2            -> asr_pass2.json   {audio: {"vocab": [...], "text": str}}

pass2 decodes again with Whisper prompt_ids built from entity names returned by the READ tool calls recorded
for that sample in calls/ (names the agent legitimately obtained through tools; state.json is never read).
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from transformers import WhisperForConditionalGeneration, WhisperProcessor

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent / "data_unz" / "train+public_test" / "public_test"
MODEL = HERE / "asr_model" / "zaic"
DEV = "cuda:0"
torch.manual_seed(0)

proc = WhisperProcessor.from_pretrained(MODEL)
model = WhisperForConditionalGeneration.from_pretrained(MODEL, torch_dtype=torch.float16).to(DEV).eval()
items = [json.loads(l) for l in open(ROOT / "public_test.jsonl", encoding="utf-8") if l.strip()]


def wav(p):
    a, sr = sf.read(str(ROOT / p), dtype="float32", always_2d=False)
    if a.ndim > 1:
        a = a.mean(axis=1)
    if sr != 16000:
        n = int(len(a) * 16000 / sr)
        a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)
    return a[:480000]


def feats(a):
    return proc(a, sampling_rate=16000, return_tensors="pt").input_features.to(DEV, torch.float16)


def decode(ids):
    return proc.batch_decode(ids, skip_special_tokens=True)


NAME_KEYS = {"name", "title", "display_name", "label", "contact_name", "chat_name", "restaurant", "product", "symbol",
             "station", "place", "location", "artist", "track", "program", "provider", "merchant", "beneficiary_name"}


def harvest(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and (k in NAME_KEYS or k.endswith("_name")) and 1 < len(v) <= 60:
                out.append(v)
            else:
                harvest(v, out)
    elif isinstance(obj, list):
        for v in obj:
            harvest(v, out)


def vocab_for(i):
    sys.path.insert(0, str(ROOT))
    from zaic_tools import ToolEnv
    p = HERE / "calls" / f"{i}.json"
    if not p.is_file():
        return []
    calls = json.load(open(p, encoding="utf-8"))["calls"]
    env = ToolEnv("public_test", i, root=str(ROOT.parent))
    names = []
    for c in calls:
        r = env.call(c["name"], c["arguments"])
        if env.kind(c["name"]) == "read":
            harvest(r, names)
    seen, out = set(), []
    for n in names:
        if n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out[:40]


def run_nbest():
    out = {}
    for k, it in enumerate(items):
        f = feats(wav(it["audio"]))
        with torch.inference_mode():
            g = model.generate(f, language="vi", task="transcribe", do_sample=False, num_beams=1, max_new_tokens=220)
            b = model.generate(f, language="vi", task="transcribe", do_sample=False, num_beams=5, num_return_sequences=5,
                               max_new_tokens=220, output_scores=True, return_dict_in_generate=True)
        texts = decode(b.sequences)
        scores = b.sequences_scores.float().cpu().tolist()
        out[it["audio"]] = {"greedy": decode(g)[0].strip(), "nbest": [[t.strip(), round(s, 4)] for t, s in zip(texts, scores)]}
        if k % 50 == 0:
            print(k, out[it["audio"]]["greedy"], flush=True)
            json.dump(out, open(HERE / "asr_nbest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    json.dump(out, open(HERE / "asr_nbest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)


def run_pass2():
    out = {}
    for k, it in enumerate(items):
        vocab = vocab_for(it["id"])
        if not vocab:
            continue
        prompt = ", ".join(vocab)
        pids = torch.tensor(proc.get_prompt_ids(prompt), device=DEV)
        if len(pids) > 200:
            pids = pids[:200]
        f = feats(wav(it["audio"]))
        with torch.inference_mode():
            ids = model.generate(f, language="vi", task="transcribe", do_sample=False, num_beams=5, max_new_tokens=220,
                                 prompt_ids=pids)
        text = proc.decode(ids[0], skip_special_tokens=True).strip()
        # generate() returns the prompt too on some versions; strip it
        if text.startswith(prompt):
            text = text[len(prompt):].strip()
        out[it["audio"]] = {"vocab": vocab, "text": text}
        if k % 50 == 0:
            print(k, text, flush=True)
            json.dump(out, open(HERE / "asr_pass2.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    json.dump(out, open(HERE / "asr_pass2.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)


if __name__ == "__main__":
    {"nbest": run_nbest, "pass2": run_pass2}[sys.argv[1]]()
