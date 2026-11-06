"""Synthetic integration fixtures: metadata-only snapshots and TOML configs.

Snapshots carry real safetensors headers but no usable weights; nothing here
loads a model or touches competition environment files.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

from support import Fixture

NATIVE_TEMPLATE = (
    "{%- if tools %}<|im_start|>system\n# Tools\n<tools>{% for t in tools %}{{ t | tojson }}{% endfor %}"
    "</tools>\nFor each function call, return <tool_call>\n{\"name\": <name>, \"arguments\": <args>}\n"
    "</tool_call><|im_end|>\n{%- endif %}{% for m in messages %}{% if m.role == 'tool' %}"
    "<tool_response>{{ m.content }}</tool_response>{% endif %}{% endfor %}")


def safetensors(path: Path, shapes: dict[str, list[int]]) -> None:
    offset, header = 0, {}
    for name, shape in shapes.items():
        size = 2
        for n in shape:
            size *= n
        header[name] = {"dtype": "F16", "shape": shape, "data_offsets": [offset, offset + size]}
        offset += size
    encoded = json.dumps(header).encode()
    # Header only: preflight never reads tensor bytes, so omit the (possibly huge) payload.
    path.write_bytes(struct.pack("<Q", len(encoded)) + encoded)


def snapshot(path: Path, *, planner: bool, template: str = NATIVE_TEMPLATE,
             model_type: str | None = None, parameters: int = 100, positions: int = 40_960) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    config = {"model_type": model_type or ("qwen3" if planner else "whisper")}
    if planner:
        config["max_position_embeddings"] = positions
    (path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (path / "tokenizer.json").write_text("{}", encoding="utf-8")
    tokenizer = {"eos_token": "<|im_end|>"} | ({"chat_template": template} if planner else {})
    (path / "tokenizer_config.json").write_text(json.dumps(tokenizer), encoding="utf-8")
    if not planner:
        (path / "preprocessor_config.json").write_text("{}", encoding="utf-8")
    safetensors(path / "model.safetensors", {"weight": [parameters]})
    return path


def toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return json.dumps(str(value))


class IntegrationFixture(Fixture):
    """Fixture data plus planner/ASR snapshots and a config file writer."""

    def __init__(self, count=1):
        super().__init__(count)
        self.planner = snapshot(self.root / "models" / "planner", planner=True)
        self.asr = snapshot(self.root / "models" / "asr", planner=False)
        self.selection = self.root / "config" / "selection.txt"
        self.selection.parent.mkdir()
        self.selection.write_text("\n".join(r["id"] for r in self.rows) + "\n", encoding="utf-8")
        self.output = self.root / "output"

    def values(self) -> dict:
        return {
            "asr": {"backend": "whisper", "model_path": self.asr, "device": "cpu", "dtype": "float32",
                    "offload": False},
            "planner": {"backend": "qwen3", "protocol": "qwen-native-v1", "model_path": self.planner,
                        "device": "cpu", "dtype": "float32", "offload": False,
                        "context_tokens": 16384, "max_new_tokens": 512},
            "execution": {"timeout_seconds": 30, "max_steps": 16, "startup_timeout_seconds": 300,
                          "recovery_attempts": 1, "seed": 42},
            "data": {"root": self.data, "split": "train", "mode": "audio", "runtime_dir": self.runtime,
                     "sample_ids_file": self.selection},
            "output": {"root": self.output, "debug_payloads": False},
        }

    def toml(self, values: dict | None = None, *, header: str = "schema_version = 1") -> str:
        values = self.values() if values is None else values
        lines = [header]
        for section, table in values.items():
            lines.append(f"\n[{section}]")
            lines += [f"{key} = {toml_value(value)}" for key, value in table.items()]
        return "\n".join(lines) + "\n"

    def write_config(self, values: dict | None = None, **kwargs) -> Path:
        path = self.root / "config" / "integration.toml"
        path.write_text(self.toml(values, **kwargs), encoding="utf-8")
        return path
