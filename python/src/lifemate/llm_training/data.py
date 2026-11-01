"""Frozen split, pure visible projection and native strict-prefix expansion (LL006-LL008).

Label access is confined to ``expand_source``: the visible projection used to build
messages never sees ``label``/``final_state``, and the current target's result R[k]
never enters row k. No ToolEnv, environment file or hidden state is touched.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..adapters.qwen_native import native_call_message, native_final_message, tool_message
from ..dataset import validate_catalog, visible_context
from ..jsonio import digest, loads, safe_id, visible_path
from ..native_tools import SYSTEM_TOOL, adapt_tools
from ..prompting import SYSTEM, HistoryProjectionError, current_user_message, native_history_messages
from .config import (CATALOG_SHA256, DATASET_SHA256, ROW_SCHEMA, SMOKE_FIT_IDS, SPLIT_COUNTS,
                     SPLIT_IDENTITY, content_hash)

SPLIT_SCHEMA = "asr-grouped-split-v1"


class DataContractError(ValueError):
    """Global identity/shape failure: preparation stops instead of row-level noise."""


@dataclass(frozen=True)
class SplitExpectation:
    identity: str = SPLIT_IDENTITY
    dataset_sha256: str = DATASET_SHA256
    catalog_sha256: str = CATALOG_SHA256
    counts: dict = field(default_factory=lambda: dict(SPLIT_COUNTS))
    smoke_fit_ids: tuple[str, ...] = SMOKE_FIT_IDS


PRODUCTION = SplitExpectation()


@dataclass(frozen=True)
class Source:
    id: str
    line: int
    record: dict


def read_train(path: Path) -> list[Source]:
    """Strict JSONL with one-based source lines; duplicate IDs fail globally."""
    visible_path(path)
    sources, seen = [], set()
    try:
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                record = loads(line)
                if not isinstance(record, dict):
                    raise DataContractError(f"Record at line {line_number} is not an object")
                sample_id = safe_id(record.get("id"))
                if sample_id in seen:
                    raise DataContractError("Duplicate source ID")
                seen.add(sample_id)
                sources.append(Source(sample_id, line_number, record))
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, DataContractError):
            raise
        raise DataContractError("Train JSONL is unreadable or invalid") from exc
    return sources


def load_catalog(path: Path) -> tuple[dict, dict[str, dict]]:
    visible_path(path)
    try:
        catalog = loads(path.read_text(encoding="utf-8"))
        return catalog, validate_catalog(catalog)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise DataContractError("Tool catalog is unreadable or invalid") from exc


def validate_split(manifest_path: Path, train_path: Path, catalog_path: Path,
                   sources: list[Source], expected: SplitExpectation = PRODUCTION) -> dict:
    """Verify the existing grouped seed-42 manifest; never re-split (LL006/D01)."""
    visible_path(manifest_path)
    try:
        manifest = loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise DataContractError("Split manifest is missing or unreadable; do not create a new split") from exc
    body = {key: value for key, value in manifest.items() if key != "identity"} if isinstance(manifest, dict) else None
    if (body is None or manifest.get("schema") != SPLIT_SCHEMA or manifest.get("seed") != 42
            or manifest.get("identity") != expected.identity or content_hash(body) != expected.identity):
        raise DataContractError("Frozen seed-42 split identity mismatch; do not re-split")
    if (manifest.get("source", {}).get("train_jsonl_sha256") != expected.dataset_sha256
            or digest(train_path) != expected.dataset_sha256):
        raise DataContractError("Source Train JSONL hash differs from the pinned dataset")
    if digest(catalog_path) != expected.catalog_sha256:
        raise DataContractError("Tool catalog hash differs from the pinned catalog")
    samples = manifest.get("samples")
    if not isinstance(samples, list) or [s.get("id") for s in samples] != [s.id for s in sources]:
        raise DataContractError("Manifest membership/order differs from the source JSONL")
    groups, partition = {}, {}
    for sample in samples:
        kind, group = sample.get("partition"), sample.get("group")
        if kind not in {"train", "validation"} or not isinstance(group, str) or not group:
            raise DataContractError("Invalid partition or group")
        mapped = "fit" if kind == "train" else "validation"  # Manifest train is Fit.
        if groups.setdefault(group, mapped) != mapped:
            raise DataContractError("A group crosses Fit/Validation")
        partition[sample["id"]] = {"partition": mapped, "group": group}
    fit = [i for i, v in partition.items() if v["partition"] == "fit"]
    validation = [i for i, v in partition.items() if v["partition"] == "validation"]
    if {"fit": len(fit), "validation": len(validation)} != expected.counts:
        raise DataContractError("Partition counts differ from the pinned split")
    if any(partition.get(i, {}).get("partition") != "fit" for i in expected.smoke_fit_ids):
        raise DataContractError("Smoke IDs must remain in Fit")
    lines = {source.id: source.line for source in sources}
    return {"schema": "lifemate-native-partition-v1", "split_identity": expected.identity,
            "split_manifest_sha256": digest(manifest_path), "seed": 42, "groups": len(groups),
            "counts": expected.counts, "fit_ids": fit, "validation_ids": validation,
            "sources": {i: {**v, "source_line": lines[i]} for i, v in partition.items()}}


# ------------------------------------------------------------ visible projection

def visible_source(record: dict, specs: dict[str, dict]) -> dict:
    """Label-free planner-visible view with gold (G) transcripts; no audio paths."""
    context, names = visible_context(record.get("context"), specs)
    history = []
    for turn in record.get("history", []) if isinstance(record.get("history"), list) else [None]:
        if not isinstance(turn, dict):
            history.append({"role": None})
        elif turn.get("role") == "user":
            history.append({"role": "user", "text": turn.get("audio_text")})
        else:
            entry = {"role": turn.get("role"), "text": turn.get("text")}
            for key in ("tool_calls", "tool_results"):
                if key in turn:
                    entry[key] = copy.deepcopy(turn[key])
            history.append(entry)
    request = record.get("audio_text")
    if not isinstance(request, str) or not request.strip():
        raise DataContractError("Current transcript is missing")
    return {"request": request, "context": context, "history": history,
            "tool_names": names, "permitted_tools": [copy.deepcopy(specs[n]) for n in names]}


def base_messages(visible: dict) -> list[dict]:
    """System + projected history + current user; raises HistoryProjectionError."""
    return ([{"role": "system", "content": SYSTEM}] + native_history_messages(visible["history"])
            + [current_user_message(visible["request"], visible["context"])])


def target_type(name: str | None) -> str:
    return "ask_missing_info" if name == SYSTEM_TOOL else "normal_call"


def _is_terminal_ask(call: Any, result: Any) -> bool:
    return (isinstance(call, dict) and call.get("name") == SYSTEM_TOOL and isinstance(result, dict)
            and result.get("ok") is True and result.get("waiting_for_user") is True)


def expand_source(source: Source, partition: dict, specs: dict[str, dict], identities: dict) -> dict:
    """Emit every candidate next-action row of one source with trajectory reasons.

    Rows carry complete native input/target when representable; otherwise the row is
    a reason-bearing placeholder so coverage and dispositions stay visible.
    """
    info = partition["sources"][source.id]
    visible = visible_source(source.record, specs)
    native_tools, binding = adapt_tools(visible["permitted_tools"])
    label = source.record.get("label")
    calls = label.get("tool_calls") if isinstance(label, dict) else None
    results = label.get("tool_results") if isinstance(label, dict) else None
    trajectory: set[str] = set()
    history_error = None
    try:
        prefix = base_messages(visible)
    except HistoryProjectionError as exc:
        prefix, history_error = None, {"code": exc.code, "index": exc.index, "detail": exc.detail}
        trajectory.add(exc.code)
    if (not isinstance(calls, list) or not isinstance(results, list) or len(calls) != len(results)
            or any(not isinstance(r, dict) for r in results)
            or any(not isinstance(c, dict) or not isinstance(c.get("name"), str)
                   or not isinstance(c.get("arguments"), dict) for c in calls)):
        trajectory.add("PAIR_MISMATCH")
        calls = calls if isinstance(calls, list) else []
    terminal = next((k for k, (c, r) in enumerate(zip(calls, results or [])) if _is_terminal_ask(c, r)), None)
    if terminal is not None and terminal != len(calls) - 1:
        trajectory.add("TERMINAL_CONTINUATION")
    rows = []

    def emit(k: int, target: dict | None, kind: str):
        provenance = {"source_id": source.id, "source_line": source.line, "group_id": info["group"],
                      "partition": info["partition"], "decision_index": k, "view": "clean",
                      "identities": identities}
        base_id = content_hash({"protocol": identities["protocol"], "source_id": source.id,
                                "decision_index": k, "target": target, "target_type": kind})
        provenance["base_row_id"] = base_id
        messages = None
        if prefix is not None and "PAIR_MISMATCH" not in trajectory:
            messages = copy.deepcopy(prefix)
            for j in range(k):
                messages.append(native_call_message(calls[j]["name"], calls[j]["arguments"]))
                messages.append(tool_message(results[j]))
        row = {"schema": ROW_SCHEMA, "provenance": provenance,
               "input": None if messages is None else {"messages": messages, "tools": native_tools},
               "target": target, "target_type": kind,
               "token_audit": {"status": "not_run", "prompt_tokens": None, "completion_tokens": None,
                               "reserved_output_tokens": 512, "total_tokens": None, "contract": None}}
        row["row_id"] = content_hash({k2: v for k2, v in row.items() if k2 != "row_id"})
        rows.append({"row": row, "result": results[k] if results is not None and k < len(results) else None,
                     "later_results": list(results[k:]) if results is not None else [],
                     "reasons": set(trajectory), "binding": binding})

    if not calls and "PAIR_MISMATCH" not in trajectory:
        emit(0, native_final_message(), "initial_finish")
    else:
        for k, call in enumerate(calls):
            try:
                target = native_call_message(call.get("name"), call.get("arguments"))
            except (ValueError, AttributeError, TypeError):
                target = {"role": "assistant", "content": "", "tool_calls": [
                    {"type": "function", "function": copy.deepcopy(call)}]}
            emit(k, target, target_type(call.get("name") if isinstance(call, dict) else None))
            if terminal == k:
                break
        if terminal is None and calls:
            emit(len(calls), native_final_message(), "finish_after_calls")
    return {"source_id": source.id, "partition": info["partition"], "group_id": info["group"],
            "visible": visible, "binding": binding, "native_tools": native_tools,
            "history_error": history_error, "trajectory_reasons": sorted(trajectory),
            "label_final_state": label.get("final_state") if isinstance(label, dict) else None,
            "calls": calls, "results": results, "candidates": rows}

