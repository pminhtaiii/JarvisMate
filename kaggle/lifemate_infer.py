"""LifeMate end-to-end inference for Kaggle: Whisper ASR (zaic) -> FunReason-MT tool calling -> zaic_tools.

Writes one submission line per sample: {"id", "tool_calls": env.get_tool_calls(), "state_hash": env.get_state_hash()}.
Every sample always gets a line, even when the model fails (the calls already made are kept).

    python lifemate_infer.py --split public_test --out submission.jsonl
    python lifemate_infer.py --split train --limit 100 --eval          # local score on Train (gold labels)
    python lifemate_infer.py --split train --limit 100 --eval --gold-transcript   # isolate the LLM from ASR errors
"""
from __future__ import annotations

import argparse
import copy
import gc
import json
import os
import random
import re
import sys
import time
import unicodedata
import wave
from collections import Counter
from pathlib import Path

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
sys.dont_write_bytecode = True  # Kaggle inputs are read-only; zaic_tools is imported from there.

DEFAULT_LLM = "Qwen/Qwen3-4B-Instruct-2507"
SEED = 20261027
SEARCH_ROOTS = ("/kaggle/input", "/kaggle/working", ".", "..")

DEFAULT_SYSTEM_PROMPT = """Bạn là LifeMate, trợ lý giọng nói tiếng Việt điều khiển các ứng dụng của người dùng bằng cách gọi công cụ (tools).
Yêu cầu của người dùng được nhận dạng từ giọng nói nên có thể sai chính tả, thiếu dấu hoặc lẫn từ tiếng Anh; hãy hiểu theo ý gần nhất.

Quy tắc:
1. Chỉ gọi các tool có trong danh sách, đúng tên, đúng tên tham số, đúng kiểu dữ liệu và enum. Số điện thoại luôn là chuỗi.
2. Tham số ID (device_id, contact_id, event_id, ...) phải lấy từ kết quả tool đã gọi hoặc từ lịch sử hội thoại. Không tự bịa ID, không điền tên vào trường ID. Nếu cần ID mà chưa có, hãy gọi tool tìm kiếm/liệt kê phù hợp trước (ví dụ contacts.search, smart_home.get_status).
3. Thời gian tương đối ("mai", "tối nay", "3 giờ chiều") tính theo current_time và timezone trong ngữ cảnh; dùng định dạng ISO 8601 có múi giờ, ví dụ 2026-11-17T15:00:00+07:00.
4. "Nhà" và "công ty/chỗ làm" lấy từ user_profile (home_address, work_address). Vị trí hiện tại lấy từ location.
5. Lịch sử hội thoại đã được thực hiện xong; không lặp lại các thao tác trong lịch sử. Chỉ xử lý yêu cầu cuối cùng của người dùng.
6. Yêu cầu có điều kiện ("nếu ... thì ...") phải kiểm tra bằng tool trước rồi mới quyết định làm hay không.
7. Nếu thiếu thông tin bắt buộc mà không thể lấy từ ngữ cảnh hoặc tool, gọi sys.ask_missing_info với tool_name là tool cần gọi và params là danh sách tên tham số bắt buộc còn thiếu. Phần nào đủ thông tin thì làm trước.
8. Nếu không có ứng dụng nào được cài có thể xử lý yêu cầu, không gọi tool nào, chỉ trả lời ngắn gọn.
9. Không gọi tool thừa: không gọi lại tool đã thành công, không gọi chỉ để xác nhận. Khi đã hoàn tất, trả lời ngắn gọn bằng tiếng Việt và không gọi thêm tool.
10. Văn bản tự do (nội dung tin nhắn, tiêu đề, ghi chú) giữ đúng ý và từ ngữ người dùng nói.
11. Số đọc bằng chữ phải đổi sang số: "năm mươi ngàn" = 50000, "1 triệu rưỡi" = 1500000, "hai mươi sáu độ" = 26. Số điện thoại đọc từng chữ số: "không chín năm không" = "0950".
12. Chỉ điền tham số tùy chọn khi người dùng nói rõ giá trị đó. Không tự thêm location (mặc định là thành phố của người dùng), label, repeat, note, room, type... nếu người dùng không nói.
13. Trước khi gọi sys.ask_missing_info, hãy tìm thông tin bằng tool đọc dữ liệu (calendar.list_events cho địa điểm/giờ của sự kiện, contacts.search cho người, bill_payment.list_bills cho hóa đơn, banking.list_beneficiaries cho người nhận chuyển khoản...). Chỉ hỏi khi tool không có thông tin.
14. Mỗi lượt chỉ gọi các tool có thể gọi ngay; nếu tham số phụ thuộc kết quả của tool khác thì gọi tool đó trước và chờ kết quả."""


# ----------------------------------------------------------------------------------------------- discovery
def _walk(root: Path, max_depth: int):
    root = Path(root)
    if not root.is_dir():
        return
    stack = [(root, 0)]
    while stack:
        d, depth = stack.pop()
        yield d
        if depth >= max_depth:
            continue
        try:
            children = sorted(p for p in d.iterdir() if p.is_dir() and p.name != "__MACOSX" and not p.name.startswith("."))
        except OSError:
            continue
        # skip huge folders that never hold what we look for
        stack.extend((c, depth + 1) for c in reversed(children) if c.name not in {"audio"} and not c.name.endswith("_environment"))


def find_data_root(split: str, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    for base in SEARCH_ROOTS:
        for d in _walk(Path(base), 5):
            if (d / split / f"{split}.jsonl").is_file() and (d / split / "zaic_tools").is_dir():
                return d.resolve()
    raise SystemExit(f"Không tìm thấy thư mục dữ liệu chứa {split}/{split}.jsonl; truyền --data-root")


def _model_dirs(model_type: str):
    for base in SEARCH_ROOTS:
        for d in _walk(Path(base), 6):
            cfg = d / "config.json"
            if cfg.is_file():
                try:
                    if json.load(open(cfg, encoding="utf-8")).get("model_type") == model_type:
                        yield d.resolve()
                except (OSError, ValueError):
                    pass


def find_asr_model(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    for d in _model_dirs("whisper"):
        if (d / "preprocessor_config.json").is_file():
            return d
    raise SystemExit("Không tìm thấy mô hình Whisper (thư mục zaic/); truyền --asr-model")


def resolve_llm(spec: str, download_dir: str) -> Path:
    p = Path(spec)
    if p.is_dir() and (p / "config.json").is_file():
        return p.resolve()
    want = spec.split("/")[-1].lower()
    for d in _model_dirs("qwen3"):  # a Kaggle dataset/model of the same name already attached
        if any(d.glob("*.safetensors")) and want in str(d).lower():
            print(f"[llm] dùng bản có sẵn: {d}", flush=True)
            return d
    download_dir = download_dir or f"/tmp/{spec.split('/')[-1]}"
    if Path(download_dir, "config.json").is_file() and any(Path(download_dir).glob("*.safetensors")):
        return Path(download_dir)
    from huggingface_hub import snapshot_download
    print(f"[llm] tải {spec} về {download_dir} ...", flush=True)
    return Path(snapshot_download(spec, local_dir=download_dir,
                                  allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.jinja"]))


def seed_everything(seed: int = SEED):
    import numpy as np
    import torch
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True


def gpu_dtype():
    import torch
    if not torch.cuda.is_available():
        return torch.float32
    return torch.bfloat16 if torch.cuda.is_bf16_supported() and torch.cuda.get_device_capability()[0] >= 8 else torch.float16


# ----------------------------------------------------------------------------------------------- ASR
def load_wav(path: Path):
    import numpy as np
    try:
        import soundfile as sf
        audio, sr = sf.read(str(path), dtype="float32", always_2d=False)
    except Exception:
        with wave.open(str(path), "rb") as w:
            sr, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
            raw = w.readframes(w.getnframes())
        dtype = {1: np.uint8, 2: "<i2", 4: "<i4"}[width]
        audio = np.frombuffer(raw, dtype=dtype).astype(np.float32)
        audio = (audio - 128) / 128 if width == 1 else audio / float(2 ** (8 * width - 1))
        if ch > 1:
            audio = audio.reshape(-1, ch)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != 16000 and len(audio):
        n = int(round(len(audio) * 16000 / sr))
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)
    return audio


class ASR:
    def __init__(self, model_dir: Path, device: str):
        import torch
        from transformers import WhisperForConditionalGeneration, WhisperProcessor
        self.torch, self.device = torch, device
        self.dtype = torch.float16 if device.startswith("cuda") else torch.float32
        self.processor = WhisperProcessor.from_pretrained(model_dir)
        self.model = WhisperForConditionalGeneration.from_pretrained(model_dir, torch_dtype=self.dtype).to(device).eval()
        self.params = sum(p.numel() for p in self.model.parameters())
        print(f"[asr] {model_dir} params={self.params / 1e6:.0f}M dtype={self.dtype}", flush=True)

    def transcribe(self, clips, batch_size: int = 16) -> list[str]:
        """clips: list of float32 16 kHz arrays. Clips over 30 s are split into 30 s chunks and joined."""
        import numpy as np
        pieces, owner = [], []
        for i, a in enumerate(clips):
            chunks = [a[s:s + 480000] for s in range(0, max(len(a), 1), 480000)] or [a]
            for c in chunks:
                pieces.append(c if len(c) else np.zeros(1600, dtype=np.float32))
                owner.append(i)
        order = sorted(range(len(pieces)), key=lambda k: len(pieces[k]))
        out = [""] * len(pieces)
        for s in range(0, len(order), batch_size):
            idx = order[s:s + batch_size]
            feats = self.processor([pieces[k] for k in idx], sampling_rate=16000, return_tensors="pt").input_features
            with self.torch.inference_mode():
                ids = self.model.generate(feats.to(self.device, self.dtype), language="vi", task="transcribe",
                                          do_sample=False, num_beams=1, max_new_tokens=440)
            for k, text in zip(idx, self.processor.batch_decode(ids, skip_special_tokens=True)):
                out[k] = text.strip()
        texts = [""] * len(clips)
        for k, i in enumerate(owner):
            texts[i] = (texts[i] + " " + out[k]).strip()
        return texts

    def nbest(self, clips, n: int = 3, beams: int = 8, batch_size: int = 1) -> list[list[str]]:
        """Beam search, up to n distinct hypotheses per clip (first 30 s), best first. Beams often differ only in
        tokenization, so ask for more and de-duplicate the text. One clip at a time: the cross-attention cache grows with
        batch x beams (Kaggle v13: batch 8 x 8 beams needed ~9 GB and OOM'd a T4). A clip that still OOMs gets no N-best."""
        import numpy as np
        out = []
        r = min(beams, 2 * n)
        for s in range(0, len(clips), batch_size):
            part = [c[:480000] if len(c) else np.zeros(1600, dtype=np.float32) for c in clips[s:s + batch_size]]
            feats = self.processor(part, sampling_rate=16000, return_tensors="pt").input_features
            try:
                with self.torch.inference_mode():
                    ids = self.model.generate(feats.to(self.device, self.dtype), language="vi", task="transcribe",
                                              do_sample=False, num_beams=beams, num_return_sequences=r, max_new_tokens=220)
            except self.torch.OutOfMemoryError:
                if self.torch.cuda.is_available():
                    self.torch.cuda.empty_cache()
                out.extend([] for _ in part)
                continue
            texts = [t.strip() for t in self.processor.batch_decode(ids, skip_special_tokens=True)]
            for i in range(len(part)):
                out.append(list(dict.fromkeys(t for t in texts[i * r:(i + 1) * r] if t))[:n])
        return out

    def prompted(self, clip, prompt: str) -> str:
        """Decode again with Whisper prompt_ids = entity names seen in tool results (contextual biasing)."""
        feats = self.processor([clip[:480000]], sampling_rate=16000, return_tensors="pt").input_features
        pids = self.processor.get_prompt_ids(prompt, return_tensors="pt")
        pids = pids[-200:] if len(pids) > 200 else pids
        with self.torch.inference_mode():
            ids = self.model.generate(feats.to(self.device, self.dtype), language="vi", task="transcribe", do_sample=False,
                                      num_beams=5, max_new_tokens=220, prompt_ids=pids.to(self.device))
        text = self.processor.batch_decode(ids, skip_special_tokens=True)[0].strip()
        p = prompt.strip()
        return text[len(p):].strip() if p and text.startswith(p) else text

    def close(self):
        del self.model
        gc.collect()
        if self.torch.cuda.is_available():
            self.torch.cuda.empty_cache()


def user_audio_paths(item) -> list[str]:
    paths = [t["audio"] for t in item.get("history", []) if t.get("role") == "user" and t.get("audio")]
    return paths + [item["audio"]]


def build_transcripts(items, split_dir: Path, asr_dir: Path, cache_path: Path, device: str, batch_size: int) -> dict:
    cache = json.load(open(cache_path, encoding="utf-8")) if cache_path.is_file() else {}
    todo = sorted({p for it in items for p in user_audio_paths(it)} - set(cache))
    if todo:
        asr = ASR(asr_dir, device)
        t0 = time.time()
        step = 256
        for s in range(0, len(todo), step):
            part = todo[s:s + step]
            clips = [load_wav(split_dir / p) for p in part]
            for p, text in zip(part, asr.transcribe(clips, batch_size)):
                cache[p] = text
            json.dump(cache, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"[asr] {min(s + step, len(todo))}/{len(todo)} clips ({time.time() - t0:.0f}s)", flush=True)
        asr.close()
    return cache


def build_nbest(items, split_dir: Path, asr_dir: Path, cache_path: Path, device: str, n: int) -> dict:
    """N-best of the final request clip of every sample (cached like the transcripts)."""
    cache = json.load(open(cache_path, encoding="utf-8")) if cache_path.is_file() else {}
    todo = sorted({it["audio"] for it in items} - set(cache))
    if todo and n > 1:
        asr = ASR(asr_dir, device)
        t0 = time.time()
        for s in range(0, len(todo), 64):
            part = todo[s:s + 64]
            for p, hyps in zip(part, asr.nbest([load_wav(split_dir / p) for p in part], n)):
                cache[p] = hyps
            json.dump(cache, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"[asr-nbest] {min(s + 64, len(todo))}/{len(todo)} clips ({time.time() - t0:.0f}s)", flush=True)
        asr.close()
    return cache


# ----------------------------------------------------------------------------------------------- tools/prompt
def load_catalog(split_dir: Path, split: str) -> dict:
    cat = json.load(open(split_dir / f"{split}_tools_catalog.json", encoding="utf-8"))
    return {t["name"]: t for app in cat["apps"] for t in app["tools"]}


def _clean_schema(node):
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k == "x-match":
                continue
            if k == "x-ref":
                continue
            if k == "x-one-of":
                continue
            out[k] = _clean_schema(v)
        ref = node.get("x-ref")
        if ref and "description" not in out:
            out["description"] = f"ID lấy từ {ref}"
        return out
    if isinstance(node, list):
        return [_clean_schema(x) for x in node]
    return node


def tool_specs(catalog: dict, item) -> list[dict]:
    names = [n for app in item["context"]["installed_apps"].values() for n in app.get("tools", [])]
    names.append("sys.ask_missing_info")
    specs, seen = [], set()
    for n in names:
        if n in seen or n not in catalog:
            continue
        seen.add(n)
        t = catalog[n]
        params = _clean_schema(t.get("parameters") or {"type": "object", "properties": {}})
        groups = (t.get("parameters") or {}).get("x-one-of")
        desc = t.get("description", "")
        if groups and "một trong" not in desc:
            desc += ". Bắt buộc một trong: " + " hoặc ".join("+".join(g) for g in groups)
        if t.get("returns"):
            desc += f". Trả về: {t['returns']}"
        specs.append({"type": "function", "function": {"name": n, "description": desc, "parameters": params}})
    return specs


def dumps(v) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def asr_alternatives(primary: str, hyps: list[str], k: int = 2) -> list[str]:
    """Other readings of the final clip, only when the decoder was unsure (greedy and beam-1 disagree in words)."""
    if not hyps or _norm(hyps[0]) == _norm(primary):
        return []
    out, seen = [], {_norm(primary)}
    for h in hyps:
        if h and _norm(h) not in seen:
            seen.add(_norm(h))
            out.append(h)
    return out[:k]


VI_DAYS = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ nhật"]


def date_table(current_time: str) -> str:
    """Precomputed calendar so the model never does date arithmetic (Kaggle v14: 'mai' -> +2 days, 5 giờ chiều -> 14:00)."""
    from datetime import datetime, timedelta
    try:
        now = datetime.fromisoformat(current_time)
    except (TypeError, ValueError):
        return ""
    d = now.date()
    fmt = lambda x: f"{VI_DAYS[x.weekday()]} {x.isoformat()}"
    monday = d - timedelta(days=d.weekday())
    rows = [f"Bây giờ: {now.strftime('%H:%M')} {fmt(d)} (offset {now.strftime('%z')[:3]}:{now.strftime('%z')[3:]})",
            f"Hôm qua: {fmt(d - timedelta(days=1))}", f"Hôm nay: {fmt(d)}", f"Mai: {fmt(d + timedelta(days=1))}",
            f"Ngày kia/mốt: {fmt(d + timedelta(days=2))}",
            "Tuần này: " + ", ".join(fmt(monday + timedelta(days=i)) for i in range(7)),
            "Tuần sau: " + ", ".join(fmt(monday + timedelta(days=7 + i)) for i in range(7)),
            "Giờ: 'X giờ sáng' = X:00; 'X giờ chiều/tối' = (X+12):00 (vd 5 giờ chiều = 17:00, 8 giờ tối = 20:00); "
            "'rưỡi' = :30; 'kém 15' = trừ 15 phút; 'trước giờ Y N tiếng' = Y − N giờ."]
    return "\n".join(rows)


def build_messages(item, system_prompt: str, transcripts: dict, gold_text: bool, nbest: dict | None = None,
                   dates: bool = False) -> list[dict]:
    ctx = {k: v for k, v in item["context"].items() if k != "installed_apps"}
    ctx["installed_apps"] = list(item["context"]["installed_apps"])
    system = system_prompt.strip() + "\n\n# Ngữ cảnh người dùng\n" + dumps(ctx)
    if dates:
        table = date_table(item["context"].get("current_time", ""))
        if table:
            system += "\n\n# Lịch tham chiếu (đã tính sẵn, dùng trực tiếp)\n" + table
    msgs = [{"role": "system", "content": system}]
    for turn in item.get("history", []):
        if turn.get("role") == "user":
            text = turn.get("audio_text") if gold_text and turn.get("audio_text") else transcripts.get(turn.get("audio"), "")
            msgs.append({"role": "user", "content": text or "(không nghe rõ)"})
        else:
            calls = turn.get("tool_calls") or []
            if calls:
                msgs.append({"role": "assistant", "content": "", "tool_calls": [
                    {"type": "function", "function": {"name": c["name"], "arguments": c.get("arguments") or {}}} for c in calls]})
                results = turn.get("tool_results") or []
                for i in range(len(calls)):
                    msgs.append({"role": "tool", "content": dumps(results[i]) if i < len(results) else '{"ok":true}'})
            msgs.append({"role": "assistant", "content": turn.get("text") or "Đã xong."})
    current = item.get("audio_text") if gold_text and item.get("audio_text") else transcripts.get(item["audio"], "")
    content = current or "(không nghe rõ)"
    alts = [] if gold_text else asr_alternatives(current, (nbest or {}).get(item["audio"]) or [])
    if alts:
        content += "\n(Âm thanh nghe chưa chắc chắn; cách nghe khác: " + " | ".join(f"«{a}»" for a in alts) + ")"
    msgs.append({"role": "user", "content": content})
    return msgs


# ----------------------------------------------------------------------------------------------- parsing
_TOOL_CALL = re.compile(r"<tool_call>\s*(.*?)\s*(?:</tool_call>|$)", re.S)


def _loads_loose(s: str):
    s = s.strip()
    s = re.sub(r"^```(?:json)?|```$", "", s).strip()
    try:
        return json.loads(s)
    except ValueError:
        pass
    m = re.search(r"\{.*\}", s, re.S)
    if m:
        frag = re.sub(r",\s*([}\]])", r"\1", m.group(0))
        try:
            return json.loads(frag)
        except ValueError:
            pass
    return None


# FunReason-MT was trained on BFCL prompting mode, so after </think> it rarely uses <tool_call>{json}</tool_call>.
# Formats seen on Kaggle (v4/v6 traces):  <alarm.create time="..." repeat="once"/>   [event_tickets.book(event_id="e5")]
#   /sys.ask_missing_info(tool_name="x")   <food_delivery.cancel_order(order_id="o1")>   {"name": ..., "arguments": ...}
#   <function name="public_transit.topup_card" arguments={"amount": 150000}>
_TOOL_NAME = r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*"
_FUNC_TAG = re.compile(r"<function\s+name\s*=\s*[\"']?(" + _TOOL_NAME + r")[\"']?\s*(?:arguments|parameters)\s*=\s*"
                       r"(\{.*?\}|\"[^\"]*\"|'[^']*')\s*/?>", re.S)
_FUNC_NAME_TAG = re.compile(r"<(?:function_name|function-name|name|tool_name|function)>\s*(" + _TOOL_NAME + r")\s*"
                            r"</(?:function_name|function-name|name|tool_name|function)>\s*"
                            r"(?:<(?:arguments|parameters|args)>\s*(.*?)\s*(?:</(?:arguments|parameters|args)>|$))?", re.S)
_CHILD_TAG = re.compile(r"<([A-Za-z_][A-Za-z0-9_]*)>\s*(.*?)\s*</\1>", re.S)
_PROSE_HEAD = re.compile(r"^(?:\s*<(?:answer|response|reply|tool_response|result|function[ _-]?calls?)>)*\s*", re.I)


def looks_like_prose(head: str) -> bool:
    """True when the first tokens of an answer are plain text (closing reply or restarted reasoning), not a call."""
    rest = _PROSE_HEAD.sub("", head)
    if not rest.strip():
        return False
    if unicodedata.normalize("NFC", rest.lstrip()).lower().startswith(("điều kiện", "dieu kien", "kiểm tra điều kiện")):
        return False
    if rest.lstrip()[:1] in "<[/{":
        return False
    return not re.search(_TOOL_NAME + r"\s*\(", rest)


def _args_block(raw: str) -> dict:
    """Argument block in any of: JSON, JSON with bare keys / single quotes, <key>value</key> children."""
    import html
    raw = html.unescape(raw or "").strip()
    if not raw:
        return {}
    obj = _loads_loose(raw)
    if isinstance(obj, dict):
        return obj
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        fixed = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', m.group(0))
        obj = _loads_loose(fixed)
        if isinstance(obj, dict):
            return obj
        try:
            import ast
            obj = ast.literal_eval(_py_src(fixed))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    kids = {k: _value(v) for k, v in _CHILD_TAG.findall(raw)}
    return kids
_PY_CALL = re.compile(r"(?<![A-Za-z0-9_.])(" + _TOOL_NAME + r")\s*\(")
_XML_TAG = re.compile(r"<(" + _TOOL_NAME + r")((?:\s+[A-Za-z_][A-Za-z0-9_]*\s*=)[^<>]*?)?\s*/?>", re.S)
_ATTR = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|\{.*?\}(?=\s+[A-Za-z_]\w*\s*=|\s*/?>|\s*$)|\[.*?\](?=\s+[A-Za-z_]\w*\s*=|\s*/?>|\s*$)|[^\s/>]+)", re.S)


def _value(v: str):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        inner = v[1:-1]
        try:
            return json.loads(v) if v[0] == '"' else inner
        except ValueError:
            return inner
    low = v.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "none"):
        return None
    try:
        return json.loads(v)
    except ValueError:
        pass
    try:
        import ast
        return ast.literal_eval(v)
    except Exception:
        return v


def _balanced(text: str, i: int):
    """text[i] == '(' -> index of the matching ')' (quote-aware), or len(text)."""
    depth, q, k = 0, None, i
    while k < len(text):
        ch = text[k]
        if q:
            if ch == "\\":
                k += 1
            elif ch == q:
                q = None
        elif ch in "\"'":
            q = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return k
        k += 1
    return len(text)


def _py_args(src: str):
    """'a="x", b=2, c=true' -> dict, via ast with JSON literals mapped to Python ones."""
    import ast
    try:
        tree = ast.parse("f(" + src + ")", mode="eval")
        out = {}
        for kw in tree.body.keywords:
            if kw.arg is None:
                continue
            try:
                out[kw.arg] = ast.literal_eval(kw.value)
            except Exception:
                seg = ast.get_source_segment("f(" + src + ")", kw.value) or ""
                out[kw.arg] = _value(seg)
        return out
    except SyntaxError:
        return {m.group(1): _value(m.group(2)) for m in _ATTR.finditer(src)}


def _py_src(src: str) -> str:
    return re.sub(r"\b(true|false|null)\b", lambda m: {"true": "True", "false": "False", "null": "None"}[m.group(1)], src)


def _scan_calls(text: str):
    """All non-<tool_call> formats, in order of appearance."""
    found = []
    import html
    taken = []
    for m in _FUNC_TAG.finditer(text):
        raw = m.group(2)
        if raw[:1] in "\"'":
            raw = html.unescape(raw[1:-1])
        found.append((m.start(), {"name": m.group(1), "arguments": _args_block(raw)}))
        taken.append((m.start(), m.end()))
    for m in _FUNC_NAME_TAG.finditer(text):
        if any(a <= m.start() < b for a, b in taken):
            continue
        found.append((m.start(), {"name": m.group(1), "arguments": _args_block(m.group(2) or "")}))
        taken.append((m.start(), m.end()))
    for m in _PY_CALL.finditer(text):
        if any(a <= m.start() < b for a, b in taken):
            continue
        close = _balanced(text, m.end() - 1)
        found.append((m.start(), {"name": m.group(1), "arguments": _py_args(_py_src(text[m.end():close]))}))
        taken.append((m.start(), close + 1))
    for m in _XML_TAG.finditer(text):
        if any(a <= m.start() < b for a, b in taken):
            continue
        attrs = m.group(2) or ""
        found.append((m.start(), {"name": m.group(1),
                                  "arguments": {a.group(1): _value(html.unescape(a.group(2))) for a in _ATTR.finditer(attrs)}}))
    if not found:
        for m in re.finditer(r"\{\s*\"name\"\s*:", text):
            obj = _loads_loose(text[m.start():])
            if isinstance(obj, dict) and isinstance(obj.get("name"), str):
                found.append((m.start(), obj))
                break
    return [c for _, c in sorted(found, key=lambda x: x[0])]


# Qwen3.5 / Qwen3-Coder call format: <function=name>\n<parameter=key>\nvalue\n</parameter>\n</function>
_XML_FUNC = re.compile(r"<function=([^>\s]+)>(.*?)(?:</function>|$)", re.S)
_XML_PARAM = re.compile(r"<parameter=([^>\s]+)>\n?(.*?)\n?(?:</parameter>|(?=<parameter=)|$)", re.S)


def _xml_func_calls(text: str) -> list[dict]:
    out = []
    for m in _XML_FUNC.finditer(text):
        args = {k.strip(): _value(v.strip()) for k, v in _XML_PARAM.findall(m.group(2))}
        out.append({"name": m.group(1).strip(), "arguments": args})
    return out


def parse_output(text: str):
    """-> (visible_content, [ {name, arguments} ])"""
    if "</think>" in text:
        text = text.split("</think>")[-1]
    text = text.replace("<think>", "").strip()
    calls = []
    for m in _TOOL_CALL.finditer(text):
        obj = _loads_loose(m.group(1))
        if isinstance(obj, dict) and isinstance(obj.get("name"), str):
            calls.append(obj)
        elif _XML_FUNC.search(m.group(1)):
            calls.extend(_xml_func_calls(m.group(1)))
        else:
            calls.extend(_scan_calls(m.group(1)))
    if not calls and _XML_FUNC.search(text):
        calls = _xml_func_calls(text)
    if not calls:
        calls = _scan_calls(text)
    out = []
    for c in calls:
        args = c.get("arguments", c.get("parameters", {}))
        if isinstance(args, str):
            args = _loads_loose(args) or {}
        out.append({"name": c["name"].strip(), "arguments": args if isinstance(args, dict) else {}})
    content = _TOOL_CALL.sub("", text).strip()
    return content, out


def fix_name(name: str, allowed: set[str]) -> str:
    if name in allowed:
        return name
    for prefix in ("functions.", "function.", "tools."):
        if name.startswith(prefix) and name[len(prefix):] in allowed:
            return name[len(prefix):]
    tail = [a for a in allowed if a.split(".", 1)[-1] == name or a.replace(".", "_") == name]
    return tail[0] if len(tail) == 1 else name


def coerce_args(args: dict, tool: dict | None) -> dict:
    """Cheap type fixes the schema clearly asks for (e.g. "26" -> 26, 0912 -> "0912"). Unknown keys are kept."""
    if not tool:
        return args
    props = (tool.get("parameters") or {}).get("properties") or {}
    out = {}
    for k, v in args.items():
        typ = (props.get(k) or {}).get("type")
        try:
            if typ == "integer" and isinstance(v, str) and re.fullmatch(r"-?\d+", v.strip()):
                v = int(v.strip())
            elif typ == "integer" and isinstance(v, float) and v.is_integer():
                v = int(v)
            elif typ == "number" and isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?", v.strip()):
                v = float(v) if "." in v else int(v)
            elif typ == "string" and isinstance(v, (int, float)) and not isinstance(v, bool):
                v = str(v)
            elif typ == "boolean" and isinstance(v, str) and v.lower() in {"true", "false"}:
                v = v.lower() == "true"
            elif typ == "array" and isinstance(v, str):
                v = [v]
        except (ValueError, AttributeError):
            pass
        out[k] = v
    return out


_PLACEHOLDER = re.compile(r"^\s*(\.\.\.|…|<[^>]*>|\{[^}]*\}|null|none|n/?a|unknown|tbd|\?+)?\s*$", re.I)


def drop_placeholders(args: dict, tool: dict | None) -> dict:
    """Drop optional arguments the model filled with nothing ("", "...", None): they would not match the gold call."""
    required = set(((tool or {}).get("parameters") or {}).get("required") or [])
    return {k: v for k, v in args.items()
            if k in required or not (v is None or (isinstance(v, str) and _PLACEHOLDER.match(v)) or v == [] or v == {})}


def cut_after_first_read(calls: list, catalog: dict) -> list:
    """FunReason-MT batches every call in one turn, e.g. gold_price.get_price + reminders.create for "if the price is
    below X, remind me" (Kaggle v8 train_0006). Run the batch only up to its first read call; the model sees the result
    and re-plans. Later calls that do not depend on it are simply emitted again in the next step."""
    for i, c in enumerate(calls):
        if (catalog.get(c["name"]) or {}).get("kind") == "read":
            return calls[: i + 1]
    return calls


# ----------------------------------------------------------------------------------------------- v2: guards & nudges
def _norm(s) -> str:
    s = unicodedata.normalize("NFC", str(s).lower())
    return " ".join(re.sub(r"[^\w]+", " ", s).split())


HOME_ALIASES = {"nhà", "nhà tôi", "nhà mình", "nhà em", "nhà anh", "nhà chị", "ở nhà", "về nhà", "home", "nha"}
WORK_ALIASES = {"công ty", "cơ quan", "chỗ làm", "văn phòng", "công ty tôi", "công ty mình", "nơi làm việc", "office",
                "cong ty"}
PLACE_KEYS = {"pickup", "dropoff", "origin", "destination", "from", "to", "address", "start_address", "end_address"}
IATA = {"tp hcm": "SGN", "hcm": "SGN", "hồ chí minh": "SGN", "thành phố hồ chí minh": "SGN", "tp hồ chí minh": "SGN",
        "sài gòn": "SGN", "tân sơn nhất": "SGN", "hà nội": "HAN", "nội bài": "HAN", "đà nẵng": "DAD", "nha trang": "CXR",
        "cam ranh": "CXR", "phú quốc": "PQC", "đà lạt": "DLI", "liên khương": "DLI", "huế": "HUI", "phú bài": "HUI",
        "hải phòng": "HPH", "cát bi": "HPH", "cần thơ": "VCA", "quy nhơn": "UIH", "phù cát": "UIH", "vinh": "VII",
        "buôn ma thuột": "BMV", "côn đảo": "VCS", "thanh hóa": "THD", "thanh hoá": "THD", "pleiku": "PXU",
        "đồng hới": "VDH", "quảng bình": "VDH", "chu lai": "VCL", "tuy hòa": "TBB", "tuy hoà": "TBB", "rạch giá": "VKG",
        "cà mau": "CAH", "điện biên": "DIN", "vân đồn": "VDO", "quảng ninh": "VDO"}


def fix_args(call: dict, item: dict) -> dict:
    """Deterministic repairs of values the gold always writes one way: 'nhà'/'công ty' -> the profile address,
    city names -> IATA codes for flights (train gold: HAN/SGN/DAD...)."""
    args = dict(call.get("arguments") or {})
    prof = (item.get("context") or {}).get("user_profile") or {}
    for k, v in list(args.items()):
        if not isinstance(v, str):
            continue
        n = _norm(v)
        if k in PLACE_KEYS and n in HOME_ALIASES and prof.get("home_address"):
            args[k] = prof["home_address"]
        elif k in PLACE_KEYS and n in WORK_ALIASES and prof.get("work_address"):
            args[k] = prof["work_address"]
        elif call["name"].startswith("flights.") and k in ("origin", "destination"):
            n2 = re.sub(r"^(sân bay|thành phố|tp)\s+", "", n)
            args[k] = IATA.get(n, IATA.get(n2, v))
    return args


def bad_ask(call: dict, catalog: dict, allowed: set) -> str:
    """sys.ask_missing_info must name the write tool that lacks a parameter (Kaggle v12: 21/634 asked for contacts.search)."""
    if call["name"] != "sys.ask_missing_info":
        return ""
    tn = (call.get("arguments") or {}).get("tool_name")
    if tn not in allowed or tn == "sys.ask_missing_info":
        return f"tool_name '{tn}' không có trong danh sách tool"
    if (catalog.get(tn) or {}).get("kind") == "read":
        return (f"'{tn}' là tool đọc: đừng hỏi, hãy gọi thẳng nó (tham số tìm kiếm có thể bỏ trống). "
                "Chỉ hỏi cho tool thực hiện (ghi) đang thiếu tham số bắt buộc")
    return ""


# claimed action verb -> substrings of the write tools that perform it
VERB_TOOLS = {
    "dời": ("update",), "đổi": ("update", "redeem", "set"), "cập nhật": ("update",), "điều chỉnh": ("update", "set"),
    "chỉnh": ("update", "set"), "sửa": ("update",), "đặt": ("create", "book", "reserve", "add", "place_order", "set", "schedule"),
    "hẹn": ("create", "schedule", "book"), "tạo": ("create", "add", "grant"), "nhắn": ("send", "reply"),
    "gửi": ("send", "reply", "transfer", "share"), "gọi": ("call",), "chuyển": ("transfer", "tune"),
    "hủy": ("cancel", "delete", "remove"), "huỷ": ("cancel", "delete", "remove"), "xóa": ("delete", "remove", "archive"),
    "xoá": ("delete", "remove", "archive"), "bật": ("set", "run", "control", "play", "start", "arm"),
    "tắt": ("set", "control", "stop"), "mở": ("set", "play", "tune", "control", "start"), "thanh toán": ("pay", "checkout"),
    "trả": ("pay", "transfer"), "đóng": ("pay",), "mua": ("order", "checkout", "add_to_cart", "book", "place_order"),
    "thêm": ("add", "create", "append"), "nạp": ("topup",), "lưu": ("save", "create", "append"),
    "ghi": ("create", "append", "log", "save"), "đánh dấu": ("complete", "check"), "phát": ("play",),
    "ghi lại": ("create", "append", "log"), "dừng": ("stop", "control"), "bán": ("place_order",), "check in": ("check_in",),
}
_CLAIM = re.compile(r"(?:^|[^\w])(?:đã|vừa|xong)\s+((?:\w+\s){0,1}\w+)", re.I)


def unfulfilled_claim(content: str, done_writes: list[str]) -> str:
    """The reply says the action was done ("đã dời...", "đã nhắn...") but no matching write tool succeeded.
    Kaggle v12: 133/634 samples stopped after a read with such a reply (public_0003, public_0020)."""
    text = unicodedata.normalize("NFC", content or "").lower()
    for m in _CLAIM.finditer(text):
        phrase = m.group(1)
        for verb in sorted(VERB_TOOLS, key=len, reverse=True):
            if phrase == verb or phrase.startswith(verb + " "):
                if not any(p in w for w in done_writes for p in VERB_TOOLS[verb]):
                    return verb
                break
    return ""


_ACTION_WORDS = ("đặt", "dời", "đổi", "chuyển", "nhắn", "gửi", "gọi", "hủy", "huỷ", "xóa", "xoá", "bật", "tắt", "trả",
                 "thanh toán", "đóng tiền", "nạp", "mua", "thêm", "tạo", "nhắc", "lưu", "ghi", "book", "hẹn", "check in",
                 "bán", "đánh dấu", "phát", "mở")
_HONORIFIC = re.compile(r"^(?:anh|chị|chi|cô|co|chú|chu|bác|bac|em|ông|ong|bà|ba|cậu|dì|thím|mợ|bạn|thằng|con|bé)\s+",
                        re.I)


def soft_nudge_due(content: str, done_writes: list, trace: dict, messages: list) -> bool:
    """Stopped with no write after reading, although the request asks for an action (Kaggle v14: ~100/634 public samples
    read bills/balances/beneficiaries and stopped; the claim-based nudge did not fire because nothing was claimed)."""
    low = unicodedata.normalize("NFC", content or "").lower()
    if done_writes or "sai" in low.split() or "không thoả" in low or "không thỏa" in low or "không cần" in low:
        return False
    if len(trace.get("steps", [])) < 2:  # the model never read anything: an answer, not an abandoned plan
        return False
    req = unicodedata.normalize("NFC", trace.get("request", "")).lower()
    return any(re.search(r"(?:^|\W)" + re.escape(w) + r"(?:\W|$)", req) for w in _ACTION_WORDS)


def read_note(call: dict, result: dict) -> str:
    """Plain-language facts the model kept misreading: empty contact search, rain yes/no."""
    name = call["name"]
    if name == "contacts.search" and result.get("contacts") == []:
        q = str((call.get("arguments") or {}).get("query") or "")
        core = _HONORIFIC.sub("", q).strip()
        tip = f" Thử lại với '{core}'." if core and core.lower() != q.lower() else ""
        return ("\n(Không tìm thấy: danh bạ tìm theo chuỗi con của tên, nên bỏ danh xưng (cô, anh, chú, bác...) và chỉ "
                "dùng tên riêng." + tip + ")")
    if name.startswith("weather.") and isinstance(result.get("forecast"), list):
        days = [f"{f.get('date')}: {'CÓ mưa' if f.get('rain') else 'KHÔNG mưa'} ({f.get('condition', '')})"
                for f in result["forecast"] if isinstance(f, dict)]
        return "\n(Tóm tắt: " + "; ".join(days) + ")" if days else ""
    if name.startswith("weather.") and isinstance(result.get("current"), dict) and "rain" in result["current"]:
        return "\n(Tóm tắt: hiện tại " + ("CÓ mưa" if result["current"]["rain"] else "KHÔNG mưa") + ")"
    return ""


# ----------------------------------------------------------------------------------------------- v2: dynamic few-shot
def _bag(text: str) -> Counter:
    w = _norm(text).split()
    return Counter(w + [a + " " + b for a, b in zip(w, w[1:])])


class FewShotIndex:
    """TF-IDF over words + word bigrams of the train requests; per sample, the k most similar solved train samples whose
    gold tools are all installed for this sample. Train labels are permitted training/tuning data."""

    def __init__(self, train_items, skip_ids=()):
        import math
        skip = set(skip_ids)
        self.items = [it for it in train_items if it["id"] not in skip and isinstance(it.get("audio_text"), str)
                      and isinstance(it.get("label"), dict)]
        bags = [_bag(it["audio_text"]) for it in self.items]
        df = Counter()
        for b in bags:
            df.update(b.keys())
        n = len(bags) or 1
        self.idf = {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}
        self.vecs = [self._vec(b) for b in bags]

    def _vec(self, bag):
        import math
        v = {t: c * self.idf.get(t, 0.0) for t, c in bag.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    def top_scored(self, text: str, installed: set, k: int, skip_id: str = ""):
        q = self._vec(_bag(text))
        scored = []
        for it, v in zip(self.items, self.vecs):
            if it["id"] == skip_id:
                continue
            apps = {c["name"].split(".")[0] for c in it["label"].get("tool_calls") or []} - {"sys"}
            if not apps <= installed:
                continue
            s = sum(x * v.get(t, 0.0) for t, x in q.items())
            if s > 0:
                scored.append((s, it))
        scored.sort(key=lambda x: -x[0])
        return scored[:k]

    def top(self, text: str, installed: set, k: int):
        return [it for _, it in self.top_scored(text, installed, k)]


def plan_text(sim: float, example) -> str:
    """Tool sequence of a near-duplicate train request as a suggested plan (public_test reuses the train templates).
    The model still decides arguments and whether each conditional step applies."""
    names = [c["name"] for c in example["label"].get("tool_calls") or []]
    seq = " → ".join(names) if names else "(không gọi tool nào)"
    return ("# Kế hoạch gợi ý (yêu cầu gần như giống một mẫu đã giải đúng, độ giống " + f"{sim:.2f}" + ")\n"
            f"Mẫu đó gọi theo thứ tự: {seq}\n"
            "Hãy làm theo khung này nếu yêu cầu hiện tại cùng ý: đủ các bước, không thêm bước thừa. Tham số lấy từ dữ liệu "
            "thật của người dùng này; bước nào phụ thuộc điều kiện thì vẫn kiểm tra điều kiện trước.")


def fewshot_text(examples) -> str:
    lines = ["# Ví dụ tương tự đã giải đúng (cùng kiểu yêu cầu; dữ liệu là của người dùng khác, ID trong ví dụ KHÔNG dùng được)"]
    for it in examples:
        hist = " (câu nói tiếp theo một hội thoại trước đó)" if it.get("history") else ""
        lines.append(f"Người dùng{hist} [lúc {it['context'].get('current_time', '')}]: {it['audio_text']}")
        res = it["label"].get("tool_results") or []
        calls = it["label"].get("tool_calls") or []
        for i, c in enumerate(calls):
            lines.append(f"→ gọi {c['name']} {dumps(c.get('arguments') or {})}")
            if i < len(res):
                lines.append(f"← kết quả: {dumps(res[i])[:220]}")
        lines.append("→ kết thúc." if calls else "→ không gọi tool nào (không có ứng dụng phù hợp / không cần làm gì).")
        lines.append("")
    return "\n".join(lines) if examples else ""


# ----------------------------------------------------------------------------------------------- v2: ASR helpers
def phon(s: str) -> str:
    """Rough Vietnamese-ear phonetic key, so an English/foreign name heard by a Vietnamese ASR ('Wantaboo') can meet the
    spelling in app data ('Watanabe')."""
    s = unicodedata.normalize("NFD", str(s).lower().replace("đ", "d"))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    out = []
    for w in re.sub(r"[^a-z ]", " ", s).split():
        for a, b in (("ngh", "ng"), ("ph", "f"), ("th", "t"), ("tr", "c"), ("ch", "c"), ("gh", "g"), ("gi", "z"),
                     ("qu", "kw"), ("q", "k"), ("c", "k"), ("d", "z"), ("r", "z"), ("j", "z"), ("x", "s")):
            if w.startswith(a):
                w = b + w[len(a):]
                break
        for a, b in (("ck", "k"), ("c", "k"), ("w", "u"), ("y", "i"), ("oo", "u"), ("ee", "i"), ("ph", "f"), ("th", "t")):
            w = w.replace(a, b)
        w = re.sub(r"(?<=[aeiou])r(?=[^aeiou]|$)", "", w)
        w = re.sub(r"(?<=[aeiou])h(?=[^aeiou]|$)", "", w)
        w = re.sub(r"(?<!n)[dg]$", "t", w)
        out.append(re.sub(r"(.)\1+", r"\1", w))
    return " ".join(out)


NAME_KEYS = {"name", "title", "display_name", "contact_name", "chat_name", "restaurant", "product", "symbol", "station",
             "place", "artist", "track", "program", "provider", "merchant", "beneficiary_name", "hotel", "venue", "brand"}


def result_names(obj, out=None) -> list[str]:
    out = [] if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and (k in NAME_KEYS or k.endswith("_name")) and 1 < len(v) <= 60:
                out.append(v)
            else:
                result_names(v, out)
    elif isinstance(obj, list):
        for v in obj:
            result_names(v, out)
    return out


def phon_hints(texts: list[str], names: list[str], thr: float = 0.62, limit: int = 4) -> list[str]:
    """For names in tool results that the transcript does not contain verbatim, the best same-length word window of any
    ASR hypothesis by phonetic similarity."""
    import difflib
    hay = " ".join(_norm(t) for t in texts)
    hints = []
    for name in dict.fromkeys(names):
        kn = phon(name).replace(" ", "")
        if len(kn) < 5 or _norm(name) in hay:
            continue
        nw, best = len(name.split()), (0.0, "")
        for t in texts:
            ws = t.split()
            for L in {max(1, nw - 1), nw, nw + 1}:
                for s in range(0, max(1, len(ws) - L + 1)):
                    span = " ".join(ws[s:s + L])
                    r = difflib.SequenceMatcher(None, phon(span).replace(" ", ""), kn).ratio()
                    if r > best[0]:
                        best = (r, span)
        if best[0] >= thr:
            hints.append((best[0], f"'{best[1].strip(',.?!')}' có thể là '{name}'"))
    hints.sort(key=lambda x: -x[0])
    return [h for _, h in hints[:limit]]


# ----------------------------------------------------------------------------------------------- LLM
def _sdpa_expanded_kv(module, query, key, value, attention_mask, dropout=0.0, scaling=None, is_causal=None, **kwargs):
    """SDPA with K/V heads repeated up front, so the memory-efficient kernel stays eligible."""
    import torch
    groups = query.shape[1] // key.shape[1]
    if groups > 1:
        key = key.repeat_interleave(groups, dim=1)
        value = value.repeat_interleave(groups, dim=1)
    if attention_mask is not None and attention_mask.ndim == 4:
        attention_mask = attention_mask[:, :, :, : key.shape[-2]]
    if is_causal is None:
        is_causal = query.shape[2] > 1 and attention_mask is None and getattr(module, "is_causal", True)
    out = torch.nn.functional.scaled_dot_product_attention(
        query.contiguous(), key.contiguous(), value.contiguous(), attn_mask=attention_mask,
        dropout_p=dropout, scale=scaling, is_causal=is_causal)
    return out.transpose(1, 2).contiguous(), None


def memory_safe_attention() -> str:
    """GPUs without FlashAttention (T4, P100): SDPA with enable_gqa=True only runs the math kernel, which builds the full
    heads x seq x seq score matrix (several GB at 6-8K tokens -> OOM, and slow). Force the K/V-expanded path instead."""
    import torch
    if not torch.cuda.is_available() or torch.cuda.get_device_capability()[0] >= 8:
        return "sdpa"
    try:
        import transformers.integrations.sdpa_attention as sdpa_mod
        if hasattr(sdpa_mod, "use_gqa_in_sdpa"):
            sdpa_mod.use_gqa_in_sdpa = lambda *a, **k: False
            return "sdpa"
    except ImportError:
        pass
    try:
        import transformers
        mask_iface = getattr(transformers, "AttentionMaskInterface", None)
        if mask_iface is None:
            from transformers.masking_utils import AttentionMaskInterface as mask_iface
        transformers.AttentionInterface.register("sdpa_expanded_kv", _sdpa_expanded_kv)
        mask_iface.register("sdpa_expanded_kv", mask_iface()["sdpa"])
        return "sdpa_expanded_kv"
    except Exception as exc:  # last resort: plain sdpa
        print(f"[llm] không đăng ký được attention tiết kiệm bộ nhớ: {exc}", flush=True)
        return "sdpa"


class LLM:
    def __init__(self, model_dir: Path, device: str, max_context: int = 16384):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.torch, self.device, self.max_context = torch, device, max_context
        self.tok = AutoTokenizer.from_pretrained(model_dir)
        dtype = gpu_dtype()
        attention = memory_safe_attention()
        print(f"[llm] attention={attention}", flush=True)
        try:
            self.model = AutoModelForCausalLM.from_pretrained(model_dir, torch_dtype=dtype, attn_implementation=attention)
        except (ValueError, KeyError) as exc:
            # Qwen3.5 checkpoints are image-text-to-text (Qwen3_5ForConditionalGeneration); text-only prompts work through it
            print(f"[llm] AutoModelForCausalLM: {exc}; dùng AutoModelForImageTextToText", flush=True)
            from transformers import AutoModelForImageTextToText
            self.model = AutoModelForImageTextToText.from_pretrained(model_dir, torch_dtype=dtype, attn_implementation=attention)
        self.model = self.model.to(device).eval()
        gc_ = self.model.generation_config
        gc_.do_sample, gc_.temperature, gc_.top_p, gc_.top_k = False, None, None, None
        self.eos = [i for i in {self.tok.convert_tokens_to_ids("<|im_end|>"), self.tok.eos_token_id,
                                self.tok.convert_tokens_to_ids("<|endoftext|>")} if isinstance(i, int) and i >= 0]
        template = self.tok.chat_template or ""
        # Templates with an enable_thinking switch (Qwen3.5) close the think block themselves.
        self.think_kw = "enable_thinking" in template
        self.has_think = "<think>" in template and "Instruct-2507" not in str(model_dir) and not self.think_kw
        cfg = getattr(self.model.config, "text_config", None) or self.model.config
        # Linear-attention (Gated DeltaNet) layers keep a recurrent state that cannot be cropped back to a shared prefix.
        self.reuse_cache = "linear_attention" not in (getattr(cfg, "layer_types", None) or [])
        print(f"[llm] think_kw={self.think_kw} has_think={self.has_think} reuse_cache={self.reuse_cache}", flush=True)
        self.params = sum(p.numel() for p in self.model.parameters())
        print(f"[llm] {model_dir} params={self.params / 1e9:.2f}B dtype={dtype}", flush=True)

    def render(self, messages, tools, think: bool) -> str:
        extra = {"enable_thinking": bool(think)} if getattr(self, "think_kw", False) else {}
        prompt = self.tok.apply_chat_template(messages, tools=tools, tokenize=False, add_generation_prompt=True, **extra)
        # FunReason-MT always opens a long <think> block (Kaggle v4: 616/634 samples ran out of tokens mid-thought).
        # Without --think, prefill an empty think block (Qwen3 non-thinking convention) so it answers directly.
        return prompt + self.render_suffix(think)

    def render_suffix(self, think: bool) -> str:
        if not getattr(self, "has_think", True):
            return ""
        return "<think>\n" if think else "<think>\n\n</think>\n\n"

    def think_end_ids(self):
        i = self.tok.convert_tokens_to_ids("</think>")
        return [i] if isinstance(i, int) and i >= 0 else []

    def generate_name(self, prompt: str, names: list[str]) -> str:
        """Constrained decoding of a tool name: only continuations that stay a prefix of one of `names` (followed by the
        closing quote) are allowed. Returns the chosen name."""
        import torch
        from transformers import LogitsProcessor, LogitsProcessorList, StoppingCriteria, StoppingCriteriaList
        tok, targets = self.tok, [n + '"' for n in names]

        def make(start):
            class OnlyNames(LogitsProcessor):
                def __call__(self, input_ids, scores):
                    done = tok.decode(input_ids[0, start:], skip_special_tokens=True)
                    live = [t for t in targets if t.startswith(done)]
                    allowed = set()
                    for t in live:  # the canonical next token of every still-possible name guarantees progress
                        rest = t[len(done):]
                        if rest:
                            allowed.add(tok(rest, add_special_tokens=False)["input_ids"][0])
                    for i in torch.topk(scores[0], 200).indices.tolist():
                        piece = tok.decode([i])
                        if piece and any(t.startswith(done + piece) for t in live):
                            allowed.add(i)
                    mask = torch.full_like(scores, float("-inf"))
                    idx = torch.tensor(sorted(allowed), device=scores.device, dtype=torch.long)
                    mask[0, idx] = scores[0, idx]
                    return mask

            class QuoteClosed(StoppingCriteria):
                def __call__(self, input_ids, scores, **kwargs):
                    done = tok.decode(input_ids[0, start:], skip_special_tokens=True)
                    return torch.full((input_ids.shape[0],), '"' in done, dtype=torch.bool, device=input_ids.device)

            return {"logits_processor": LogitsProcessorList([OnlyNames()]),
                    "stopping_criteria": StoppingCriteriaList([QuoteClosed()])}

        out = self.generate(prompt, 32, extra=make)
        return out.split('"')[0].strip()

    def tool_end_ids(self):
        i = self.tok.convert_tokens_to_ids("</tool_call>")
        return [i] if isinstance(i, int) and i >= 0 else []

    def count(self, text: str) -> int:
        return len(self.tok(text, add_special_tokens=False)["input_ids"])

    def reset(self):
        """Start of a sample: drop the KV cache (tools/system prompt differ between samples)."""
        self.cache, self.cache_ids = None, []

    def _stop_without_tool_call(self, start: int, grace: int, head_prefix: str = ""):
        """Stop a plain-text answer after `grace` tokens: only tool calls are scored, the closing text is not."""
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList
        call_id = self.tok.convert_tokens_to_ids("<tool_call>")
        think_id = self.tok.convert_tokens_to_ids("<think>")

        tok = self.tok

        class NoToolCall(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                gen = input_ids[0, start:]
                stop = (gen.shape[0] >= grace and not bool((gen == call_id).any()) and not bool((gen == think_id).any()))
                if stop:
                    head = head_prefix + tok.decode(gen[:grace], skip_special_tokens=True)
                    stop = looks_like_prose(head)
                return torch.full((input_ids.shape[0],), stop, dtype=torch.bool, device=input_ids.device)

        return StoppingCriteriaList([NoToolCall()])

    def generate(self, prompt: str, max_new_tokens: int, text_grace: int = 0, stop_ids=(), no_think: bool = False,
                 head_prefix: str = "", extra=None) -> str:
        """Greedy decode. Within a sample, the KV cache of the longest common token prefix with the previous step is reused,
        so each agent step only prefills the new tool result instead of the whole 6-8K-token prompt."""
        ids = self.tok(prompt, return_tensors="pt", add_special_tokens=False)["input_ids"].to(self.device)
        new = ids[0].tolist()
        kwargs = {}
        cache = getattr(self, "cache", None) if getattr(self, "reuse_cache", True) else None
        if cache is not None:
            old = self.cache_ids
            n, lim = 0, min(len(old), len(new) - 1)
            while n < lim and old[n] == new[n]:
                n += 1
            if n > 0:
                cache.crop(n)
                kwargs["past_key_values"] = cache
        if text_grace:
            kwargs["stopping_criteria"] = self._stop_without_tool_call(len(new), text_grace, head_prefix)
        if no_think:
            bad = [i for i in (self.tok.convert_tokens_to_ids("<think>"), self.tok.convert_tokens_to_ids("</think>"))
                   if isinstance(i, int) and i >= 0]
            if bad:
                kwargs["bad_words_ids"] = [[i] for i in bad]
        kwargs.update(extra(len(new)) if extra else {})
        with self.torch.inference_mode():
            out = self.model.generate(input_ids=ids, attention_mask=self.torch.ones_like(ids),
                                      max_new_tokens=max_new_tokens, do_sample=False, num_beams=1,
                                      eos_token_id=self.eos + list(stop_ids), pad_token_id=self.tok.pad_token_id or self.eos[0],
                                      return_dict_in_generate=True, **kwargs)
        seq = out.sequences[0]
        self.cache = out.past_key_values
        self.cache_ids = seq[: self.cache.get_seq_length()].tolist()
        return self.tok.decode(seq[len(new):], skip_special_tokens=True)


def fit_context(llm: LLM, messages, tools, think, max_new_tokens):
    """Shrink the longest tool outputs until prompt + reserved output fits the 16K context."""
    budget = llm.max_context - max_new_tokens
    prompt = llm.render(messages, tools, think)
    n = llm.count(prompt)
    while n > budget:
        tool_idx = [i for i, m in enumerate(messages) if m["role"] == "tool" and len(m["content"]) > 300]
        if not tool_idx:
            return None, n
        i = max(tool_idx, key=lambda k: len(messages[k]["content"]))
        c = messages[i]["content"]
        messages[i] = {"role": "tool", "content": c[: len(c) // 2] + " ...(cắt bớt)"}
        prompt = llm.render(messages, tools, think)
        n = llm.count(prompt)
    return prompt, n



# ----------------------------------------------------------------------------------------------- grounding / pruning / few-shot
_VI_DIGITS = {"không": "0", "một": "1", "mốt": "1", "hai": "2", "ba": "3", "bốn": "4", "tư": "4", "năm": "5", "lăm": "5",
              "sáu": "6", "bảy": "7", "bẩy": "7", "tám": "8", "chín": "9", "linh": "0", "lẻ": "0"}
PHONE_PARAMS = {"phone", "phone_number"}


def spoken_digits(text: str) -> str:
    """'không chín năm không ...' / '0950 ...' -> every maximal run of digits, joined by spaces."""
    runs, cur = [], ""
    for w in re.findall(r"\w+", unicodedata.normalize("NFC", str(text).lower())):
        if w.isdigit():
            cur += w
        elif w in _VI_DIGITS:
            cur += _VI_DIGITS[w]
        else:
            if cur:
                runs.append(cur)
            cur = ""
    if cur:
        runs.append(cur)
    return " ".join(runs)


def ungrounded_args(call: dict, catalog: dict, seen_text: str, said_digits: str) -> list[str]:
    """ID arguments (x-ref) must come from data the agent has already seen (tool results, history, context); phone numbers
    from that data or from what the user said. Kaggle v11: Qwen invented contact_123 / evt_12345 / 0987654321."""
    props = ((catalog.get(call["name"]) or {}).get("parameters") or {}).get("properties") or {}
    bad = []
    for k, v in (call.get("arguments") or {}).items():
        spec = props.get(k) or {}
        vals = v if isinstance(v, list) else [v]
        for x in vals:
            if not isinstance(x, (str, int)) or isinstance(x, bool):
                continue
            x = str(x)
            if spec.get("x-ref") and x not in seen_text:
                bad.append(f"{k}={x}")
            elif k in PHONE_PARAMS:
                digits = re.sub(r"\D", "", x)
                if digits and digits not in re.sub(r"\D", "", seen_text) and digits not in said_digits.replace(" ", ""):
                    bad.append(f"{k}={x}")
    return bad


def ref_hint(call: dict, catalog: dict, allowed: set) -> str:
    props = ((catalog.get(call["name"]) or {}).get("parameters") or {}).get("properties") or {}
    apps = {(spec.get("x-ref") or "").split(".")[0] for spec in props.values() if spec.get("x-ref")}
    if any(k in PHONE_PARAMS for k in (call.get("arguments") or {})):
        apps.add("contacts")
    reads = sorted(n for n in allowed if n.split(".")[0] in apps and (catalog.get(n) or {}).get("kind") == "read")
    return ", ".join(reads) or "tool tìm kiếm/liệt kê phù hợp"


def rare_optional_params(train_items, catalog: dict, max_rate: float = 0.1, min_uses: int = 3,
                         read_rate: float = 0.1) -> set:
    """(tool, param) pairs that are optional in the schema and (almost) never set in the train gold calls. Read tools
    use their own, higher threshold: an extra filter never changes the state but makes the call unmatched
    (Kaggle v14 train: calendar.list_events with date_from/date_to cost 7 of 40 samples)."""
    use, present = Counter(), Counter()
    for it in train_items:
        for c in (it.get("label") or {}).get("tool_calls") or []:
            use[c["name"]] += 1
            for k in c.get("arguments") or {}:
                present[(c["name"], k)] += 1
    rare = set()
    for n, t in catalog.items():
        params = t.get("parameters") or {}
        req = set(params.get("required") or [])
        for k in params.get("properties") or {}:
            rate = read_rate if t.get("kind") == "read" else max_rate
            if k not in req and use[n] >= min_uses and present[(n, k)] / use[n] < rate:
                rare.add((n, k))
    return rare


def few_shot_block(train_items, catalog: dict, skip_ids=()) -> str:
    """Three solved train samples (taken past the first 200 so the local eval subset is not leaked)."""
    pool = [it for it in train_items[200:] if it["id"] not in set(skip_ids) and isinstance(it.get("audio_text"), str)
            and not it.get("history")]

    def names(it):
        return [c["name"] for c in it["label"]["tool_calls"]]

    picks = []
    tests = [
        lambda it: "nếu" in it["audio_text"].lower() and len(names(it)) == 1
        and (catalog.get(names(it)[0]) or {}).get("kind") == "read",
        lambda it: names(it)[:2] in (["contacts.search", "sms.send"], ["contacts.search", "phone.call"]),
        lambda it: len(names(it)) == 2 and names(it)[0] == "smart_home.get_status",
    ]
    for test in tests:
        hit = next((it for it in pool if it not in picks and test(it)), None)
        if hit:
            picks.append(hit)
    lines = ["# Ví dụ đã giải đúng (chỉ minh họa cách làm, dữ liệu là của người dùng khác)"]
    for it in picks:
        lines.append(f"Người dùng: {it['audio_text']}")
        res = it["label"].get("tool_results") or []
        for i, c in enumerate(it["label"]["tool_calls"]):
            lines.append(f"→ gọi {c['name']} {dumps(c.get('arguments') or {})}")
            if i < len(res):
                lines.append(f"← kết quả: {dumps(res[i])[:260]}")
        lines.append("→ kết thúc (không gọi thêm tool).")
        lines.append("")
    return "\n".join(lines) if picks else ""


FINISH_TOOL = {"type": "function", "function": {
    "name": "finish",
    "description": "Gọi khi yêu cầu của người dùng đã được xử lý xong, hoặc khi không có ứng dụng nào xử lý được yêu cầu "
                   "(khi đó không gọi tool nào khác). Không có tham số.",
    "parameters": {"type": "object", "properties": {}, "required": []}}}


def run_agent(item, env, llm: LLM, catalog: dict, system_prompt: str, transcripts: dict, args) -> dict:
    tools = tool_specs(catalog, item)
    allowed = {t["function"]["name"] for t in tools}
    constrained = bool(getattr(args, "constrained", False))
    if constrained:
        tools = tools + [FINISH_TOOL]
    messages = build_messages(item, system_prompt, transcripts, args.gold_transcript, getattr(args, "nbest_cache", None),
                              getattr(args, "date_table", False))
    trace = {"request": messages[-1]["content"], "steps": []}
    heard = [] if args.gold_transcript else [transcripts.get(item["audio"], "")] + list(
        (getattr(args, "nbest_cache", None) or {}).get(item["audio"]) or [])
    done_writes: list[str] = []
    nudges, pass2_done = 0, False
    seen_text = dumps(item.get("context") or {}) + dumps(item.get("history") or [])
    said_digits = spoken_digits(" ".join(m["content"] for m in messages if m["role"] == "user"))
    rare = getattr(args, "rare_params", None) or set()
    seen: dict[str, dict] = {}
    last_fail, fail_streak = None, 0
    if hasattr(llm, "reset"):
        llm.reset()
    t0 = time.time()
    for step in range(args.max_steps):
        if args.time_budget and time.time() - t0 > args.time_budget:
            trace["stop"] = "time_budget"
            break
        prompt, n_tokens = fit_context(llm, messages, tools, args.think, args.max_new_tokens)
        if prompt is None:
            trace["stop"] = f"context_overflow({n_tokens})"
            break
        g0 = time.time()
        thought, prefix = "", ""
        if getattr(args, "think_budget", 0):
            # FunReason-MT reasons before every call; with an empty <think> it reasons in plain text instead (Kaggle v5:
            # 634/634 empty). Budget forcing: think up to N tokens, close the block ourselves, then decode the answer.
            p_think = prompt[: -len(llm.render_suffix(False))] + llm.render_suffix(True)
            thought = llm.generate(p_think, args.think_budget, stop_ids=llm.think_end_ids())
            closed = "</think>" in thought
            thought = thought.split("</think>")[0].rstrip()
            prompt = p_think + thought + "\n</think>\n\n"
            if not closed:
                # Kaggle v8: after a forced </think> the model restarted prose reasoning ("Okay, let's see...") in 6/12
                # samples and never emitted a call. Every call format it uses starts with "<", and so does <answer>.
                prefix = "<"
                prompt += prefix
        if constrained:
            # The answer is always one tool call; the model only picks the name (or `finish`) and writes the arguments.
            head = prompt[: len(prompt) - len(prefix)] if prefix else prompt
            head += '<tool_call>\n{"name": "'
            name = llm.generate_name(head, sorted(allowed) + ["finish"])
            if name == "finish" or name not in allowed:
                trace["steps"].append({"think": thought[-1500:], "raw": f"[constrained] {name}", "prompt_tokens": n_tokens,
                                       "seconds": round(time.time() - g0, 2)})
                trace["stop"] = "answer"
                break
            head += name + '", "arguments": '
            body = llm.generate(head, args.max_new_tokens, stop_ids=llm.tool_end_ids())
            raw = '<tool_call>\n{"name": "' + name + '", "arguments": ' + body.split("</tool_call>")[0] + "\n</tool_call>"
        else:
            if getattr(args, "force_call", False) and step == 0 and not prefix:
                prefix = "<tool_call>\n"
                prompt += prefix
            raw = prefix + llm.generate(prompt, args.max_new_tokens, text_grace=0 if args.think else args.text_grace,
                                        no_think=bool(getattr(args, "think_budget", 0)), head_prefix=prefix)
        content, calls = parse_output(raw)
        trace["steps"].append({"think": thought[-1500:], "raw": raw[-2000:], "prompt_tokens": n_tokens,
                               "seconds": round(time.time() - g0, 2)})
        if not calls:
            verb = unfulfilled_claim(content, done_writes) if getattr(args, "nudge", True) else ""
            if not verb and getattr(args, "soft_nudge", False) and nudges == 0 and soft_nudge_due(
                    content, done_writes, trace, messages):
                nudges += 1
                trace["steps"][-1]["nudge"] = "soft"
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": (
                    "[Hệ thống] Chưa có thao tác nào được thực hiện, mới chỉ đọc dữ liệu. Đọc lại yêu cầu của người dùng: "
                    "nếu yêu cầu cần thao tác (đặt, chuyển, nhắn, dời, huỷ, bật/tắt, thanh toán...) và điều kiện (nếu có) "
                    "thoả, hãy gọi tool đó ngay với giá trị từ kết quả ở trên; thiếu thông tin bắt buộc thì gọi "
                    "sys.ask_missing_info. Nếu điều kiện không thoả hoặc người dùng chỉ hỏi thông tin, trả lời đúng một "
                    "câu: 'Không cần làm thêm.'")})
                continue
            if verb and nudges < 2:
                nudges += 1
                trace["steps"][-1]["nudge"] = verb
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": (
                    f"[Hệ thống] Bạn vừa nói đã {verb} nhưng CHƯA gọi tool nào để làm việc đó, nên chưa có gì được thực "
                    "hiện. Hãy gọi ngay tool cần thiết, dùng ID/giá trị từ các kết quả ở trên. Nếu thực ra không cần làm "
                    "(điều kiện không thoả) thì trả lời ngắn; nếu thiếu thông tin bắt buộc thì gọi sys.ask_missing_info.")})
                continue
            trace["stop"] = "answer"
            break
        for c in calls:
            c["name"] = fix_name(c["name"], allowed)
            c["arguments"] = drop_placeholders(coerce_args(c["arguments"], catalog.get(c["name"])), catalog.get(c["name"]))
            c["arguments"] = {k: v for k, v in c["arguments"].items() if (c["name"], k) not in rare}
            if getattr(args, "fix_args", True):
                c["arguments"] = fix_args(c, item)
        calls = cut_after_first_read(calls, catalog)
        messages.append({"role": "assistant", "content": content, "tool_calls": [
            {"type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}} for c in calls]})
        stop = False
        for c in calls:
            key = c["name"] + dumps(c["arguments"])
            check = env.validate(c["name"], c["arguments"])  # schema check only: not logged, nothing executed
            ask_err = bad_ask(c, catalog, allowed) if getattr(args, "fix_args", True) else ""
            if ask_err:
                result = {"ok": False, "error": f"Chưa thực thi: {ask_err}."}
            elif key in seen and seen[key].get("ok") is not False:
                result = {"ok": False, "error": "Call này đã được thực hiện thành công ở trên, không gọi lại. "
                                                "Hãy làm bước tiếp theo hoặc trả lời kết thúc."}
            elif getattr(args, "ground", True) and ungrounded_args(c, catalog, seen_text, said_digits):
                bad = ungrounded_args(c, catalog, seen_text, said_digits)
                result = {"ok": False, "error": f"Chưa thực thi: {', '.join(bad)} không có trong dữ liệu đã thấy. Không tự đặt ID "
                                                f"hay số điện thoại; hãy gọi {ref_hint(c, catalog, allowed)} trước để lấy giá trị đúng."}
            elif not check.get("ok"):
                # A rejected env.call would still be logged and scored as an unmatched call; let the model fix it.
                result = {"ok": False, "error": f"Chưa thực thi, sai schema: {check.get('error')}. Sửa lại tham số "
                                                "hoặc dùng sys.ask_missing_info nếu thiếu thông tin."}
            else:
                result = env.call(c["name"], c["arguments"])
                seen[key] = result
                seen_text += dumps(result)
                if result.get("ok") is not False and (catalog.get(c["name"]) or {}).get("kind") == "write":
                    done_writes.append(c["name"])
            tool_msg = dumps(result)[: args.max_tool_chars]
            if heard and result.get("ok") is not False and (catalog.get(c["name"]) or {}).get("kind") == "read":
                names = result_names(result)
                notes = []
                live = getattr(args, "asr_live", None)
                if live is not None and names and not pass2_done:
                    pass2_done = True
                    try:
                        clip = load_wav(args.split_dir / item["audio"])
                        again = live.prompted(clip, ", ".join(list(dict.fromkeys(names))[:30]))
                        if again and _norm(again) != _norm(heard[0]):
                            heard.append(again)
                            notes.append(f"nghe lại audio với các tên trong dữ liệu: «{again}»")
                            trace["asr_pass2"] = again
                    except Exception as exc:  # never lose the sample over the optional second pass
                        trace["asr_pass2_error"] = f"{type(exc).__name__}: {exc}"[:300]
                        if live.torch.cuda.is_available():
                            live.torch.cuda.empty_cache()
                if getattr(args, "asr_hints", True) and names:
                    h = phon_hints(heard, names)
                    if h:
                        notes.append("tên nghe gần giống: " + "; ".join(h))
                        trace.setdefault("asr_hints", []).extend(h)
                if notes:
                    tool_msg += "\n(Gợi ý nhận dạng giọng nói: " + " | ".join(notes) + ")"
            if getattr(args, "read_notes", False) and result.get("ok") is not False:
                tool_msg += read_note(c, result)
            messages.append({"role": "tool", "content": tool_msg})
            fail = key + dumps(result) if result.get("ok") is False else None
            fail_streak = fail_streak + 1 if fail and fail == last_fail else (1 if fail else 0)
            last_fail = fail
            if c["name"] == "sys.ask_missing_info" and result.get("ok") and result.get("waiting_for_user"):
                stop, trace["stop"] = True, "ask_missing_info"
                break
            if fail_streak >= 3:
                stop, trace["stop"] = True, "repeated_failure"
                break
        if stop:
            break
    else:
        trace["stop"] = "max_steps"
    trace["seconds"] = round(time.time() - t0, 2)
    return trace


# ----------------------------------------------------------------------------------------------- local scoring (Train only)
def _nfc_tokens(s) -> list[str]:
    return unicodedata.normalize("NFC", str(s).lower()).split()


def token_f1(a, b) -> float:
    ta, tb = _nfc_tokens(a), _nfc_tokens(b)
    if not ta and not tb:
        return 1.0
    common = sum((Counter(ta) & Counter(tb)).values())
    if common == 0:
        return 0.0
    p, r = common / len(ta), common / len(tb)
    return 2 * p * r / (p + r)


def fuzzy_params(catalog: dict) -> dict:
    return {n: {k for k, v in ((t.get("parameters") or {}).get("properties") or {}).items() if v.get("x-match") == "fuzzy"}
            for n, t in catalog.items()}


def calls_match(p, g, fuzzy: dict) -> bool:
    if p.get("name") != g.get("name"):
        return False
    pa, ga = p.get("arguments") or {}, g.get("arguments") or {}
    fz = fuzzy.get(g["name"], set())
    if set(pa) != set(ga):
        return False
    for k, gv in ga.items():
        if k in fz:
            if token_f1(pa[k], gv) <= 0.6:
                return False
        elif pa[k] != gv:
            return False
    return True


def score_sample(pred_calls, pred_hash, gold_calls, gold_hash, fuzzy) -> float:
    """Our reading of the brief: empty gold -> 1 iff empty prediction; else 0 on state mismatch, otherwise F1(P, R)."""
    if not gold_calls:
        return float(not pred_calls)
    if pred_hash != gold_hash:
        return 0.0
    used, m = set(), 0
    for p in pred_calls:
        for j, g in enumerate(gold_calls):
            if j not in used and calls_match(p, g, fuzzy):
                used.add(j)
                m += 1
                break
    if m == 0:
        return 0.0
    prec, rec = m / len(pred_calls), m / len(gold_calls)
    return 2 * prec * rec / (prec + rec)


# ----------------------------------------------------------------------------------------------- main
def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="public_test", choices=("public_test", "train", "private_test"))
    ap.add_argument("--data-root", help="thư mục chứa <split>/ (tự dò trong /kaggle/input nếu bỏ trống)")
    ap.add_argument("--asr-model", help="thư mục Whisper zaic/ (tự dò nếu bỏ trống)")
    ap.add_argument("--llm-model", default=DEFAULT_LLM, help="thư mục local hoặc repo HF")
    ap.add_argument("--llm-download-dir", default="", help="mặc định /tmp/<tên repo>")
    ap.add_argument("--prompt-file", help="file system prompt (UTF-8); mặc định dùng prompt có sẵn")
    ap.add_argument("--out", default="submission.jsonl")
    ap.add_argument("--trace", default="traces.jsonl")
    ap.add_argument("--transcripts", default="transcripts_{split}.json", help="cache ASR")
    ap.add_argument("--limit", type=int, default=0, help="chỉ chạy N mẫu đầu (0 = tất cả)")
    ap.add_argument("--ids", nargs="*", default=[])
    ap.add_argument("--max-steps", type=int, default=10)
    ap.add_argument("--max-new-tokens", type=int, default=512)
    ap.add_argument("--max-tool-chars", type=int, default=6000)
    ap.add_argument("--time-budget", type=float, default=60.0, help="giây mỗi mẫu cho vòng LLM (0 = không giới hạn)")
    ap.add_argument("--think-budget", type=int, default=0,
                    help="nghĩ tối đa N token trong <think>, rồi tự đóng </think> và sinh tool call (0 = tắt)")
    ap.add_argument("--no-few-shot", dest="few_shot", action="store_false", help="tắt 3 ví dụ lấy từ train")
    ap.add_argument("--no-prune", dest="prune", action="store_false", help="giữ cả tham số tùy chọn hiếm dùng")
    ap.add_argument("--no-ground", dest="ground", action="store_false", help="không chặn ID/số điện thoại tự bịa")
    ap.add_argument("--constrained", action="store_true",
                    help="mỗi bước là đúng một tool call: tên tool được giải mã có ràng buộc (hoặc `finish` để kết thúc)")
    ap.add_argument("--force-call", action="store_true", help="bước đầu tiên luôn bắt đầu bằng <tool_call>")
    ap.add_argument("--think", action="store_true", help="mở <think> như model card (chậm hơn nhiều)")
    ap.add_argument("--text-grace", type=int, default=20,
                    help="dừng câu trả lời chữ sau N token nếu chưa có <tool_call> (0 = tắt)")
    ap.add_argument("--shard", default="0/1", help="i/n: chỉ chạy mẫu thứ i, i+n, ... (chia cho nhiều GPU)")
    ap.add_argument("--prepare-only", action="store_true", help="chỉ chạy ASR + tải LLM rồi thoát")
    ap.add_argument("--asr-batch", type=int, default=16)
    ap.add_argument("--gold-transcript", action="store_true", help="Train: dùng audio_text thay ASR")
    ap.add_argument("--eval", action="store_true", help="Train: chấm điểm cục bộ với nhãn")
    ap.add_argument("--asr-device", default="cuda:0")
    ap.add_argument("--fewshot-k", type=int, default=3, help="số ví dụ train tương tự cho mỗi mẫu (0 = 3 ví dụ cố định cũ)")
    ap.add_argument("--no-nudge", dest="nudge", action="store_false", help="không nhắc khi model nói đã làm mà chưa gọi tool")
    ap.add_argument("--no-fix-args", dest="fix_args", action="store_false", help="không sửa nhà/công ty, IATA, ask sai tool")
    ap.add_argument("--asr-nbest", type=int, default=3, help="số giả thuyết beam cho câu cuối (<=1 = tắt)")
    ap.add_argument("--no-asr-pass2", dest="asr_pass2", action="store_false", help="không giải mã lại có prompt tên")
    ap.add_argument("--no-asr-hints", dest="asr_hints", action="store_false", help="không gợi ý tên theo phát âm")
    # v3 features (public 33.99 < v2 34.66): off by default, opt in per flag
    ap.add_argument("--read-prune-rate", type=float, default=0.1,
                    help="bỏ tham số tùy chọn của tool đọc nếu gold train dùng < tỉ lệ này (v3 dùng 0.25)")
    ap.add_argument("--date-table", action="store_true", help="thêm bảng ngày tính sẵn vào ngữ cảnh (v3)")
    ap.add_argument("--soft-nudge", action="store_true", help="nhắc khi dừng sau khi đọc mà chưa thao tác (v3)")
    ap.add_argument("--read-notes", action="store_true",
                    help="ghi chú sau tool đọc: danh bạ rỗng, mưa/không mưa (v3)")
    ap.add_argument("--plan-sim", type=float, default=0.0,
                    help="thêm kế hoạch gợi ý từ mẫu train giống nhất khi độ giống >= ngưỡng này (0 = tắt)")
    ap.add_argument("--llm-device", default="cuda:0")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    import torch
    if not torch.cuda.is_available():
        args.asr_device = args.llm_device = "cpu"
    seed_everything()
    root = find_data_root(args.split, args.data_root)
    split_dir = root / args.split
    print(f"[data] root={root}", flush=True)
    sys.path.insert(0, str(split_dir))
    from zaic_tools import ToolEnv  # noqa: E402

    items = [json.loads(l) for l in open(split_dir / f"{args.split}.jsonl", encoding="utf-8") if l.strip()]
    if args.ids:
        items = [it for it in items if it["id"] in set(args.ids)]
    if args.limit:
        items = items[: args.limit]
    shard_i, shard_n = (int(x) for x in args.shard.split("/"))
    all_items, items = items, items[shard_i::shard_n]
    print(f"[data] {len(items)} mẫu (shard {args.shard})", flush=True)
    catalog = load_catalog(split_dir, args.split)
    system_prompt = (open(args.prompt_file, encoding="utf-8").read() if args.prompt_file else DEFAULT_SYSTEM_PROMPT)

    transcripts = {}
    if not (args.gold_transcript and args.split == "train"):
        asr_dir = find_asr_model(args.asr_model)
        transcripts = build_transcripts(all_items if args.prepare_only else items, split_dir, asr_dir, Path(args.transcripts.format(split=args.split)),
                                        args.asr_device, args.asr_batch)
        args.nbest_cache = build_nbest(all_items if args.prepare_only else items, split_dir, asr_dir,
                                       Path(f"asr_nbest_{args.split}.json"), args.asr_device, args.asr_nbest)

    llm_dir = resolve_llm(args.llm_model, args.llm_download_dir)
    if args.prepare_only:
        print(f"[prepare] transcripts={len(transcripts)} llm={llm_dir}", flush=True)
        return
    llm = LLM(llm_dir, args.llm_device)
    args.split_dir, args.asr_live = split_dir, None
    if args.asr_pass2 and not (args.gold_transcript and args.split == "train"):
        args.asr_live = ASR(find_asr_model(args.asr_model), args.llm_device)  # stays resident for the second pass
    fuzzy = fuzzy_params(catalog)
    train_items = []
    for cand in {root / "train" / "train.jsonl", split_dir.parent / "train" / "train.jsonl"}:
        if cand.is_file():
            train_items = [json.loads(l) for l in open(cand, encoding="utf-8") if l.strip()]
            break
    args.rare_params = (rare_optional_params(train_items, catalog, read_rate=args.read_prune_rate)
                        if (train_items and args.prune) else set())
    eval_ids = [it["id"] for it in items] if args.split == "train" else []
    fs_index = FewShotIndex(train_items, eval_ids) if (train_items and args.few_shot and args.fewshot_k > 0) else None
    if train_items and args.few_shot and not fs_index:
        system_prompt = system_prompt.rstrip() + "\n\n" + few_shot_block(train_items, catalog, eval_ids)
    print(f"[agent] rare optional params={len(args.rare_params)} few_shot={args.few_shot} k={args.fewshot_k} "
          f"ground={args.ground} nudge={args.nudge} fix_args={args.fix_args} nbest={args.asr_nbest} "
          f"pass2={args.asr_live is not None} hints={args.asr_hints} read_prune={args.read_prune_rate} "
          f"dates={args.date_table} soft_nudge={args.soft_nudge} read_notes={args.read_notes} plan_sim={args.plan_sim}",
          flush=True)
    scores = []
    t_start = time.time()
    with open(args.out, "w", encoding="utf-8") as fout, open(args.trace, "w", encoding="utf-8") as ftr:
        for n, item in enumerate(items, 1):
            env = ToolEnv(args.split, item["id"], root=root)  # exactly one environment per sample
            try:
                sp, plan_sim = system_prompt, None
                if fs_index:
                    query = (item.get("audio_text") if args.gold_transcript and isinstance(item.get("audio_text"), str)
                             else transcripts.get(item["audio"], ""))
                    scored = fs_index.top_scored(query, set(item["context"]["installed_apps"]), max(args.fewshot_k, 1))
                    sp = system_prompt.rstrip() + "\n\n" + fewshot_text([it for _, it in scored[: args.fewshot_k]])
                    if args.plan_sim and scored and scored[0][0] >= args.plan_sim:
                        plan_sim = round(scored[0][0], 3)
                        sp += "\n\n" + plan_text(scored[0][0], scored[0][1])
                trace = run_agent(item, env, llm, catalog, sp, transcripts, args)
                if plan_sim is not None:
                    trace["plan_sim"] = plan_sim
            except Exception as exc:  # keep the calls already made; never re-create the env
                trace = {"stop": f"error: {type(exc).__name__}: {exc}"}
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            row = {"id": item["id"], "tool_calls": env.get_tool_calls(), "state_hash": env.get_state_hash()}
            fout.write(json.dumps(row, ensure_ascii=False) + "\n")
            fout.flush()
            msg = f"[{n}/{len(items)}] {item['id']} calls={len(row['tool_calls'])} stop={trace.get('stop')} {trace.get('seconds', 0)}s"
            if args.eval and "label" in item:
                gold_env = ToolEnv(args.split, item["id"], root=root)  # scorer-side replay of the gold label only
                for c in item["label"]["tool_calls"]:
                    gold_env.call(c["name"], c.get("arguments") or {})
                s = score_sample(row["tool_calls"], row["state_hash"], item["label"]["tool_calls"],
                                 gold_env.get_state_hash(), fuzzy)
                scores.append(s)
                trace["score"], trace["gold"] = s, item["label"]["tool_calls"]
                msg += f" score={s:.2f} mean={sum(scores) / len(scores):.4f}"
            print(msg, flush=True)
            # What the ASR heard (or the gold transcript with --gold-transcript), and what the agent called
            print(f"    nghe: {trace.get('request', '')[:300]}", flush=True)
            if args.eval and "audio_text" in item and not args.gold_transcript:
                gold_text = item["audio_text"] if isinstance(item["audio_text"], str) else item["audio_text"].get(item["audio"], "")
                print(f"    gốc : {str(gold_text)[:300]}", flush=True)
            print("    gọi : " + "; ".join(c["name"] + dumps(c.get("arguments") or {})[:120] for c in row["tool_calls"]), flush=True)
            ftr.write(json.dumps({"id": item["id"], **trace, "tool_calls": row["tool_calls"]}, ensure_ascii=False) + "\n")
            ftr.flush()
    total = time.time() - t_start
    print(f"[done] {len(items)} dòng -> {args.out}  ({total / max(len(items), 1):.1f}s/mẫu)", flush=True)
    if scores:
        print(f"[eval] {args.split} n={len(scores)} score={sum(scores) / len(scores):.4f}", flush=True)


if __name__ == "__main__":
    main()
