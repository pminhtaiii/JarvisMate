"""Synthetic controlled fixtures. Never copy or inspect competition environments."""
from __future__ import annotations

import copy
import json
import tempfile
import wave
from collections import deque
from pathlib import Path

from lifemate.contracts import RunConfig


def call(name, **arguments):
    return {"action": "call", "name": name, "arguments": arguments}


FINISH = {"action": "finish"}
CATALOG = {"schema_version": "test-v1", "apps": [
    {"id": "contacts", "tools": [{"name": "contacts.search", "app": "contacts", "kind": "read",
     "description": "Tìm liên hệ", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}]},
    {"id": "sms", "tools": [{"name": "sms.send", "app": "sms", "kind": "write", "description": "Gửi SMS",
     "parameters": {"type": "object", "properties": {"contact_id": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["contact_id", "content"]}}]},
    {"id": "sys", "tools": [{"name": "sys.ask_missing_info", "app": "sys", "kind": "meta", "description": "Hỏi thiếu",
     "parameters": {"type": "object", "properties": {"tool_name": {"type": "string"}, "params": {"type": "array", "items": {"type": "string"}}},
                    "required": ["tool_name", "params"]}}]},
]}


def wav(path, *, rate=16000, channels=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(b"\0\0" * 160 * channels)


class Fixture:
    def __init__(self, count=1):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.split = self.data / "train"
        self.split.mkdir(parents=True)
        self.runtime = self.root / "tools" / "train"
        self.runtime.mkdir(parents=True)
        self.rows = []
        for number in range(1, count + 1):
            sample_id = f"train_{number:04d}"
            audio = f"audio/{sample_id}/{sample_id}.wav"
            wav(self.split / audio)
            state = self.split / "train_environment" / sample_id / "state.json"
            state.parent.mkdir(parents=True)
            state.touch()  # Empty existence marker, never parsed by the controlled runtime.
            self.rows.append({"id": sample_id, "audio": audio, "audio_text": "Nhắn Lan tôi đến trễ",
                              "context": {"current_time": "2026-11-01T12:00:00+07:00",
                               "timezone": "Asia/Ho_Chi_Minh", "location": {"lat": 21, "lng": 105},
                               "user_profile": {"name": "An", "home_address": "Nhà", "work_address": "Công ty", "city": "Hà Nội"},
                               "installed_apps": {"contacts": {"tools": ["contacts.search"]}, "sms": {"tools": ["sms.send"]}}},
                              "history": [], "label": {"secret_gold": "GOLD_MUST_NOT_ENTER_PROMPT"}})
        runtime_source = '''TOOLS = {"contacts.search": "read", "sms.send": "write", "sys.ask_missing_info": "meta"}
def ToolEnv(*args, **kwargs):
    return object()
'''
        (self.runtime / "__init__.py").write_text(runtime_source, encoding="utf-8")
        self.write()

    def write(self):
        (self.split / "train.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self.rows), encoding="utf-8")
        for path in (self.split / "train_tools_catalog.json", self.runtime.parent / "train_tools_catalog.json"):
            path.write_text(json.dumps(CATALOG, ensure_ascii=False), encoding="utf-8")

    def config(self, **changes):
        values = dict(data_root=self.data, runtime_dir=self.runtime, split="train", input_mode="transcript",
                      selected_ids=(self.rows[0]["id"],), run_dir=self.root / "run")
        values.update(changes)
        return RunConfig(**values)

    def close(self):
        self.temp.cleanup()


class ControlledPlanner:
    metadata = {"parameter_count": 100, "controlled_test_only": True}

    def __init__(self, actions):
        self.actions, self.inputs = deque(actions), []

    def next_action(self, value, remaining_seconds):
        self.inputs.append(copy.deepcopy(value))
        if not self.actions:
            raise RuntimeError("No controlled action remains")
        action = self.actions.popleft()
        if isinstance(action, Exception):
            raise action
        if callable(action):
            action = action(value)
        return action if isinstance(action, str) else json.dumps(action, ensure_ascii=False)


class ControlledEnvironment:
    def __init__(self, response=None):
        self.calls = []
        self.response = response

    def call(self, name, arguments):
        self.calls.append({"name": name, "arguments": copy.deepcopy(arguments)})
        if self.response:
            return self.response(name, arguments)
        if name == "contacts.search":
            return {"ok": True, "contacts": [{"id": "observed_77", "name": "Lan"}]}
        if name == "sms.send" and "contact_id" not in arguments:
            return {"ok": False, "error": "missing contact_id"}
        if name == "sys.ask_missing_info":
            return {"ok": True, "waiting_for_user": True}
        return {"ok": True}

    def get_tool_calls(self):
        return copy.deepcopy(self.calls)

    def get_state_hash(self):
        return "a" * 64


class MemoryTrace:
    def __init__(self, fail_on=None):
        self.events, self.fail_on = [], fail_on

    def emit(self, kind, **fields):
        if kind == self.fail_on:
            from lifemate.contracts import PipelineError
            raise PipelineError("TRACE_IO", "Injected storage failure", "trace")
        self.events.append((kind, copy.deepcopy(fields)))


class ControlledASR:
    metadata = {"parameter_count": 50, "controlled_test_only": True}

    def __init__(self):
        self.paths = []

    def transcribe(self, path, remaining_seconds):
        self.paths.append(path)
        return "ASR: " + path.stem
