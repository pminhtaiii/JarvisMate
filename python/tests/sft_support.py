"""Controlled planner SFT inputs: labeled sources, a small tokenizer and a snapshot."""
import json
import re
from pathlib import Path

from lifemate.sft import parse_config

CATALOG = {"schema_version": "test", "apps": [
    {"id": "contacts", "tools": [{"name": "contacts.search", "app": "contacts", "kind": "read", "description": "Tìm",
                                  "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                                                 "required": ["query"]}}]},
    {"id": "sms", "tools": [{"name": "sms.send", "app": "sms", "kind": "write", "description": "Gửi",
                             "parameters": {"type": "object", "properties": {
                                 "contact_id": {"type": "string", "x-ref": "contacts.contacts"},
                                 "content": {"type": "string"}, "count": {"type": "integer"}},
                                 "required": ["contact_id", "content"]}}]},
    {"id": "sys", "tools": [{"name": "sys.ask_missing_info", "app": "sys", "kind": "meta", "description": "Hỏi",
                             "parameters": {"type": "object", "properties": {
                                 "tool_name": {"type": "string"}, "params": {"type": "array", "items": {"type": "string"}}},
                                 "required": ["tool_name", "params"]}}]}]}
SENTINEL = "FUTURE_RESULT_SENTINEL"
SEARCH = {"name": "contacts.search", "arguments": {"query": "Lân"}}
FOUND = {"ok": True, "contacts": [{"id": "c_07", "name": "Lân"}]}
SEND = {"name": "sms.send", "arguments": {"contact_id": "c_07", "content": "Tôi đến trễ 10 phút."}}
SENT = {"ok": True, "message_id": SENTINEL}
ASK = {"name": "sys.ask_missing_info", "arguments": {"tool_name": "sms.send", "params": ["content"]}}
WAITING = {"ok": True, "waiting_for_user": True}


def source(sample_id, request="Nhắn Lân tôi đến trễ", calls=(), results=None, **fields):
    row = {"id": sample_id, "audio": f"audio/{sample_id}/{sample_id}.wav", "audio_text": request,
           "context": {"current_time": "2026-11-01T12:00:00+07:00", "timezone": "Asia/Ho_Chi_Minh",
                       "location": {"lat": 21, "lng": 105},
                       "user_profile": {"name": "An", "home_address": "Nhà", "work_address": "Công ty", "city": "Hà Nội"},
                       "installed_apps": {"contacts": {"tools": ["contacts.search"]}, "sms": {"tools": ["sms.send"]}}},
           "history": [], "label": {"tool_calls": list(calls), "tool_results": [] if results is None else list(results),
                                    "final_state": {"secret": "FINAL_STATE_SENTINEL"}}}
    row.update(fields)
    return row


class CharTokenizer:
    """One token per character, with Qwen-shaped special tokens and a transparent template."""
    eos_token = "<|im_end|>"
    pad_token = "<|endoftext|>"
    eos_token_id, pad_token_id = 2, 1
    all_special_tokens = [eos_token, pad_token]
    all_special_ids = [1, 2]
    chat_template = "tools <tool_call> </tool_call> <tool_response>"
    OFFSET = 10

    def __init__(self):
        self.calls = []

    def apply_chat_template(self, messages, tools=None, tokenize=False, add_generation_prompt=False, enable_thinking=None):
        assert not tokenize and add_generation_prompt and enable_thinking is False
        names = ",".join(tool["function"]["name"] for tool in tools)
        lines = [f"tools:{names}"]
        for message in messages:
            if message.get("tool_calls"):
                call = message["tool_calls"][0]["function"]
                body = json.dumps({"name": call["name"], "arguments": call["arguments"]}, ensure_ascii=False)
                lines.append(f"<tool_call>\n{body}\n</tool_call>{self.eos_token}")
            elif message["role"] == "tool":
                lines.append(f"<tool_response>{message['content']}</tool_response>")
            else:
                lines.append(f"{message['role']}:{message['content']}{self.eos_token}")
        return "\n".join(lines) + "\nassistant\n"

    def _split(self, text):
        return [part for part in re.split(f"({re.escape(self.eos_token)})", text) if part]

    def encode(self, text, add_special_tokens=False):
        ids = []
        for part in self._split(text):
            ids += [self.eos_token_id] if part == self.eos_token else [ord(c) + self.OFFSET for c in part]
        return ids

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": self.encode(text)}

    def decode(self, ids, skip_special_tokens=False):
        return "".join(self.eos_token if i == self.eos_token_id else chr(i - self.OFFSET) for i in ids)


def write_snapshot(path: Path) -> Path:
    """Metadata-complete snapshot with a header-only weights file; holds no real weights."""
    path.mkdir(parents=True, exist_ok=True)
    template = "{{ tools }} <tool_call> </tool_call> <tool_response>"
    (path / "config.json").write_text(json.dumps({"model_type": "qwen3", "max_position_embeddings": 32768}), encoding="utf-8")
    (path / "tokenizer.json").write_text("{}", encoding="utf-8")
    (path / "tokenizer_config.json").write_text(json.dumps({"chat_template": template, "eos_token": "<|im_end|>"}), encoding="utf-8")
    header = json.dumps({"weight": {"dtype": "F16", "shape": [10], "data_offsets": [0, 20]}}).encode("utf-8")
    (path / "model.safetensors").write_bytes(len(header).to_bytes(8, "little") + header + bytes(20))
    return path


def write_role(directory: Path, name: str, rows, catalog=CATALOG) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    jsonl, catalog_path = directory / f"{name}.jsonl", directory / f"{name}_catalog.json"
    jsonl.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    return jsonl, catalog_path


def make_config(root: Path, train_rows, validation_rows, *, resolutions=None, microbatch=1, accumulation=16,
                context_tokens=16384, max_new_tokens=512, experiment="experiment", validation_mode=None):
    """``validation_rows`` None means validation_mode "none": no validation file or key exists."""
    train = write_role(root / "data/train", "train", train_rows)
    base = write_snapshot(root / "base")
    data = {"train_jsonl": str(train[0]), "train_catalog": str(train[1]), "train_role": "train",
            "permitted_use": "controlled test"}
    if validation_rows is not None:
        validation = write_role(root / "data/validation", "validation", validation_rows)
        data |= {"validation_jsonl": str(validation[0]), "validation_catalog": str(validation[1]),
                 "validation_role": "validation"}
    if validation_mode is not None:
        data["validation_mode"] = validation_mode
    raw = {"schema_version": 1, "data": data,
           "model": {"base_path": str(base)},
           "training": {"recipe": "qlora-baseline-v1", "device": "cuda:0", "seed": 20261027,
                        "microbatch": microbatch, "accumulation": accumulation},
           "limits": {"context_tokens": context_tokens, "max_new_tokens": max_new_tokens},
           "output": {"experiment_dir": str(root / experiment)}}
    if resolutions is not None:
        path = root / "resolutions.json"
        path.write_text(json.dumps({"resolutions": resolutions}, ensure_ascii=False), encoding="utf-8")
        raw["data"]["audit_resolutions"] = str(path)
    return parse_config(raw, root)


def train_only_config(root: Path, train_rows, **options):
    """100% Train, explicit validation_mode "none"."""
    return make_config(root, train_rows, None, validation_mode="none", **options)
