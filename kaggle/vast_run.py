"""Run the team's fine-tuned ASR + Qwen3-4B SFT planner (the 42.5 public submission) on a rented GPU box.

    python kaggle/vast_run.py --data-root /workspace/data --lifemate-src /workspace/team/python/src
    python kaggle/vast_run.py ... --procs-per-gpu 2     # 2 planner processes per GPU (24 GB fits two fp16 copies)
    python kaggle/vast_run.py ... --limit 20            # quick timing check before the full run

Steps: download both models from the team's Google Drive (file ids from build_native_notebook.py), ASR once over
the split, run `native_infer.py` shards in parallel, merge in dataset order -> <out-dir>/submission.jsonl, and print
seconds/sample with the number of samples over 25 s and 30 s (the competition limit is 30 s/sample on one A30).
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def drive_ids():
    tree = ast.parse((HERE / "build_native_notebook.py").read_text(encoding="utf-8"))
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ("LLM_FILES", "ASR_FILES"):
                found[node.targets[0].id] = ast.literal_eval(node.value)
    return found["LLM_FILES"], found["ASR_FILES"]


def fetch(files, dest: Path):
    import gdown
    dest.mkdir(parents=True, exist_ok=True)
    for name, fid in files.items():
        out = dest / name
        for _ in range(4):
            if out.exists() and out.stat().st_size > 0:
                break
            try:
                gdown.download(id=fid, output=str(out), quiet=True)
            except Exception as exc:  # Drive quota / transient errors: retry
                print("retry", name, exc, flush=True)
        if not out.exists():
            raise SystemExit(f"không tải được {name} ({fid})")
        print(f"  {name:40s} {out.stat().st_size / 1e6:10.1f} MB", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True, help="thư mục chứa public_test/ (và train/)")
    ap.add_argument("--lifemate-src", required=True, help="python/src của nhánh codex/007-sft-full-train-no-validation")
    ap.add_argument("--split", default="public_test")
    ap.add_argument("--models-dir", default="/workspace/models")
    ap.add_argument("--out-dir", default="/workspace/out")
    ap.add_argument("--procs-per-gpu", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "gdown", "soundfile"], check=True)
    models, out = Path(args.models_dir), Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    llm_files, asr_files = drive_ids()
    llm_dir, asr_dir = models / "llm_sft", models / "asr_sft"
    print("[models] LLM", flush=True)
    fetch(llm_files, llm_dir)
    print("[models] ASR", flush=True)
    fetch(asr_files, asr_dir)
    manifest = json.load(open(asr_dir / "export-manifest.json"))["files"]
    digest = hashlib.sha256((asr_dir / "model.safetensors").read_bytes()).hexdigest()
    print("[models] ASR sha256 khớp manifest:", digest == manifest["model.safetensors"], flush=True)

    import torch
    n_gpu = max(torch.cuda.device_count(), 1)
    n = n_gpu * args.procs_per_gpu
    common = [sys.executable, str(HERE / "native_infer.py"), "--split", args.split, "--data-root", args.data_root,
              "--asr-model", str(asr_dir), "--llm-model", str(llm_dir), "--lifemate-src", args.lifemate_src,
              "--transcripts", str(out / f"tr_{args.split}.json")] + (["--limit", str(args.limit)] if args.limit else [])
    t0 = time.time()
    subprocess.run(common + ["--asr-only"], check=True, cwd=HERE)
    print(f"[asr] {time.time() - t0:.0f}s", flush=True)

    t1, procs = time.time(), []
    for i in range(n):
        env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(i % n_gpu))
        log = open(out / f"shard_{i}.log", "w", encoding="utf-8")
        procs.append(subprocess.Popen(common + ["--shard", f"{i}/{n}", "--out", str(out / f"sub_{i}.jsonl"),
                                                "--trace", str(out / f"traces_{i}.jsonl")],
                                      cwd=HERE, env=env, stdout=log, stderr=subprocess.STDOUT))
    while any(p.poll() is None for p in procs):
        time.sleep(60)
        done = sum(sum(1 for _ in open(out / f"sub_{i}.jsonl", encoding="utf-8"))
                   for i in range(n) if (out / f"sub_{i}.jsonl").exists())
        print(f"  {(time.time() - t1) / 60:.0f} phút: {done} mẫu xong", flush=True)
    print("exit codes", [p.returncode for p in procs], flush=True)

    split_file = Path(args.data_root) / args.split / f"{args.split}.jsonl"
    order = [json.loads(l)["id"] for l in open(split_file, encoding="utf-8") if l.strip()]
    rows, secs = {}, []
    for i in range(n):
        for path, sink in ((out / f"sub_{i}.jsonl", "row"), (out / f"traces_{i}.jsonl", "trace")):
            if path.exists():
                for l in open(path, encoding="utf-8"):
                    r = json.loads(l)
                    if sink == "row":
                        rows[r["id"]] = r
                    else:
                        secs.append(r.get("seconds", 0.0))
    missing = [i for i in order if i not in rows]
    with open(out / "submission.jsonl", "w", encoding="utf-8") as f:
        for i in order:
            if i in rows:
                f.write(json.dumps(rows[i], ensure_ascii=False) + "\n")
    print(f"[merge] {len(rows)}/{len(order)} dòng -> {out / 'submission.jsonl'} (thiếu {len(missing)})", flush=True)
    if secs:
        secs.sort()
        print(f"[time] {n} tiến trình trên {n_gpu} GPU | tổng {(time.time() - t1) / 60:.1f} phút | "
              f"s/mẫu TB {sum(secs) / len(secs):.1f}, p50 {secs[len(secs) // 2]:.1f}, max {secs[-1]:.1f} | "
              f">25s: {sum(s > 25 for s in secs)}, >30s: {sum(s > 30 for s in secs)}", flush=True)
        if args.procs_per_gpu > 1:
            print("[time] chú ý: chạy nhiều tiến trình trên một GPU làm s/mẫu của từng mẫu chậm hơn; đo giới hạn 30 s "
                  "bằng --procs-per-gpu 1", flush=True)


if __name__ == "__main__":
    main()
