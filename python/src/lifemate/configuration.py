"""Strict integration TOML v1, known CLI overrides and pre-environment preflight.

Nothing here loads model weights, imports model libraries or creates a ToolEnv.
"""
from __future__ import annotations

import copy
import hashlib
import math
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import (JSON, Limits, PipelineError, PreparedDataset, RunConfig,
                        integration_deadline, integration_soft_deadline)
from .jsonio import digest, dumps, loads, safe_id

SCHEMA_VERSION = 1
PROTOCOL = "qwen-native-v1"
DEVICE = re.compile(r"cpu|cuda(:[0-9]{1,2})?")
DTYPES = ("float32", "float16", "bfloat16")
# TOML v1 schema: section -> key -> (accepted types, required).
SCHEMA: dict[str, dict[str, tuple[tuple[type, ...], bool]]] = {
    "asr": {"backend": ((str,), True), "model_path": ((str,), True), "device": ((str,), True),
            "dtype": ((str,), True), "offload": ((bool,), False)},
    "planner": {"backend": ((str,), True), "protocol": ((str,), True), "model_path": ((str,), True),
                "device": ((str,), True), "dtype": ((str,), True), "offload": ((bool,), False),
                "context_tokens": ((int,), True), "max_new_tokens": ((int,), True)},
    "execution": {"timeout_seconds": ((int, float), True), "max_steps": ((int,), True),
                  "soft_timeout_seconds": ((int, float), False),
                  "startup_timeout_seconds": ((int, float), True), "recovery_attempts": ((int,), True),
                  "seed": ((int,), True)},
    "data": {"root": ((str,), True), "split": ((str,), True), "mode": ((str,), True),
             "runtime_dir": ((str,), True), "sample_ids_file": ((str,), False),
             "select_all": ((bool,), False)},
    "output": {"root": ((str,), True), "debug_payloads": ((bool,), False)},
}
# Known CLI overrides map onto existing TOML fields only.
OVERRIDES = {"asr_model": ("asr", "model_path"), "planner_model": ("planner", "model_path")}


def invalid(message: str, code: str = "INPUT_INVALID") -> PipelineError:
    return PipelineError(code, message, "configuration")


@dataclass(frozen=True)
class ModelSettings:
    backend: str
    model_path: Path
    device: str
    dtype: str
    offload: bool = False
    protocol: str | None = None
    context_tokens: int | None = None
    max_new_tokens: int | None = None


@dataclass(frozen=True)
class IntegrationConfig:
    asr: ModelSettings | None
    planner: ModelSettings
    timeout_seconds: float
    max_steps: int
    startup_timeout_seconds: float
    recovery_attempts: int
    seed: int
    data_root: Path
    split: str
    mode: str
    runtime_dir: Path
    sample_ids_file: Path | None
    select_all: bool
    output_root: Path
    debug_payloads: bool
    source: Path | None = None
    soft_timeout_seconds: float = 26.0

    @property
    def limits(self) -> Limits:
        return Limits(self.max_steps, self.timeout_seconds, self.planner.context_tokens,
                      self.planner.max_new_tokens)

    def record(self) -> JSON:
        """Effective configuration in TOML v1 shape with absolute paths."""
        def model(settings: ModelSettings, planner: bool) -> JSON:
            value = {"backend": settings.backend, "model_path": settings.model_path.as_posix(),
                     "device": settings.device, "dtype": settings.dtype, "offload": settings.offload}
            if planner:
                value.update(protocol=settings.protocol, context_tokens=settings.context_tokens,
                             max_new_tokens=settings.max_new_tokens)
            return value

        data = {"root": self.data_root.as_posix(), "split": self.split, "mode": self.mode,
                "runtime_dir": self.runtime_dir.as_posix(), "select_all": self.select_all}
        if self.sample_ids_file is not None:
            data["sample_ids_file"] = self.sample_ids_file.as_posix()
        value = {"schema_version": SCHEMA_VERSION, "planner": model(self.planner, True),
                 "execution": {"timeout_seconds": self.timeout_seconds, "max_steps": self.max_steps,
                               "soft_timeout_seconds": self.soft_timeout_seconds,
                               "startup_timeout_seconds": self.startup_timeout_seconds,
                               "recovery_attempts": self.recovery_attempts, "seed": self.seed},
                 "data": data,
                 "output": {"root": self.output_root.as_posix(), "debug_payloads": self.debug_payloads}}
        if self.asr is not None:
            value["asr"] = model(self.asr, False)
        return value

    def fingerprint(self) -> str:
        return hashlib.sha256(dumps(self.record()).encode("utf-8")).hexdigest()


def _path(value: str, base: Path, name: str) -> Path:
    if not value or "\x00" in value:
        raise invalid(f"{name} must be a nonempty path")
    path = Path(value)
    return (path if path.is_absolute() else base / path).resolve()


def _check_shape(raw: Any) -> None:
    if not isinstance(raw, dict):
        raise invalid("Configuration must be a TOML table")
    unknown = set(raw) - set(SCHEMA) - {"schema_version"}
    if unknown:
        raise invalid("Unknown configuration section(s): " + ", ".join(sorted(map(str, unknown)))[:200])
    version = raw.get("schema_version")
    if type(version) is not int or version != SCHEMA_VERSION:
        raise invalid("schema_version must be 1")
    for section, keys in SCHEMA.items():
        if section not in raw:
            if section == "asr":
                continue  # Required later for audio mode only.
            raise invalid(f"Missing [{section}] section")
        table = raw[section]
        if not isinstance(table, dict):
            raise invalid(f"[{section}] must be a table")
        unknown = set(table) - set(keys)
        if unknown:
            raise invalid(f"Unknown key(s) in [{section}]: " + ", ".join(sorted(map(str, unknown)))[:200])
        for key, (types, required) in keys.items():
            if key not in table:
                if required:
                    raise invalid(f"Missing {section}.{key}")
                continue
            value = table[key]
            # bool is an int subclass; never accept it where a number is required.
            if isinstance(value, bool) and bool not in types or not isinstance(value, types):
                raise invalid(f"Invalid type for {section}.{key}")


def _model(table: JSON, base: Path, *, planner: bool) -> ModelSettings:
    name = "planner" if planner else "asr"
    backend, device, dtype = table["backend"], table["device"], table["dtype"]
    if backend != ("qwen3" if planner else "whisper"):
        raise invalid(f"Unsupported {name}.backend")
    if not DEVICE.fullmatch(device):
        raise invalid(f"{name}.device must be cpu, cuda or cuda:N")
    if dtype not in DTYPES:
        raise invalid(f"{name}.dtype must be one of float32, float16, bfloat16")
    if device == "cpu" and dtype == "float16":
        raise invalid(f"{name}: float16 inference is not supported on CPU")
    offload = table.get("offload", False)
    if offload and device == "cpu":
        raise invalid(f"{name}.offload requires a CUDA device")
    settings = dict(backend=backend, model_path=_path(table["model_path"], base, f"{name}.model_path"),
                    device=device, dtype=dtype, offload=offload)
    if planner:
        if table["protocol"] != PROTOCOL:
            raise invalid("planner.protocol must be qwen-native-v1")
        context, output = table["context_tokens"], table["max_new_tokens"]
        if not 0 < output < context <= 16_384:
            raise invalid("Require 0 < max_new_tokens < context_tokens <= 16384")
        settings.update(protocol=PROTOCOL, context_tokens=context, max_new_tokens=output)
    return ModelSettings(**settings)


def parse_config(raw: Any, base: Path, *, source: Path | None = None) -> IntegrationConfig:
    """Validate a TOML v1 mapping; relative paths resolve against ``base``."""
    _check_shape(raw)
    execution, data, output = raw["execution"], raw["data"], raw["output"]
    timeout = integration_deadline(execution["timeout_seconds"])
    soft_timeout = integration_soft_deadline(execution.get("soft_timeout_seconds", 26.0), timeout)
    startup = execution["startup_timeout_seconds"]
    if not math.isfinite(startup) or not 0 < startup <= 3600:
        raise invalid("execution.startup_timeout_seconds must be in (0, 3600]")
    if not 0 < execution["max_steps"] <= 64:
        raise invalid("execution.max_steps must be in [1, 64]")
    if execution["recovery_attempts"] not in (0, 1):
        raise invalid("execution.recovery_attempts must be 0 or 1")
    if not 0 <= execution["seed"] < 2**32:
        raise invalid("execution.seed must be a 32-bit unsigned integer")
    split, mode = data["split"], data["mode"]
    if split not in {"train", "public_test"}:
        raise invalid("data.split must be train or public_test")
    if mode not in {"audio", "transcript"}:
        raise invalid("data.mode must be audio or transcript")
    if mode == "transcript" and split != "train":
        raise invalid("Transcript mode is a Train-only diagnostic")
    select_all = data.get("select_all", False)
    if ("sample_ids_file" in data) == select_all:
        raise invalid("Set exactly one of data.sample_ids_file or data.select_all = true")
    if mode == "audio" and "asr" not in raw:
        raise invalid("Audio mode requires an [asr] section")
    asr = _model(raw["asr"], base, planner=False) if "asr" in raw else None
    planner = _model(raw["planner"], base, planner=True)
    data_root = _path(data["root"], base, "data.root")
    runtime_dir = _path(data["runtime_dir"], base, "data.runtime_dir")
    output_root = _path(output["root"], base, "output.root")
    for inside in (data_root, runtime_dir, planner.model_path, *(() if asr is None else (asr.model_path,))):
        if output_root == inside or output_root.is_relative_to(inside):
            raise invalid("output.root must be outside model, data and runtime inputs")
    return IntegrationConfig(
        asr=asr, planner=planner, timeout_seconds=timeout, max_steps=execution["max_steps"],
        startup_timeout_seconds=float(startup), recovery_attempts=execution["recovery_attempts"],
        seed=execution["seed"], data_root=data_root, split=split, mode=mode, runtime_dir=runtime_dir,
        sample_ids_file=(_path(data["sample_ids_file"], base, "data.sample_ids_file")
                         if "sample_ids_file" in data else None),
        select_all=select_all, output_root=output_root,
        debug_payloads=output.get("debug_payloads", False), source=source,
        soft_timeout_seconds=soft_timeout)


def apply_overrides(raw: JSON, overrides: JSON) -> JSON:
    """Apply known CLI overrides to existing TOML fields; reject anything else."""
    result = copy.deepcopy(raw)
    for key, value in overrides.items():
        if value is None:
            continue
        if key == "device":
            for section in ("asr", "planner"):
                if isinstance(result.get(section), dict):
                    result[section]["device"] = value
            continue
        if key not in OVERRIDES:
            raise invalid(f"Unknown override {key}")
        section, field = OVERRIDES[key]
        if not isinstance(result.get(section), dict):
            raise invalid(f"Override targets absent [{section}] section")
        result[section][field] = str(value)
    return result


def load_config(path: Path, overrides: JSON | None = None) -> IntegrationConfig:
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise invalid("Configuration file is unreadable") from exc
    except tomllib.TOMLDecodeError as exc:
        raise invalid("Configuration is not valid TOML") from exc
    return parse_config(apply_overrides(raw, overrides or {}), path.resolve().parent, source=path.resolve())


def read_effective(path: Path) -> IntegrationConfig:
    """Re-validate the supervisor's effective JSON record (absolute paths)."""
    try:
        raw = loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise invalid("Effective configuration is unreadable") from exc
    return parse_config(raw, path.resolve().parent)


def selected_ids(config: IntegrationConfig) -> tuple[str, ...]:
    if config.select_all:
        return ()
    try:
        lines = config.sample_ids_file.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise invalid("Selection file is unreadable", "ASSET_MISSING") from exc
    ids = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    for value in ids:
        safe_id(value)
    if not ids or len(set(ids)) != len(ids):
        raise invalid("Selection file is empty or has duplicate IDs")
    return tuple(ids)


def run_config(config: IntegrationConfig) -> RunConfig:
    """Bridge into the shared dataset/runtime preflight; legacy fields stay default."""
    ids = selected_ids(config)
    return RunConfig(
        data_root=config.data_root, runtime_dir=config.runtime_dir, split=config.split,
        input_mode=config.mode, selected_ids=ids, select_all=config.select_all,
        planner_model=config.planner.model_path,
        asr_model=config.asr.model_path if config.asr and config.mode == "audio" else None,
        device="cuda" if config.planner.device.startswith("cuda") else "cpu",
        trace_payloads=config.debug_payloads, limits=config.limits, seed=config.seed)


# --- Snapshot preflight: metadata only, no weights are loaded. ---

def _json_file(path: Path, what: str) -> JSON:
    try:
        value = loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise invalid(f"{what} is missing or invalid", "MODEL_UNAVAILABLE") from exc
    if not isinstance(value, dict):
        raise invalid(f"{what} must be a JSON object", "MODEL_UNAVAILABLE")
    return value


def safetensors_parameters(path: Path) -> int | None:
    """Exact stored parameter count from safetensors headers; None without them."""
    files = sorted(path.glob("*.safetensors"))
    if not files:
        return None
    total = 0
    for file in files:
        try:
            with file.open("rb") as stream:
                size = int.from_bytes(stream.read(8), "little")
                if not 0 < size <= 100 * 1024 * 1024:
                    raise ValueError("Invalid header size")
                header = loads(stream.read(size).decode("utf-8"))
            for key, tensor in header.items():
                if key != "__metadata__":
                    total += math.prod(int(n) for n in tensor["shape"])
        except (OSError, ValueError, UnicodeError, KeyError, TypeError) as exc:
            raise invalid("Model safetensors header is invalid", "MODEL_UNAVAILABLE") from exc
    return total


def chat_template(path: Path) -> str:
    template_file = path / "chat_template.jinja"
    if template_file.is_file():
        return template_file.read_text(encoding="utf-8")
    template = _json_file(path / "tokenizer_config.json", "Planner tokenizer_config.json").get("chat_template")
    if isinstance(template, list):  # Named templates: native tool use needs the default one.
        template = next((t.get("template") for t in template
                         if isinstance(t, dict) and t.get("name") == "default"), None)
    if not isinstance(template, str) or not template:
        raise invalid("Planner snapshot lacks a chat template", "MODEL_UNAVAILABLE")
    return template


def inspect_snapshot(settings: ModelSettings, *, planner: bool) -> JSON:
    path = settings.model_path
    if not path.is_dir():
        raise invalid("Model snapshot directory is missing", "MODEL_UNAVAILABLE")
    config = _json_file(path / "config.json", "Model config.json")
    if not any(path.glob("*.safetensors")) and not any(path.glob("*.bin")):
        raise invalid("Model snapshot has no weight files", "MODEL_UNAVAILABLE")
    tokenizer = (path / "tokenizer.json").is_file() or (path / "vocab.json").is_file()
    if not tokenizer or not (path / "tokenizer_config.json").is_file():
        raise invalid("Model snapshot lacks tokenizer files", "MODEL_UNAVAILABLE")
    result: JSON = {"model_type": config.get("model_type"),
                    "parameter_count": safetensors_parameters(path)}
    if planner:
        if config.get("model_type") != "qwen3":
            raise invalid("Planner must be a Qwen3 causal LM snapshot", "MODEL_UNAVAILABLE")
        positions = config.get("max_position_embeddings")
        if type(positions) is not int or positions < settings.context_tokens:
            raise invalid("Planner context_tokens exceeds the model position limit", "MODEL_UNAVAILABLE")
        template = chat_template(path)
        # The native protocol renders tools and actual results through the template.
        for marker in ("tools", "<tool_call>", "</tool_call>", "<tool_response>"):
            if marker not in template:
                raise invalid("Planner chat template lacks native tool-call support", "MODEL_UNAVAILABLE")
        if not _json_file(path / "tokenizer_config.json", "Planner tokenizer_config.json").get("eos_token"):
            raise invalid("Planner tokenizer declares no EOS token", "MODEL_UNAVAILABLE")
        result["template_sha256"] = hashlib.sha256(template.encode("utf-8")).hexdigest()
    else:
        if config.get("model_type") != "whisper":
            raise invalid("ASR must be a Whisper-family snapshot", "MODEL_UNAVAILABLE")
        if not (path / "preprocessor_config.json").is_file():
            raise invalid("ASR snapshot lacks preprocessor_config.json", "MODEL_UNAVAILABLE")
    return result


def check_parameter_budget(planner: int | None, asr: int | None) -> JSON:
    if planner is not None and planner >= 5_000_000_000:
        raise invalid("Planner must have fewer than 5B parameters", "MODEL_UNAVAILABLE")
    known = [n for n in (planner, asr) if n is not None]
    if sum(known) >= 6_000_000_000:
        raise invalid("Deployed models must have fewer than 6B parameters", "MODEL_UNAVAILABLE")
    complete = planner is not None and asr is not None
    return {"planner": planner, "asr": asr, "total": sum(known) if complete else None,
            "status": "checked_from_headers" if complete else "verified_after_load"}


@dataclass(frozen=True)
class Preflight:
    config: IntegrationConfig
    dataset: PreparedDataset
    runtime: Any
    identity: JSON
    run_sha256: str


def preflight(config: IntegrationConfig, *, runtime_loader=None, hash_models: bool = True) -> Preflight:
    """Validate everything knowable before workers, models or environments exist."""
    from .dataset import preflight as data_preflight
    from .provenance import code_identity, model_identity, package_versions
    from .runtime import load_runtime

    audio = config.mode == "audio"
    planner = inspect_snapshot(config.planner, planner=True)
    asr = inspect_snapshot(config.asr, planner=False) if audio else None
    # Transcript diagnostics deploy no ASR; audio counts stay unverified until load without headers.
    budget = check_parameter_budget(planner["parameter_count"], asr["parameter_count"] if audio else 0)
    legacy = run_config(config)
    dataset = data_preflight(legacy)
    runtime = (runtime_loader or load_runtime)(legacy, dataset)
    identity = {
        "config_sha256": config.fingerprint(), "protocol": PROTOCOL,
        "planner": planner | {"files": model_identity(config.planner.model_path)["files"] if hash_models else None},
        "asr": (asr | {"files": model_identity(config.asr.model_path)["files"] if hash_models else None}
                if audio else None),
        "parameter_budget": budget,
        "dataset": {k: dataset.metadata[k] for k in ("dataset_sha256", "catalog_sha256", "catalog_version",
                                                       "selected_ids", "coverage_scope")},
        "runtime_source_sha256": runtime.metadata.get("source_sha256"),
        "code": code_identity(), "packages": package_versions(),
    }
    if config.sample_ids_file is not None:
        identity["dataset"]["selection_sha256"] = digest(config.sample_ids_file)
    run_sha = hashlib.sha256(dumps(identity).encode("utf-8")).hexdigest()
    return Preflight(config, dataset, runtime, identity, run_sha)
