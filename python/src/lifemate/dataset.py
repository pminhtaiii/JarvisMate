"""Preflight selected visible records; hidden files receive existence checks only."""
from __future__ import annotations

import copy
import math
import wave
from datetime import datetime
from pathlib import Path, PurePosixPath

from .contracts import ASR, Deadline, JSON, PipelineError, PreparedDataset, RunConfig, SampleInput
from .jsonio import contained, digest, loads, read_json, safe_id, visible_path


def require(condition: bool, message: str, code: str = "INPUT_INVALID") -> None:
    if not condition:
        raise PipelineError(code, message)


def text(value, name: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"Missing/invalid {name}")
    return value


def validate_calls(calls) -> None:
    require(isinstance(calls, list), "Historical tool_calls must be a list")
    for call in calls:
        require(isinstance(call, dict) and isinstance(call.get("name"), str)
                and isinstance(call.get("arguments"), dict), "Invalid historical call")


def validate_catalog(catalog: JSON) -> dict[str, JSON]:
    code = "CATALOG_INVALID"
    require(isinstance(catalog, dict) and isinstance(catalog.get("schema_version"), str)
            and isinstance(catalog.get("apps"), list) and bool(catalog["apps"]),
            "Catalog requires version and apps", code)
    tools, apps = {}, set()
    for app in catalog["apps"]:
        require(isinstance(app, dict) and isinstance(app.get("id"), str)
                and isinstance(app.get("tools"), list), "Invalid catalog app", code)
        require(app["id"] not in apps, "Duplicate catalog app", code)
        apps.add(app["id"])
        for tool in app["tools"]:
            require(isinstance(tool, dict), "Invalid catalog tool", code)
            name, params = tool.get("name"), tool.get("parameters")
            require(isinstance(name, str) and name.startswith(app["id"] + ".")
                    and tool.get("app") == app["id"] and name not in tools
                    and isinstance(tool.get("kind"), str) and tool["kind"] in {"read", "write", "meta"}
                    and isinstance(tool.get("description"), str), "Invalid tool definition", code)
            require(isinstance(params, dict) and params.get("type") == "object"
                    and isinstance(params.get("properties"), dict), "Invalid tool parameters", code)
            props, required = params["properties"], params.get("required", [])
            require(isinstance(required, list)
                    and all(isinstance(k, str) and k in props for k in required),
                    "Invalid required parameters", code)
            require(all(isinstance(p, dict) for p in props.values()), "Invalid property schema", code)
            groups = params.get("x-one-of", [])
            require(isinstance(groups, list) and all(isinstance(g, list) and g
                    and all(isinstance(k, str) and k in props for k in g) for g in groups),
                    "Invalid alternative parameter groups", code)
            tools[name] = tool
    require("sys.ask_missing_info" in tools, "Missing system-tool schema", code)
    return tools


def wav_info(path: Path) -> JSON:
    try:
        visible_path(path)
        with wave.open(str(path), "rb") as wav:
            require(wav.getcomptype() == "NONE" and wav.getnchannels() == 1
                    and wav.getsampwidth() == 2 and wav.getframerate() == 16000,
                    "Audio must be mono 16-kHz 16-bit PCM WAV")
            frames = wav.getnframes()
            seconds = frames / 16000
            require(0 < seconds <= 30, "Baseline supports nonempty WAVs up to 30 seconds")
            require(len(wav.readframes(frames)) == frames * wav.getnchannels() * wav.getsampwidth(),
                    "Audio WAV payload is truncated")
            return {"frames": frames, "seconds": seconds}
    except (OSError, EOFError, wave.Error) as exc:
        raise PipelineError("INPUT_INVALID", "Invalid/unreadable WAV") from exc


def audio_path(base: Path, value, required: bool) -> Path:
    text(value, "audio path")
    parts = PurePosixPath(value)
    require(bool(parts.parts) and parts.parts[0] == "audio" and parts.suffix.lower() == ".wav",
            "Audio must reference a WAV under audio/")
    result = contained(base, value, must_exist=required)
    root = base.resolve() / "audio"
    require(root.resolve() == root and result.is_relative_to(root),
            "Audio links must stay inside the split's audio directory")
    if required:
        wav_info(result)
    return result


def normalize_record(row: JSON, config: RunConfig, specs: dict[str, JSON]) -> SampleInput:
    sample_id = safe_id(row["id"])
    base = (config.data_root / config.split).resolve()
    ctx = row.get("context")
    require(isinstance(ctx, dict), "Missing context")
    for name in ("current_time", "timezone"):
        text(ctx.get(name), name)
    try:
        now = datetime.fromisoformat(ctx["current_time"].replace("Z", "+00:00"))
        require(now.tzinfo is not None, "current_time requires timezone offset")
    except ValueError as exc:
        raise PipelineError("INPUT_INVALID", "Invalid current_time") from exc
    loc, profile, installed = ctx.get("location"), ctx.get("user_profile"), ctx.get("installed_apps")
    require(isinstance(loc, dict) and isinstance(profile, dict)
            and isinstance(installed, dict), "Invalid location/profile/installed_apps")
    for key, bound in (("lat", 90), ("lng", 180)):
        n = loc.get(key)
        require(type(n) in (int, float) and math.isfinite(n) and abs(n) <= bound,
                "Invalid location coordinate")
    for key in ("name", "home_address", "work_address", "city"):
        text(profile.get(key), key)
    names = []
    for app, info in installed.items():
        require(isinstance(info, dict) and isinstance(info.get("tools"), list),
                "Invalid installed app")
        for name in info["tools"]:
            require(isinstance(name, str) and name in specs and specs[name]["app"] == app,
                    "Declared tool is absent from matching app/catalog", "CATALOG_INVALID")
            require(name not in names, "Duplicate declared tool", "CATALOG_INVALID")
            names.append(name)
    if "sys.ask_missing_info" not in names:
        names.append("sys.ask_missing_info")
    audio_mode = config.input_mode == "audio"
    audio = audio_path(base, row.get("audio"), audio_mode)
    history = row.get("history")
    require(isinstance(history, list), "History must be a list")
    normalized = []
    for index, turn in enumerate(history):
        require(isinstance(turn, dict) and turn.get("role") == ("user" if index % 2 == 0 else "assistant"),
                "History must alternate user and assistant")
        if turn["role"] == "user":
            path = audio_path(base, turn.get("audio"), audio_mode)
            entry = {"role": "user", "audio": path}
            if not audio_mode:
                entry["text"] = text(turn.get("audio_text"), "historical transcript")
        else:
            entry = {"role": "assistant", "text": text(turn.get("text"), "assistant text")}
            if "tool_calls" in turn:
                validate_calls(turn["tool_calls"])
                entry["tool_calls"] = copy.deepcopy(turn["tool_calls"])
            if "tool_results" in turn:
                require(isinstance(turn["tool_results"], list)
                        and all(isinstance(r, dict) for r in turn["tool_results"]),
                        "Invalid historical results")
                if "tool_calls" in turn:
                    require(len(turn["tool_calls"]) == len(turn["tool_results"]),
                            "Historical calls/results length mismatch")
                entry["tool_results"] = copy.deepcopy(turn["tool_results"])
        normalized.append(entry)
    require(len(history) % 2 == 0, "History must end with assistant")
    # Resolve the path and check existence only. The original runtime owns reading it.
    contained(base, f"{config.split}_environment/{sample_id}/state.json", allow_environment=True)
    context = {"current_time": ctx["current_time"], "timezone": ctx["timezone"],
               "location": {k: loc[k] for k in ("lat", "lng")},
               "user_profile": {k: profile[k] for k in ("name", "home_address", "work_address", "city")},
               "installed_apps": {app: {"tools": list(info["tools"])} for app, info in installed.items()}}
    return SampleInput(sample_id, context, tuple(normalized),
                       tuple(copy.deepcopy(specs[n]) for n in names), config.input_mode,
                       audio, None if audio_mode else text(row.get("audio_text"), "current transcript"))


def preflight(config: RunConfig) -> PreparedDataset:
    base = config.data_root / config.split
    require(base.is_dir(), "Split directory is missing", "ASSET_MISSING")
    jsonl = contained(base, f"{config.split}.jsonl")
    catalog_path = contained(base, f"{config.split}_tools_catalog.json")
    catalog = read_json(catalog_path, "CATALOG_INVALID")
    specs = validate_catalog(catalog)
    index = {}
    try:
        with jsonl.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                require(len(line.encode("utf-8")) <= 4 * 1024 * 1024, "Dataset row is too large")
                row = loads(line)
                require(isinstance(row, dict), "Dataset row must be an object")
                sample_id = safe_id(row.get("id"))
                require(sample_id not in index, "Duplicate dataset ID")
                index[sample_id] = row
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        raise PipelineError("INPUT_INVALID", "Dataset JSONL is unreadable or invalid") from exc
    selected = set(index) if config.select_all else set(config.selected_ids)
    require(bool(selected) and selected <= index.keys(), "Selection is empty or contains unknown IDs")
    samples = tuple(normalize_record(row, config, specs) for key, row in index.items() if key in selected)
    return PreparedDataset(samples, catalog, {
        "split": config.split, "input_mode": config.input_mode,
        "selected_ids": [s.id for s in samples], "selected_count": len(samples),
        "total_dataset_ids": len(index), "coverage_scope": "full_split" if len(samples) == len(index) else "subset",
        "dataset_sha256": digest(jsonl), "catalog_sha256": digest(catalog_path),
        "catalog_version": catalog["schema_version"],
    })


def prepare_request(sample: SampleInput, asr: ASR | None, deadline: Deadline) -> JSON:
    if sample.mode == "audio":
        require(asr is not None, "Audio mode requires an ASR adapter", "MODEL_UNAVAILABLE")
    history = []
    for turn in sample.history:
        deadline.remaining()
        if turn["role"] == "user":
            value = (asr.transcribe(turn["audio"], deadline.remaining())
                     if sample.mode == "audio" and asr is not None else turn.get("text"))
            history.append({"role": "user", "text": text(value, "prepared history transcript")})
        else:
            history.append(copy.deepcopy(turn))
    deadline.remaining()
    if sample.mode == "audio":
        require(asr is not None, "Audio mode requires an ASR adapter", "MODEL_UNAVAILABLE")
        request = asr.transcribe(sample.audio, deadline.remaining())
    else:
        request = sample.text
    deadline.remaining()
    return {"request": text(request, "prepared request"), "context": copy.deepcopy(sample.context),
            "history": history, "available_tools": copy.deepcopy(list(sample.tools))}
