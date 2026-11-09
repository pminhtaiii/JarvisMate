"""LifeMate inference with the team's fine-tuned models: PhoWhisper-large LoRA (merged) ASR + Qwen3-4B SFT planner.

The planner was trained on the team's `qwen-native-v1` protocol (python/src/lifemate/adapters/qwen_native.py): the
system prompt, user JSON and tool schemas are rendered by that exact code, so inference sees the training format.
One decision per step: one `<tool_call>` block or the finish text "Mình hiểu.".

    python native_infer.py --split public_test --asr-model ASR_DIR --llm-model LLM_DIR --lifemate-src SRC_DIR
    python native_infer.py --split train --limit 200 --eval ...           # local score with labels (contaminated:
                                                                            # both models were trained on all train)
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
import lifemate_infer as L  # noqa: E402  (ASR, data discovery, scoring)


def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="public_test", choices=("public_test", "train", "private_test"))
    ap.add_argument("--data-root")
    ap.add_argument("--asr-model", required=True)
    ap.add_argument("--llm-model", required=True)
    ap.add_argument("--lifemate-src", required=True, help="thư mục chứa package lifemate/ (python/src)")
    ap.add_argument("--transcripts", required=True, help="cache ASR json (theo từng mô hình ASR)")
    ap.add_argument("--out", default="submission.jsonl")
    ap.add_argument("--trace", default="traces.jsonl")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", nargs="*", default=[])
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--max-steps", type=int, default=12)
    ap.add_argument("--max-new-tokens", type=int, default=768)
    ap.add_argument("--time-budget", type=float, default=150.0)
    ap.add_argument("--asr-batch", type=int, default=16)
    ap.add_argument("--asr-only", action="store_true", help="chỉ chạy ASR rồi thoát")
    ap.add_argument("--gold-transcript", action="store_true", help="Train: dùng audio_text thay ASR")
    ap.add_argument("--eval", action="store_true")
    ap.add_argument("--device", default="cuda:0")
    return ap.parse_args(argv)


class Planner:
    def __init__(self, model_dir: Path, device: str, qn):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.torch, self.device, self.qn = torch, device, qn
        self.tok = AutoTokenizer.from_pretrained(model_dir)
        self.template = qn.validate_template(self.tok)
        attention = L.memory_safe_attention()
        self.model = AutoModelForCausalLM.from_pretrained(model_dir, torch_dtype=torch.float16,
                                                          attn_implementation=attention).to(device).eval()
        g = self.model.generation_config
        g.do_sample, g.temperature, g.top_p, g.top_k = False, None, None, None
        self.eos = self.tok.eos_token_id
        n = sum(p.numel() for p in self.model.parameters())
        print(f"[llm] {model_dir} params={n / 1e9:.2f}B attention={attention} template={self.template}", flush=True)

    def decide(self, prepared, observations, max_new_tokens):
        prompt = self.qn.render_prompt(self.tok, prepared, observations)
        ids = self.tok(prompt, return_tensors="pt", add_special_tokens=False).input_ids.to(self.device)
        with self.torch.inference_mode():
            out = self.model.generate(ids, max_new_tokens=max_new_tokens, do_sample=False, num_beams=1,
                                      eos_token_id=self.eos, pad_token_id=self.tok.pad_token_id or self.eos)
        gen = [int(t) for t in out[0][ids.shape[-1]:]]
        ended = bool(gen) and gen[-1] == self.eos
        text = self.tok.decode(gen[:-1] if ended else gen, skip_special_tokens=False)
        return text, ended, ids.shape[-1], len(gen)


def lenient(text, eligible):
    """Fallback when the strict parser refuses: first JSON object with a known name inside <tool_call>."""
    import re
    m = re.search(r"<tool_call>\s*(\{.*\})\s*(?:</tool_call>|$)", text, re.S)
    if not m:
        return None
    try:
        v = json.loads(m.group(1))
    except ValueError:
        return None
    if isinstance(v, dict) and v.get("name") in eligible and isinstance(v.get("arguments", {}), dict):
        return {"action": "call", "name": v["name"], "arguments": v.get("arguments", {})}
    return None


def visible_row(item, transcripts, gold):
    """The sample with its user turns carrying the transcript the planner will read (ASR, or gold for diagnostics)."""
    row = copy.deepcopy(item)
    if not gold:
        row["audio_text"] = transcripts.get(item["audio"], "") or "."
        for t in row.get("history", []):
            if t.get("role") == "user":
                t["audio_text"] = transcripts.get(t.get("audio"), "") or "."
    return row


def main(argv=None):
    args = parse_args(argv)
    sys.path.insert(0, str(Path(args.lifemate_src).resolve()))
    from lifemate.adapters import qwen_native as qn
    from lifemate.agent import waiting_for_user
    from lifemate.contracts import Deadline
    from lifemate.dataset import normalize_visible, prepare_request_once, validate_catalog

    L.seed_everything()
    root = L.find_data_root(args.split, args.data_root)
    split_dir = root / args.split
    sys.path.insert(0, str(split_dir))
    from zaic_tools import ToolEnv  # noqa: E402

    items = [json.loads(l) for l in open(split_dir / f"{args.split}.jsonl", encoding="utf-8") if l.strip()]
    if args.ids:
        items = [it for it in items if it["id"] in set(args.ids)]
    if args.limit:
        items = items[: args.limit]
    all_items = items
    si, sn = (int(x) for x in args.shard.split("/"))
    items = items[si::sn]
    raw_catalog = json.load(open(split_dir / f"{args.split}_tools_catalog.json", encoding="utf-8"))
    specs = validate_catalog(raw_catalog)
    fuzzy = L.fuzzy_params({t["name"]: t for a in raw_catalog["apps"] for t in a["tools"]})

    gold = args.gold_transcript and args.split == "train"
    transcripts = {}
    if not gold:
        transcripts = L.build_transcripts(all_items if args.asr_only else items, split_dir, Path(args.asr_model),
                                          Path(args.transcripts), args.device, args.asr_batch)
    if args.asr_only:
        print(f"[asr] {len(transcripts)} transcripts -> {args.transcripts}", flush=True)
        return
    planner = Planner(Path(args.llm_model), args.device, qn)
    scores, t_start = [], time.time()
    with open(args.out, "w", encoding="utf-8") as fout, open(args.trace, "w", encoding="utf-8") as ftr:
        for n, item in enumerate(items, 1):
            t0 = time.time()
            env = ToolEnv(args.split, item["id"], root=str(root))
            trace = {"steps": [], "stop": ""}
            try:
                sample = normalize_visible(visible_row(item, transcripts, gold), specs, split_dir, "transcript")
                prepared, _ = prepare_request_once(sample, None, Deadline(3600.0))
                trace["request"] = prepared["request"]
                eligible = {t["name"] for t in prepared["available_tools"]}
                observations = []
                for _ in range(args.max_steps):
                    if args.time_budget and time.time() - t0 > args.time_budget:
                        trace["stop"] = "time"
                        break
                    text, ended, plen, glen = planner.decide(prepared, observations, args.max_new_tokens)
                    step = {"out": text[:400], "eos": ended, "prompt_tokens": plen, "gen": glen}
                    trace["steps"].append(step)
                    try:
                        action = qn.parse_completion(text, eligible) if ended else None
                    except qn.NativeFormatError as exc:
                        step["format_error"] = str(exc)
                        action = None
                    if action is None:
                        action = lenient(text, eligible)
                        step["lenient"] = action is not None
                    if action is None or action["action"] == "finish":
                        trace["stop"] = "finish" if action else "format"
                        break
                    result = env.call(action["name"], action["arguments"])
                    observations.append({"name": action["name"], "arguments": action["arguments"],
                                         "result": result if isinstance(result, dict) else {"result": result}})
                    if waiting_for_user(action["name"], observations[-1]["result"]):
                        trace["stop"] = "ask"
                        break
                else:
                    trace["stop"] = "max_steps"
            except Exception as exc:  # one bad sample must not kill the shard
                trace["stop"] = f"error: {type(exc).__name__}: {exc}"[:300]
                planner.torch.cuda.empty_cache()
            trace["seconds"] = round(time.time() - t0, 1)
            row = {"id": item["id"], "tool_calls": env.get_tool_calls(), "state_hash": env.get_state_hash()}
            fout.write(json.dumps(row, ensure_ascii=False) + "\n")
            fout.flush()
            msg = f"[{n}/{len(items)}] {item['id']} calls={len(row['tool_calls'])} stop={trace['stop']} {trace['seconds']}s"
            if args.eval and "label" in item:
                genv = ToolEnv(args.split, item["id"], root=str(root))
                for c in item["label"]["tool_calls"]:
                    genv.call(c["name"], c.get("arguments") or {})
                s = L.score_sample(row["tool_calls"], row["state_hash"], item["label"]["tool_calls"],
                                   genv.get_state_hash(), fuzzy)
                scores.append(s)
                trace["score"], trace["gold"] = s, item["label"]["tool_calls"]
                msg += f" score={s:.2f} mean={sum(scores) / len(scores):.4f}"
            print(msg, flush=True)
            print(f"    nghe: {trace.get('request', '')[:300]}", flush=True)
            print("    gọi : " + "; ".join(c["name"] + json.dumps(c.get("arguments") or {}, ensure_ascii=False)[:120]
                                         for c in row["tool_calls"]), flush=True)
            ftr.write(json.dumps({"id": item["id"], **trace, "tool_calls": row["tool_calls"]}, ensure_ascii=False) + "\n")
            ftr.flush()
    print(f"[done] {len(items)} dòng -> {args.out} ({(time.time() - t_start) / max(len(items), 1):.1f}s/mẫu)", flush=True)
    if scores:
        print(f"[eval] {args.split} n={len(scores)} score={sum(scores) / len(scores):.4f}", flush=True)


if __name__ == "__main__":
    main()
