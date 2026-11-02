"""Controlled doubles for native LLM tests. NOT the pinned Qwen tokenizer/template.

FakeQwenTokenizer reproduces the structure of the Qwen3 tool-calling chat template
closely enough to exercise renderer/mask/walk logic; acceptance of the pinned
template requires the real CPU decoder proof (RV002), never these doubles.
"""
from __future__ import annotations

import json

SPECIAL = {"<|im_start|>": 1, "<|im_end|>": 2, "<|endoftext|>": 3}
ADDED = {"<tool_call>": 4, "</tool_call>": 5, "<tool_response>": 6, "</tool_response>": 7}
VOCAB = SPECIAL | ADDED
REVERSE = {v: k for k, v in VOCAB.items()}
OFFSET = 1000


class FakeQwenTokenizer:
    eos_token_id = 2
    pad_token_id = 3
    unk_token_id = None
    bos_token_id = None
    all_special_ids = [1, 2, 3]

    def __init__(self, thinking_branch=False, drift=False):
        self.thinking_branch, self.drift = thinking_branch, drift

    def convert_tokens_to_ids(self, token):
        return VOCAB.get(token, 0)

    def encode(self, text):
        ids, i = [], 0
        while i < len(text):
            for token, value in VOCAB.items():
                if text.startswith(token, i):
                    ids.append(value)
                    i += len(token)
                    break
            else:
                ids.append(OFFSET + ord(text[i]))
                i += 1
        return ids

    def __call__(self, text, add_special_tokens=False, **_):
        return {"input_ids": self.encode(text)}

    def decode(self, ids, skip_special_tokens=False):
        out = []
        for i in ids:
            if i in REVERSE:
                if not (skip_special_tokens and i in SPECIAL.values()):
                    out.append(REVERSE[i])
            else:
                out.append(chr(i - OFFSET))
        return "".join(out)

    def apply_chat_template(self, messages, tools=None, tokenize=False, add_generation_prompt=False,
                            enable_thinking=None):
        def tojson(value):
            return json.dumps(value, ensure_ascii=False)

        text = ""
        if tools:
            text += "<|im_start|>system\n"
            if messages[0]["role"] == "system":
                text += messages[0]["content"] + "\n\n"
            text += "# Tools\n\n<tools>" + "".join("\n" + tojson(t) for t in tools) + "\n</tools><|im_end|>\n"
        elif messages[0]["role"] == "system":
            text += "<|im_start|>system\n" + messages[0]["content"] + "<|im_end|>\n"
        for index, message in enumerate(messages):
            content = message.get("content") if isinstance(message.get("content"), str) else ""
            role = message["role"]
            if role == "user" or (role == "system" and index):
                text += f"<|im_start|>{role}\n{content}<|im_end|>\n"
            elif role == "assistant":
                text += "<|im_start|>assistant\n" + content
                for position, call in enumerate(message.get("tool_calls") or []):
                    if (position == 0 and content) or position:
                        text += "\n"
                    function = call.get("function", call)
                    arguments = function["arguments"] if isinstance(function["arguments"], str) else tojson(function["arguments"])
                    if self.drift:
                        arguments = arguments.replace(": ", ":")
                    text += '<tool_call>\n{"name": "' + function["name"] + '", "arguments": ' + arguments + "}\n</tool_call>"
                text += "<|im_end|>\n"
            elif role == "tool":
                if index == 0 or messages[index - 1]["role"] != "tool":
                    text += "<|im_start|>user"
                text += "\n<tool_response>\n" + content + "\n</tool_response>"
                if index == len(messages) - 1 or messages[index + 1]["role"] != "tool":
                    text += "<|im_end|>\n"
        if add_generation_prompt:
            text += "<|im_start|>assistant\n"
            if self.thinking_branch and enable_thinking is False:
                text += "<think>\n\n</think>\n\n"
        return self.encode(text) if tokenize else text


class WhitelistConstraint:
    """Controlled stand-in for LMFE: allows continuations of a finite set of texts."""

    def __init__(self, tokenizer, texts):
        self.tokenizer, self.texts = tokenizer, list(texts)

    def prefix(self, tools):
        state = {"prompt": None}

        def allowed(batch_id, sent):
            ids = list(sent.tolist() if hasattr(sent, "tolist") else sent)
            if state["prompt"] is None:
                state["prompt"] = len(ids)
            generated = self.tokenizer.decode(ids[state["prompt"]:])
            result = set()
            for text in self.texts:
                if text == generated:
                    result.add(self.tokenizer.eos_token_id)
                elif text.startswith(generated):
                    result.add(self.tokenizer.encode(text[len(generated):])[0])
            return sorted(result) or [self.tokenizer.eos_token_id]

        return allowed


# ------------------------------------------------------------- controlled suites

import copy as _copy  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from lifemate.jsonio import digest, dumps  # noqa: E402
from lifemate.llm_training.config import (BASE_MODEL, IDENTITIES, LIMITS, SEEDS, SUITE_CONFIG_SCHEMA,  # noqa: E402
                                          content_hash)
from lifemate.llm_training.data import SplitExpectation  # noqa: E402
from lifemate.llm_training.storage import write_json  # noqa: E402
from lifemate.llm_training.tokenization import PROOF_SCHEMA, backend_version, proof_binding  # noqa: E402
from support import CATALOG as BASE_CATALOG  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CATALOG = _copy.deepcopy(BASE_CATALOG)
CATALOG["apps"].insert(2, {"id": "chat", "tools": [
    {"name": "chat.list_chats", "app": "chat", "kind": "read", "description": "Liệt kê chat",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "chat.send_message", "app": "chat", "kind": "write", "description": "Gửi tin",
     "parameters": {"type": "object", "properties": {"chat_id": {"type": "string", "x-ref": "chat.chats"},
                                                     "text": {"type": "string", "x-match": "fuzzy"}},
                    "required": ["chat_id", "text"]}}]})
CATALOG["apps"].insert(3, {"id": "banking", "tools": [
    {"name": "banking.transfer", "app": "banking", "kind": "write", "description": "Chuyển tiền",
     "parameters": {"type": "object", "properties": {"account_id": {"type": "string", "x-ref": "banking.accounts"},
                                                     "amount": {"type": "integer", "exclusiveMinimum": 0}},
                    "required": ["account_id", "amount"]}}]})
CONTEXT = {"current_time": "2026-11-01T12:00:00+07:00", "timezone": "Asia/Ho_Chi_Minh",
           "location": {"lat": 21, "lng": 105},
           "user_profile": {"name": "An", "home_address": "Nhà", "work_address": "Công ty", "city": "Hà Nội"}}
FINAL_STATE_SENTINEL = {"sms": {"messages": [{"id": "FINAL_STATE_SENTINEL_MUST_NOT_RENDER", "content": "x" * 40}]}}


def record(sample_id, text, calls, results, apps=("contacts", "sms"), history=()):
    installed = {a: {"tools": [t["name"] for app in CATALOG["apps"] if app["id"] == a for t in app["tools"]]}
                 for a in apps}
    return {"id": sample_id, "audio": f"audio/{sample_id}/{sample_id}.wav", "audio_text": text,
            "context": CONTEXT | {"installed_apps": installed}, "history": list(history),
            "label": {"tool_calls": calls, "tool_results": results, "final_state": FINAL_STATE_SENTINEL}}


def gold(name, **arguments):
    return {"name": name, "arguments": arguments}


SEARCH = {"ok": True, "contacts": [{"id": "c_lan", "name": "Lan", "phone": "0912345678"}]}
CHATS = {"ok": True, "chats": [{"id": "chat_01", "name": "Nhóm A"}]}
ROWS = [
    record("train_0001", "Chào bạn", [], []),
    record("train_0002", "Nhắn Lan tôi đến trễ",
           [gold("contacts.search", query="Lan"), gold("sms.send", contact_id="c_lan", content="Tôi đến trễ")],
           [SEARCH, {"ok": True, "message_id": "m_1", "detail": "SECRET_FUTURE_RESULT_SENTINEL_0123456789"}]),
    record("train_0003", "Nhắn tin", [gold("contacts.search", query="ai"),
                                       gold("sys.ask_missing_info", tool_name="sms.send", params=["contact_id"])],
           [{"ok": True, "contacts": []}, {"ok": True, "waiting_for_user": True}]),
    record("train_0004", "Nhắn tin", [gold("sys.ask_missing_info", tool_name="sms.send", params=["content"]),
                                       gold("contacts.search", query="Lan")],
           [{"ok": True, "waiting_for_user": True}, SEARCH]),
    # train_1696-like controlled shape: k=2 sends to an ID absent from visible evidence.
    record("train_0005", "Gửi nhóm bạn thân lời chào", [gold("contacts.search", query="bạn thân"),
           gold("chat.list_chats"), gold("chat.send_message", chat_id="chat_6142", text="Chào")],
           [{"ok": True, "contacts": []}, CHATS, {"ok": True, "done": False, "message": "không tìm thấy chat_id"}],
           apps=("contacts", "chat")),
    record("train_0006", "Gửi lại", [gold("contacts.search", query="Lan")], [SEARCH], history=[
        {"role": "user", "audio": "audio/train_0006/u1.wav", "audio_text": "Tìm Lan"},
        {"role": "assistant", "text": "Đã tìm.", "tool_calls": [gold("contacts.search", query="Lan")], "tool_results": []}]),
    record("train_0007", "Nhắn Lan", [gold("contacts.search", query="Lan")], []),
    record("train_0008", "Chuyển 500000 cho tài khoản", [gold("banking.transfer", account_id="acc_01", amount=500000)],
           [{"ok": True}], apps=("banking",), history=[
        {"role": "user", "audio": "audio/train_0008/u1.wav", "audio_text": "Số dư?"},
        {"role": "assistant", "text": "Có hai tài khoản.", "tool_calls": [gold("banking.transfer", account_id="acc_01", amount=1)],
         "tool_results": [{"ok": True, "accounts": [{"id": "acc_01"}]}]}]),
    record("train_0009", "Tìm Lan", [gold("contacts.search", query="Lan")], [SEARCH]),
    record("train_0010", "Không cần làm gì", [], []),
]
PARTITIONS = {"train_0009": "validation", "train_0010": "validation"}


class SuiteFixture:
    """Temporary project with visible data, split manifest, config and optional proof."""

    def __init__(self, *, proof=True, rows=None):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "dự án có khoảng trắng"
        self.data = self.root / "resources" / "data"
        split = self.data / "train"
        split.mkdir(parents=True)
        self.rows = rows or ROWS
        for row in self.rows:
            state = split / "train_environment" / row["id"] / "state.json"
            state.parent.mkdir(parents=True)
            state.touch()  # Existence marker only; never parsed.
        (split / "train.jsonl").write_text("".join(dumps(r) + "\n" for r in self.rows), encoding="utf-8")
        (split / "train_tools_catalog.json").write_text(dumps(CATALOG), encoding="utf-8")
        manifest = {"schema": "asr-grouped-split-v1", "seed": 42,
                    "source": {"train_jsonl_sha256": digest(split / "train.jsonl")},
                    "samples": [{"id": r["id"], "group": "g-" + r["id"], "partition": PARTITIONS.get(r["id"], "train"),
                                 "utterances": []} for r in self.rows]}
        manifest["identity"] = content_hash(manifest)
        self.split_manifest = self.root / "resources" / "split42.json"
        self.split_manifest.write_text(dumps(manifest), encoding="utf-8")
        fit = sum(1 for r in self.rows if PARTITIONS.get(r["id"], "train") == "train")
        self.expected = SplitExpectation(manifest["identity"], digest(split / "train.jsonl"),
                                         digest(split / "train_tools_catalog.json"),
                                         {"fit": fit, "validation": len(self.rows) - fit}, ())
        self.model = self.root / "resources" / "model"
        self.model.mkdir()
        (self.model / "tokenizer_config.json").write_text('{"chat_template": "controlled"}', encoding="utf-8")
        self.proof = None
        if proof:
            from lifemate.llm_training.decoder_poc import run_proof
            from unittest.mock import patch
            catalog = REPO / "tools" / "train_tools_catalog.json"
            with patch("lifemate.llm_training.decoder_poc.CATALOG_SHA256", digest(catalog)), \
                    patch("lifemate.llm_training.decoder_poc.backend_version", return_value="0.11.3"):
                result = run_proof(self.root / ".agent-work/llm-finetune/decoder-poc", self.model, catalog,
                                   tokenizer_loader=lambda _: FakeQwenTokenizer(), constraint_factory=proof_constraint)
            self.proof = Path(result["directory"])
        config = {"schema": SUITE_CONFIG_SCHEMA, "project_root": "..", "data_root": "resources/data",
                  "model_dir": "resources/model", "split_manifest": "resources/split42.json",
                  "output_root": ".agent-work/llm-finetune", "runtime_dir": str(REPO / "tools" / "train"),
                  "native_decoder_proof": self.proof.relative_to(self.root).as_posix() if proof else None,
                  "base_model": BASE_MODEL, "identities": IDENTITIES, "seeds": SEEDS, "limits": LIMITS}
        (self.root / "configs").mkdir()
        self.config_path = self.root / "configs" / "suite.json"
        self.config_path.write_text(dumps(config), encoding="utf-8")
        self.suite = self.root / ".agent-work" / "llm-finetune" / "suite-01"

    def close(self):
        self.temp.cleanup()


def proof_constraint(tokenizer):
    from lifemate.llm_training.decoder_poc import fixtures
    from lifemate.adapters.qwen_native import call_completion_text, FINAL_CONTENT
    texts = []
    for case in fixtures():
        if case["kind"] == "valid":
            calls = case["target"].get("tool_calls")
            texts.append(call_completion_text(calls[0]["function"]["name"], calls[0]["function"]["arguments"])
                         if calls else FINAL_CONTENT)
    return WhitelistConstraint(tokenizer, texts)


def accept_fixture(config, suite):
    from lifemate.llm_training.acceptance import audit_corpus, native_acceptance
    native_acceptance(config, suite, FakeQwenTokenizer())
    return audit_corpus(config, suite, FakeQwenTokenizer())
