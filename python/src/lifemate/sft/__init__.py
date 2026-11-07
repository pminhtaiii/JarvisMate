"""Strict planner SFT configuration and the fixed recipe (specs/003-planner-sft-baseline).

Imports no model library, so preflight and the inference environment stay independent
of the training extra. ``SFT_*`` failures are bounded ``PipelineError`` records.
"""
from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..contracts import JSON, PipelineError
from ..jsonio import dumps

SCHEMA_VERSION = 1
RECIPE_NAME = "qlora-baseline-v1"
SEED = 20261027
EFFECTIVE_BATCH = 16
# The agreed recipe is a constant, not configuration; a change is an explicit code revision.
RECIPE: JSON = {
    "name": RECIPE_NAME, "base_quantization": "nf4", "double_quant": True, "compute_dtype": "bfloat16",
    "lora_targets": ["q_proj", "k_proj", "v_proj", "o_proj"], "lora_rank": 8, "lora_alpha": 16,
    "lora_dropout": 0.05, "lora_bias": "none", "learning_rate": 1e-4, "betas": [0.9, 0.999], "eps": 1e-8,
    "weight_decay": 0.0, "warmup_updates": 25, "updates": 500, "evaluate_every": 100,
    "effective_batch": EFFECTIVE_BATCH, "seed": SEED, "export_dtype": "float16",
    "selection": "lowest finite validation NLL among fully covered candidates; earlier update on exact tie",
}
TEST_DIRECTORIES = frozenset({"public_test", "private_test"})
DEVICE = re.compile(r"cuda(:[0-9]{1,2})?")
# TOML v1 schema: section -> key -> (accepted type, required).
SCHEMA: dict[str, dict[str, tuple[type, bool]]] = {
    "data": {"train_jsonl": (str, True), "train_catalog": (str, True), "train_role": (str, True),
             "validation_jsonl": (str, True), "validation_catalog": (str, True), "validation_role": (str, True),
             "permitted_use": (str, True), "audit_resolutions": (str, False)},
    "model": {"base_path": (str, True), "revision": (str, False)},
    "training": {"recipe": (str, True), "device": (str, True), "seed": (int, True),
                 "microbatch": (int, True), "accumulation": (int, True)},
    "limits": {"context_tokens": (int, True), "max_new_tokens": (int, True)},
    "output": {"experiment_dir": (str, True)},
}
# CLI overrides touch only paths, the selected device, batch factors and output (contracts/training.md).
OVERRIDES = {"train_jsonl": ("data", "train_jsonl"), "train_catalog": ("data", "train_catalog"),
             "validation_jsonl": ("data", "validation_jsonl"), "validation_catalog": ("data", "validation_catalog"),
             "base_path": ("model", "base_path"), "device": ("training", "device"),
             "microbatch": ("training", "microbatch"), "accumulation": ("training", "accumulation"),
             "experiment_dir": ("output", "experiment_dir")}


def invalid(message: str, code: str = "INPUT_INVALID") -> PipelineError:
    return PipelineError(code, message, "sft_configuration")


@dataclass(frozen=True)
class SftConfig:
    train_jsonl: Path
    train_catalog: Path
    validation_jsonl: Path
    validation_catalog: Path
    permitted_use: str
    audit_resolutions: Path | None
    base_path: Path
    revision: str | None
    device: str
    microbatch: int
    accumulation: int
    context_tokens: int
    max_new_tokens: int
    experiment_dir: Path

    @property
    def sft_dir(self) -> Path:
        return self.experiment_dir / "sft"

    def record(self) -> JSON:
        """Effective configuration, recorded in ``effective_config.json``."""
        def text(path):
            return None if path is None else path.as_posix()

        return {"schema_version": SCHEMA_VERSION, "recipe": RECIPE,
                "data": {"train_jsonl": text(self.train_jsonl), "train_catalog": text(self.train_catalog),
                         "validation_jsonl": text(self.validation_jsonl),
                         "validation_catalog": text(self.validation_catalog),
                         "permitted_use": self.permitted_use, "audit_resolutions": text(self.audit_resolutions)},
                "model": {"base_path": text(self.base_path), "revision": self.revision},
                "training": {"device": self.device, "microbatch": self.microbatch,
                             "accumulation": self.accumulation},
                "limits": {"context_tokens": self.context_tokens, "max_new_tokens": self.max_new_tokens},
                "output": {"experiment_dir": text(self.experiment_dir)}}

    def identity(self) -> str:
        """Run-defining settings only; hosts may differ in paths, device and batch factors.

        Inputs are identified by content in the export manifest, and every factorization
        trains the same 16-example objective.
        """
        value = {"schema_version": SCHEMA_VERSION, "recipe": RECIPE, "permitted_use": self.permitted_use,
                 "revision": self.revision, "context_tokens": self.context_tokens,
                 "max_new_tokens": self.max_new_tokens}
        return hashlib.sha256(dumps(value).encode("utf-8")).hexdigest()


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
    if type(raw.get("schema_version")) is not int or raw["schema_version"] != SCHEMA_VERSION:
        raise invalid(f"schema_version must be {SCHEMA_VERSION}")
    for section, keys in SCHEMA.items():
        table = raw.get(section)
        if not isinstance(table, dict):
            raise invalid(f"Missing [{section}] section")
        unknown = set(table) - set(keys)
        if unknown:
            raise invalid(f"Unknown key(s) in [{section}]: " + ", ".join(sorted(map(str, unknown)))[:200])
        for key, (kind, required) in keys.items():
            if key not in table:
                if required:
                    raise invalid(f"Missing {section}.{key}")
            elif type(table[key]) is not kind:  # Exact: bool is an int subclass.
                raise invalid(f"Invalid type for {section}.{key}")


def _reject_test_data(path: Path, name: str) -> None:
    # Whole path components: the supplied bundle directory "train+public_test" holds Train too.
    if any(part.lower() in TEST_DIRECTORIES for part in path.parts) or path.name.lower().startswith(
            ("public_test", "private_test")):
        raise invalid(f"{name} points at competition test data, which is excluded from tuning")
    if any(part.lower().endswith(("_environment", "_enviroment")) for part in path.parts):
        raise invalid(f"{name} points inside an environment directory")


def parse_config(raw: Any, base: Path) -> SftConfig:
    """Validate a TOML mapping; relative paths resolve against ``base``."""
    _check_shape(raw)
    data, model, training, limits = raw["data"], raw["model"], raw["training"], raw["limits"]
    if data["train_role"] != "train" or data["validation_role"] != "validation":
        raise invalid("Data roles must be train and validation; competition test is not a tuning role")
    if not data["permitted_use"].strip():
        raise invalid("data.permitted_use must declare the permitted development use")
    if training["recipe"] != RECIPE_NAME:
        raise invalid(f"training.recipe must be {RECIPE_NAME}")
    if training["seed"] != SEED:
        raise invalid(f"training.seed must be the recipe seed {SEED}")
    if not DEVICE.fullmatch(training["device"]):
        raise invalid("training.device must select one GPU: cuda or cuda:N")
    microbatch, accumulation = training["microbatch"], training["accumulation"]
    if microbatch <= 0 or accumulation <= 0 or microbatch * accumulation != EFFECTIVE_BATCH:
        raise invalid(f"microbatch * accumulation must equal {EFFECTIVE_BATCH}")
    context, output = limits["context_tokens"], limits["max_new_tokens"]
    if not 0 < output < context <= 16_384:
        raise invalid("Require 0 < max_new_tokens < context_tokens <= 16384")
    paths = {name: _path(data[name], base, f"data.{name}")
             for name in ("train_jsonl", "train_catalog", "validation_jsonl", "validation_catalog")}
    for name, path in paths.items():
        _reject_test_data(path, f"data.{name}")
    if paths["train_jsonl"] == paths["validation_jsonl"]:
        raise invalid("Train and validation must be different datasets")
    base_path = _path(model["base_path"], base, "model.base_path")
    experiment = _path(raw["output"]["experiment_dir"], base, "output.experiment_dir")
    for inside in (base_path, paths["train_jsonl"].parent, paths["validation_jsonl"].parent):
        if experiment == inside or experiment.is_relative_to(inside):
            raise invalid("output.experiment_dir must be outside model and data inputs")
    resolutions = data.get("audit_resolutions")
    return SftConfig(
        **paths, permitted_use=data["permitted_use"],
        audit_resolutions=None if resolutions is None else _path(resolutions, base, "data.audit_resolutions"),
        base_path=base_path, revision=model.get("revision"), device=training["device"], microbatch=microbatch,
        accumulation=accumulation, context_tokens=context, max_new_tokens=output, experiment_dir=experiment)


def load_config(path: Path, overrides: JSON | None = None) -> SftConfig:
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise invalid("Configuration file is unreadable") from exc
    except tomllib.TOMLDecodeError as exc:
        raise invalid("Configuration is not valid TOML") from exc
    for key, value in (overrides or {}).items():
        if value is None:
            continue
        if key not in OVERRIDES:
            raise invalid(f"Unknown override {key}")
        section, field = OVERRIDES[key]
        if isinstance(raw.get(section), dict):
            raw[section][field] = value
    return parse_config(raw, path.resolve().parent)
