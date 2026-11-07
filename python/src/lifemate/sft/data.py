"""Audited native next-action export from labeled JSONL and catalog files.

Reads only those files: no ToolEnv is created and no environment file is opened. Each
source yields all of its rows or an audit entry, so a partial trajectory never becomes
training data. Gold labels stay outside ``input`` except the strict prefix of the
target, which the inference whitelist and native renderer then see like live observations.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import unicodedata
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..adapters.qwen_native import (FINISH_TEXT, PROTOCOL, SYSTEM_SHA256, NativeFormatError, completion_text,
                                    decoding_schema, parse_completion, render_prompt, validate_template)
from ..agent import waiting_for_user
from ..artifacts import atomic_json, sync_write
from ..configuration import ModelSettings, check_parameter_budget, inspect_snapshot
from ..contracts import JSON, Deadline, PipelineError
from ..dataset import normalize_visible, prepare_request_once, validate_catalog
from ..jsonio import digest, dumps, loads, read_json, safe_id
from ..provenance import code_identity, model_identity
from . import RECIPE_NAME, SftConfig

ROW_SCHEMA = "planner-next-action-v1"
MAX_ROW_BYTES = 4 * 1024 * 1024
GROUP_FIELDS = ("conversation_id", "group_id", "source_group")
# A reviewer may keep a flagged gold target; the other reasons leave no valid row to keep.
KEEPABLE = frozenset({"UNGROUNDED_ID", "SCHEMA_INVALID_TARGET"})
REASONS = KEEPABLE | {"INVALID_SOURCE", "INVALID_LABEL", "UNEQUAL_PAIRS", "UNAVAILABLE_TOOL", "CALLS_AFTER_TERMINAL",
                      "CONTEXT_OVERFLOW", "OUTPUT_OVERFLOW", "TARGET_RENDER", "TOKEN_BOUNDARY"}


def blocked(message: str, code: str = "SFT_BLOCKED") -> PipelineError:
    return PipelineError(code, message, "sft_data")


@dataclass(frozen=True)
class RoleData:
    role: str
    base: Path
    rows: tuple[JSON, ...]
    specs: dict[str, JSON]
    identity: JSON


def read_role(role: str, jsonl: Path, catalog_path: Path) -> RoleData:
    """Read one declared role; a file-level defect stops export rather than losing sources."""
    if not jsonl.is_file() or not catalog_path.is_file():
        raise PipelineError("ASSET_MISSING", f"{role} JSONL or catalog is missing", "sft_data")
    catalog = read_json(catalog_path, "CATALOG_INVALID")
    specs = validate_catalog(catalog)
    rows, seen = [], set()
    try:
        with jsonl.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                if len(line.encode("utf-8")) > MAX_ROW_BYTES:
                    raise PipelineError("INPUT_INVALID", f"{role} row is too large", "sft_data")
                row = loads(line)
                if not isinstance(row, dict):
                    raise PipelineError("INPUT_INVALID", f"{role} row must be an object", "sft_data")
                sample_id = safe_id(row.get("id"))
                if sample_id in seen:
                    raise PipelineError("INPUT_INVALID", f"Duplicate {role} ID {sample_id}", "sft_data")
                # Competition test rows carry neither transcript nor label; they are not a tuning role.
                if sample_id.startswith(("public", "private")) or ("label" not in row and "audio_text" not in row):
                    raise PipelineError("INPUT_INVALID", f"{role} contains competition test row {sample_id}", "sft_data")
                seen.add(sample_id)
                rows.append(row)
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        raise PipelineError("INPUT_INVALID", f"{role} JSONL is unreadable or invalid", "sft_data") from exc
    if not rows:
        raise PipelineError("INPUT_INVALID", f"{role} JSONL has no rows", "sft_data")
    return RoleData(role, jsonl.parent.resolve(), tuple(rows), specs, {
        "role": role, "jsonl": jsonl.as_posix(), "jsonl_sha256": digest(jsonl), "catalog": catalog_path.as_posix(),
        "catalog_sha256": digest(catalog_path), "catalog_version": catalog["schema_version"], "sources": len(rows)})


# --- Cross-role overlap ---------------------------------------------------------

def normalize_text(value) -> str:
    """NFC, case-folded, whitespace-collapsed; Vietnamese diacritics and numbers stay distinct."""
    return " ".join(unicodedata.normalize("NFC", value).casefold().split()) if isinstance(value, str) else ""


def _turn_text(turn) -> str:
    if not isinstance(turn, dict):
        return ""
    return normalize_text(turn.get("audio_text") if turn.get("role") == "user" else turn.get("text"))


def _visible_keys(row: JSON) -> JSON:
    history = row.get("history") if isinstance(row.get("history"), list) else []
    turns = [_turn_text(turn) for turn in history]
    request = normalize_text(row.get("audio_text"))

    def key(value) -> str:
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    return {"input": key([request, turns, row.get("context")]), "request": request,
            "conversation": key(turns) if turns else None,
            "groups": {(field, str(row[field])) for field in GROUP_FIELDS if row.get(field) is not None}}


def audit_overlap(train: RoleData, validation: RoleData) -> JSON:
    """Before expansion: IDs, visible inputs, shared conversations and any declared groups.

    The supplied Train format has no conversation IDs, so an identical nonempty history
    stands in for them. Identical requests alone are reported: short commands legitimately
    recur with different contexts.
    """
    left = {r["id"]: _visible_keys(r) for r in train.rows}
    right = {r["id"]: _visible_keys(r) for r in validation.rows}

    def shared(field: str) -> set:
        return ({k[field] for k in left.values() if k[field]} & {k[field] for k in right.values() if k[field]})

    ids = sorted(set(left) & set(right))
    inputs, conversations = shared("input"), shared("conversation")
    groups = set().union(*(k["groups"] for k in left.values())) & set().union(*(k["groups"] for k in right.values()))
    declared = any(k["groups"] for k in left.values()) and any(k["groups"] for k in right.values())
    failed = bool(ids or inputs or conversations or groups)
    return {"status": "overlap" if failed else "disjoint", "id_overlap": len(ids), "id_examples": ids[:20],
            "visible_input_overlap": len(inputs), "conversation_overlap": len(conversations),
            "declared_group_overlap": len(groups), "request_only_overlap": len(shared("request")),
            "grouping_metadata": "declared" if declared else "unavailable"}


# --- Semantic conversion --------------------------------------------------------

def schema_errors(schema: JSON, value, path: str = "arguments") -> list[str]:
    """Bounded check of the decoding schema vocabulary: what the runtime could emit."""
    kind = schema.get("type")
    valid = {"string": isinstance(value, str), "integer": type(value) is int, "number": type(value) in (int, float),
             "boolean": type(value) is bool, "array": isinstance(value, list), "object": isinstance(value, dict),
             "null": value is None}.get(kind, True)
    if not valid:
        return [f"{path}: expected {kind}"]
    errors = []
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: outside enum")
    if "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{path}: below minimum")
    if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
        errors.append(f"{path}: not above exclusive minimum")
    if kind == "string" and len(value) < schema.get("minLength", 0):
        errors.append(f"{path}: too short")
    if kind == "array":
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: too few items")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                errors += schema_errors(schema["items"], item, f"{path}[{index}]")
    if kind == "object":
        properties = schema.get("properties", {})
        errors += [f"{path}.{key}: missing" for key in schema.get("required", []) if key not in value]
        for key, item in value.items():
            if key in properties:
                errors += schema_errors(properties[key], item, f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: undeclared property")
    return errors


def target_schema_errors(tool: JSON, arguments: JSON) -> list[str]:
    errors = schema_errors(decoding_schema(tool), arguments)
    groups = tool["parameters"].get("x-one-of")
    if groups and not any(all(key in arguments for key in group) for group in groups):
        errors.append("arguments: no x-one-of alternative is complete")
    return errors


def reference_values(schema: JSON, value) -> Iterable:
    """Argument values whose schema declares an ``x-ref`` to app data."""
    if "x-ref" in schema and not isinstance(value, (dict, list)):
        yield value
    if isinstance(value, dict):
        for key, item in value.items():
            if key in schema.get("properties", {}):
                yield from reference_values(schema["properties"][key], item)
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        for item in value:
            yield from reference_values(schema["items"], item)


def grounded(value, visible: str) -> bool:
    # Dumped form, so quoting and escapes compare the same on both sides.
    return (dumps(value)[1:-1] if isinstance(value, str) else dumps(value)) in visible


def _entry(role: str, source_id: str, index: int | None, reason: str, message: str) -> JSON:
    return {"role": role, "source_id": source_id, "decision_index": index, "reason": reason,
            "message": message[:300], "status": "unresolved"}


def convert_source(row: JSON, data: RoleData) -> tuple[list[JSON], list[JSON]]:
    """One source to next-action rows plus audit entries; never repairs or drops gold.

    Flagged-but-representable targets keep their rows so a reviewer may resolve them;
    structural failures yield no rows at all.
    """
    source_id, role = row["id"], data.role

    def fail(reason: str, message: str, index: int | None = None) -> tuple[list[JSON], list[JSON]]:
        return [], [_entry(role, source_id, index, reason, message)]

    try:
        sample = normalize_visible(row, data.specs, data.base, "transcript")
        prepared, _ = prepare_request_once(sample, None, Deadline(3600.0))
    except (PipelineError, KeyError, TypeError) as exc:
        return fail("INVALID_SOURCE", str(exc))
    label = row.get("label")
    calls = label.get("tool_calls") if isinstance(label, dict) else None
    results = label.get("tool_results") if isinstance(label, dict) else None
    if not isinstance(calls, list) or not isinstance(results, list):
        return fail("INVALID_LABEL", "Label requires tool_calls and tool_results lists")
    if len(calls) != len(results):
        return fail("UNEQUAL_PAIRS", f"{len(calls)} calls paired with {len(results)} results")
    tools = {tool["name"]: tool for tool in sample.tools}
    inputs = {key: prepared[key] for key in ("request", "context", "history", "available_tools")}
    visible = dumps({key: prepared[key] for key in ("request", "context", "history")})
    rows, entries, observations, terminal = [], [], [], False

    def emit(index: int, target: JSON) -> None:
        rows.append({"schema": ROW_SCHEMA,
                     "provenance": {"source_id": source_id, "role": role, "decision_index": index},
                     "input": inputs | {"observations": [dict(item) for item in observations]}, "target": target})

    for index, (call, result) in enumerate(zip(calls, results)):
        if terminal:
            return fail("CALLS_AFTER_TERMINAL", "Gold continues after a waiting clarification", index)
        if (not isinstance(call, dict) or set(call) != {"name", "arguments"} or not isinstance(call["name"], str)
                or not isinstance(call["arguments"], dict) or not isinstance(result, dict)):
            return fail("INVALID_LABEL", "Gold call or result has an invalid shape", index)
        tool = tools.get(call["name"])
        if tool is None:
            return fail("UNAVAILABLE_TOOL", f"Gold names ineligible tool {call['name']}", index)
        errors = target_schema_errors(tool, call["arguments"])
        if errors:
            entries.append(_entry(role, source_id, index, "SCHEMA_INVALID_TARGET", "; ".join(errors)))
        # Checked against this decision's visible text only: a later result cannot ground an ID.
        if any(not grounded(value, visible) for value in reference_values(tool["parameters"], call["arguments"])):
            entries.append(_entry(role, source_id, index, "UNGROUNDED_ID", f"{call['name']} uses an unobserved x-ref ID"))
        emit(index, {"action": "call", "name": call["name"], "arguments": call["arguments"]})
        observations.append({"name": call["name"], "arguments": call["arguments"], "result": result})
        visible += dumps(observations[-1])
        terminal = waiting_for_user(call["name"], result)
    if not terminal:
        emit(len(calls), {"action": "finish"})
    return rows, entries


# --- Tokenization ---------------------------------------------------------------

class TokenAudit(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def encode_row(tokenizer, row: JSON, context_tokens: int, max_new_tokens: int) -> JSON:
    """Exact supervised span: prompt tokens as inference sees them, then target plus EOS."""
    inputs, target = row["input"], row["target"]
    prompt = render_prompt(tokenizer, inputs, inputs["observations"])
    prompt_ids = list(tokenizer(prompt, add_special_tokens=False)["input_ids"])
    try:
        text = completion_text(target)
    except (NativeFormatError, ValueError, TypeError) as exc:
        raise TokenAudit("TARGET_RENDER", "Target cannot be rendered") from exc
    body = list(tokenizer(text, add_special_tokens=False)["input_ids"])
    eos = tokenizer.eos_token_id
    if not body or eos in body:
        raise TokenAudit("TARGET_RENDER", "Target tokens are empty or contain EOS")
    decoded = tokenizer.decode(body, skip_special_tokens=False)
    if any(token in decoded for token in tokenizer.all_special_tokens):
        raise TokenAudit("TARGET_RENDER", "Target contains special tokens the runtime rejects")
    eligible = {tool["name"] for tool in inputs["available_tools"]}
    try:
        if parse_completion(decoded, eligible) != target:
            raise TokenAudit("TARGET_RENDER", "Target does not survive tokenizer round trip")
    except NativeFormatError as exc:
        raise TokenAudit("TARGET_RENDER", "Target does not parse after tokenizer round trip") from exc
    # Tokenized apart because generation appends tokens to the prompt; both views must agree.
    if list(tokenizer(prompt + text, add_special_tokens=False)["input_ids"]) != prompt_ids + body:
        raise TokenAudit("TOKEN_BOUNDARY", "Prompt/target tokens differ when tokenized together")
    target_ids = body + [eos]
    if len(prompt_ids) + max_new_tokens > context_tokens:
        raise TokenAudit("CONTEXT_OVERFLOW", f"{len(prompt_ids)} prompt tokens leave no {max_new_tokens}-token reservation")
    if len(target_ids) > max_new_tokens:
        raise TokenAudit("OUTPUT_OVERFLOW", f"Target needs {len(target_ids)} tokens")
    return {"input_ids": prompt_ids + target_ids, "labels": [-100] * len(prompt_ids) + target_ids,
            "prompt_tokens": len(prompt_ids), "target_tokens": len(target_ids),
            "sha256": hashlib.sha256(dumps(prompt_ids + target_ids).encode("utf-8")).hexdigest()}


# --- Resolutions, identities and export -----------------------------------------

def read_resolutions(path: Path | None) -> dict[tuple[str, str], str]:
    if path is None:
        return {}
    raw = read_json(path)
    items = raw.get("resolutions") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise PipelineError("INPUT_INVALID", "Resolution file requires a resolutions list", "sft_data")
    result = {}
    for item in items:
        if (not isinstance(item, dict) or set(item) != {"source_id", "reason", "decision", "note"}
                or item["reason"] not in REASONS or item["decision"] not in {"exclude", "keep"}
                or not isinstance(item["source_id"], str) or not isinstance(item["note"], str) or not item["note"].strip()):
            raise PipelineError("INPUT_INVALID", "Each resolution needs source_id, reason, decision and a note", "sft_data")
        if item["decision"] == "keep" and item["reason"] not in KEEPABLE:
            raise PipelineError("INPUT_INVALID", f"{item['reason']} cannot be kept: no valid row exists", "sft_data")
        key = (item["source_id"], item["reason"])
        if key in result:
            raise PipelineError("INPUT_INVALID", "Duplicate resolution", "sft_data")
        result[key] = item["decision"]
    return result


def apply_resolutions(entries: list[JSON], resolutions: dict[tuple[str, str], str]) -> bool:
    """Mark one source's entries; True keeps its rows. Exclusion wins over a keep."""
    decisions = [resolutions.get((entry["source_id"], entry["reason"])) for entry in entries]
    for entry, decision in zip(entries, decisions):
        entry["status"] = {"exclude": "excluded", "keep": "kept"}.get(decision, "unresolved")
    if "exclude" in decisions:
        for entry in entries:
            entry["status"] = "excluded" if entry["status"] != "kept" else "kept"
        return False
    return all(decision == "keep" for decision in decisions)


def base_identity(config: SftConfig, *, hash_files: bool) -> JSON:
    settings = ModelSettings("qwen3", config.base_path, config.device, "bfloat16", protocol=PROTOCOL,
                             context_tokens=config.context_tokens, max_new_tokens=config.max_new_tokens)
    snapshot = inspect_snapshot(settings, planner=True)
    budget = check_parameter_budget(snapshot["parameter_count"], 0)
    result = snapshot | {"revision": config.revision, "parameter_budget": budget}
    if hash_files:
        files = model_identity(config.base_path)["files"]
        result["files_sha256"] = hashlib.sha256(dumps(files).encode("utf-8")).hexdigest()
    return result


def load_tokenizer(path: Path):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        from transformers import AutoTokenizer

        return AutoTokenizer.from_pretrained(path, local_files_only=True, trust_remote_code=False)
    except (ImportError, OSError, ValueError) as exc:
        raise PipelineError("MODEL_UNAVAILABLE", "Cannot load the local tokenizer", "sft_data") from exc


def preflight(config: SftConfig) -> JSON:
    """Metadata only: configuration, roles, overlap and snapshot; loads no model library."""
    train = read_role("train", config.train_jsonl, config.train_catalog)
    validation = read_role("validation", config.validation_jsonl, config.validation_catalog)
    if train.identity["jsonl_sha256"] == validation.identity["jsonl_sha256"]:
        raise blocked("Train and validation have identical content")
    read_resolutions(config.audit_resolutions)
    overlap = audit_overlap(train, validation)
    if overlap["status"] != "disjoint":
        raise blocked(f"Train and validation overlap: {dumps(overlap)[:300]}")
    return {"stage": "preflight", "state": "unvalidated", "train": train.identity, "validation": validation.identity,
            "overlap": overlap, "base": base_identity(config, hash_files=False)}


def _accounting(sources: int, converted: dict[str, list[JSON]], included: set[str], entries: list[JSON]) -> JSON:
    rows = [row for source in included for row in converted[source]]
    targets = Counter(row["target"].get("name", "<finish>") for row in rows)
    unresolved = {e["source_id"] for e in entries if e["status"] == "unresolved"}
    excluded = {e["source_id"] for e in entries if e["status"] == "excluded"} - unresolved
    if len(included) + len(unresolved | excluded) != sources:
        raise PipelineError("SFT_BLOCKED", "Source accounting does not balance", "sft_data")
    return {"sources": sources, "sources_with_rows": len(included), "sources_unresolved": len(unresolved),
            "sources_excluded": len(excluded), "rows": len(rows), "finish_rows": targets.get("<finish>", 0),
            "call_rows": len(rows) - targets.get("<finish>", 0),
            "clarification_rows": targets.get("sys.ask_missing_info", 0),
            "targets": dict(sorted(targets.items())), "audit_entries": len(entries),
            "audit_reasons": dict(sorted(Counter(e["reason"] for e in entries).items()))}


def export_role(data: RoleData, tokenizer, config: SftConfig, resolutions: dict) -> tuple[list[JSON], list[JSON], JSON]:
    """Rows, audit entries and accounting for one role; pure apart from tokenizer use."""
    rows_out, entries_out, converted, included, lengths = [], [], {}, set(), []
    for source in data.rows:
        rows, entries = convert_source(source, data)
        encoded = []
        for row in rows:
            try:
                encoded.append(encode_row(tokenizer, row, config.context_tokens, config.max_new_tokens))
            except TokenAudit as exc:
                entries.append(_entry(data.role, source["id"], row["provenance"]["decision_index"], exc.reason, str(exc)))
        if any(entry["reason"] not in KEEPABLE for entry in entries):
            rows = []  # All-or-nothing: an unusable decision invalidates its trajectory.
        keep = apply_resolutions(entries, resolutions) if entries else True
        converted[source["id"]] = rows
        entries_out += entries
        if keep and rows:
            for row, tokens in zip(rows, encoded):
                row["tokens"] = {"prompt": tokens["prompt_tokens"], "target": tokens["target_tokens"],
                                 "sha256": tokens["sha256"]}
                lengths.append((tokens["prompt_tokens"], tokens["target_tokens"]))
            rows_out += rows
            included.add(source["id"])
    accounting = _accounting(len(data.rows), converted, included, entries_out)
    accounting["token_lengths"] = ({"prompt_max": max(p for p, _ in lengths), "target_max": max(t for _, t in lengths),
                                    "prompt_mean": sum(p for p, _ in lengths) / len(lengths),
                                    "target_mean": sum(t for _, t in lengths) / len(lengths)} if lengths else None)
    return rows_out, entries_out, accounting


def row_line(row: JSON) -> str:
    """Original key order: schema and argument order shape the rendered prompt and target."""
    return json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _write_jsonl(path: Path, rows: Iterable[JSON]) -> str:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        sync_write(stream, "".join(row_line(row) + "\n" for row in rows))
    return digest(path)


def commit_directory(stage: Path, target: Path) -> None:
    """Replace ``target`` by a fully written sibling; readers never see a partial directory."""
    previous = target.with_name(f"{target.name}.old-{uuid.uuid4().hex}")
    if target.exists():
        os.replace(target, previous)
    os.replace(stage, target)
    if previous.exists():
        shutil.rmtree(previous, ignore_errors=True)


def prepare(config: SftConfig, *, tokenizer=None) -> JSON:
    """Write ``sft/`` with a ready or blocked manifest; blocked still exits nonzero with evidence."""
    checkpoints = config.experiment_dir / "checkpoints"
    if checkpoints.is_dir() and any(checkpoints.iterdir()):
        raise blocked("Experiment already has checkpoints; a changed export needs a new experiment")
    train = read_role("train", config.train_jsonl, config.train_catalog)
    validation = read_role("validation", config.validation_jsonl, config.validation_catalog)
    resolutions = read_resolutions(config.audit_resolutions)
    base = base_identity(config, hash_files=True)
    overlap = audit_overlap(train, validation)
    if train.identity["jsonl_sha256"] == validation.identity["jsonl_sha256"]:
        overlap["status"] = "overlap"
    tokenizer = tokenizer if tokenizer is not None else load_tokenizer(config.base_path)
    template = validate_template(tokenizer)
    # Overlap stops before expansion: no row is derived from an invalid role assignment.
    disjoint = overlap["status"] == "disjoint"
    train_rows, train_entries, train_counts = export_role(train, tokenizer, config, resolutions) if disjoint else ([], [], None)
    valid_rows, valid_entries, valid_counts = export_role(validation, tokenizer, config, resolutions) if disjoint else ([], [], None)
    entries = train_entries + valid_entries
    stale = set(resolutions) - {(e["source_id"], e["reason"]) for e in entries}
    if disjoint and stale:
        raise PipelineError("INPUT_INVALID", "Resolution matches no audit entry: " + dumps(sorted(stale))[:200], "sft_data")
    reasons = []
    if not disjoint:
        reasons.append("cross-role overlap")
    if train_counts and train_counts["sources_unresolved"]:
        reasons.append(f"{train_counts['sources_unresolved']} unresolved training sources")
    if disjoint and (not train_rows or not valid_rows):
        reasons.append("no usable rows in a role")
    config.experiment_dir.mkdir(parents=True, exist_ok=True)
    stage = config.experiment_dir / f".sft-{uuid.uuid4().hex}"
    stage.mkdir()
    try:
        files = {name: _write_jsonl(stage / name, rows) for name, rows in (
            ("train.jsonl", train_rows), ("validation.next_action.jsonl", valid_rows), ("audit.jsonl", entries))}
        manifest = {
            "schema": ROW_SCHEMA, "state": "blocked" if reasons else "ready", "blocked_reasons": reasons,
            "config_identity": config.identity(), "recipe": RECIPE_NAME, "permitted_use": config.permitted_use,
            "sources": {"train": train.identity, "validation": validation.identity},
            "resolutions_sha256": None if config.audit_resolutions is None else digest(config.audit_resolutions),
            "overlap": overlap, "accounting": {"train": train_counts, "validation": valid_counts},
            "limits": {"context_tokens": config.context_tokens, "max_new_tokens": config.max_new_tokens},
            "base": base, "protocol": {"name": PROTOCOL, "finish_text": FINISH_TEXT, "system_sha256": SYSTEM_SHA256,
                                       "template": template},
            "files_sha256": files, "code": code_identity()}
        atomic_json(stage / "export_manifest.json", manifest)
        commit_directory(stage, config.sft_dir)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    atomic_json(config.experiment_dir / "effective_config.json", config.record())
    if reasons:
        raise blocked("Export blocked: " + "; ".join(reasons))
    return {"stage": "prepare", "state": "ready", "accounting": manifest["accounting"], "overlap": overlap}


@dataclass(frozen=True)
class ReadyExport:
    manifest: JSON
    manifest_sha256: str
    train: tuple[JSON, ...]
    validation: tuple[JSON, ...]


def _read_rows(path: Path, role: str) -> tuple[JSON, ...]:
    rows = []
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                row = loads(line)
                if (not isinstance(row, dict) or row.get("schema") != ROW_SCHEMA
                        or row["provenance"]["role"] != role or not isinstance(row["input"]["observations"], list)):
                    raise ValueError("Unexpected export row")
                completion_text(row["target"])
                rows.append(row)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise PipelineError("SFT_IDENTITY", f"{role} export rows are invalid", "sft_data") from exc
    return tuple(rows)


def load_ready_export(config: SftConfig) -> ReadyExport:
    """Reject anything except a ready export matching this configuration and its current sources."""
    path = config.sft_dir / "export_manifest.json"
    if not path.is_file():
        raise blocked("No prepared export: run the prepare stage")
    manifest = read_json(path, "SFT_IDENTITY")
    if not isinstance(manifest, dict) or manifest.get("state") != "ready":
        raise blocked("Prepared export is not ready")
    if manifest.get("config_identity") != config.identity():
        raise PipelineError("SFT_IDENTITY", "Export was prepared with a different recipe or limits", "sft_data")
    for role, jsonl, catalog in (("train", config.train_jsonl, config.train_catalog),
                                 ("validation", config.validation_jsonl, config.validation_catalog)):
        source = manifest["sources"][role]
        if digest(jsonl) != source["jsonl_sha256"] or digest(catalog) != source["catalog_sha256"]:
            raise PipelineError("SFT_IDENTITY", f"{role} sources changed after export", "sft_data")
    for name, expected in manifest["files_sha256"].items():
        if not (config.sft_dir / name).is_file() or digest(config.sft_dir / name) != expected:
            raise PipelineError("SFT_IDENTITY", f"Export file {name} is missing or changed", "sft_data")
    train = _read_rows(config.sft_dir / "train.jsonl", "train")
    validation = _read_rows(config.sft_dir / "validation.next_action.jsonl", "validation")
    counts = manifest["accounting"]
    if len(train) != counts["train"]["rows"] or len(validation) != counts["validation"]["rows"]:
        raise PipelineError("SFT_IDENTITY", "Export row counts disagree with the manifest", "sft_data")
    return ReadyExport(manifest, digest(path), train, validation)
