"""Strict JSON and contained paths; no simulated app-state reads."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from .contracts import PipelineError


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(",", ":"))


def loads(text: str) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("Nonfinite JSON value")

    value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    dumps(value)  # Also rejects numeric overflow such as 1e999, including nested values.
    return value


def read_json(path: Path, code: str = "INPUT_INVALID") -> Any:
    try:
        visible_path(path)
        return loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        raise PipelineError(code, "Required JSON file is unreadable or invalid") from exc


def digest(path: Path) -> str:
    # Only call for visible input/catalog/runtime/model metadata, never environment files.
    try:
        visible_path(path)
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError as exc:
        raise PipelineError("INPUT_INVALID", "Cannot fingerprint visible input") from exc


def safe_id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise PipelineError("INPUT_INVALID", "Unsafe or empty sample ID")
    return value


def visible_path(path: Path) -> None:
    resolved = path.resolve()
    if any(part.lower().endswith(("_environment", "_enviroment")) for part in resolved.parts):
        raise PipelineError("INPUT_INVALID", "App-state files are not visible pipeline inputs")


def contained(base: Path, relative: str, *, must_exist: bool = True,
              allow_environment: bool = False) -> Path:
    if (not isinstance(relative, str) or not relative or "\\" in relative
            or ":" in relative or "\x00" in relative):
        raise PipelineError("INPUT_INVALID", "Invalid relative asset path")
    parts = PurePosixPath(relative)
    if parts.is_absolute() or ".." in parts.parts:
        raise PipelineError("INPUT_INVALID", "Asset path escapes the split")
    try:
        base = base.resolve(strict=True)
        result = (base / relative).resolve()
        if not result.is_relative_to(base):
            raise PipelineError("INPUT_INVALID", "Asset link escapes the split")
        if not allow_environment:
            visible_path(result)
        if must_exist and not result.is_file():
            raise PipelineError("ASSET_MISSING", "Selected asset is missing")
        return result
    except (OSError, RuntimeError) as exc:
        raise PipelineError("ASSET_MISSING", "Cannot resolve selected asset") from exc
