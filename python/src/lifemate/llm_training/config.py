"""Strict native suite configuration, pinned identities and portable roots (LL002/LL003).

Model-free: standard library only. Relative paths resolve from the declared project
root (never the working directory); portable identities store project-relative
references, while resolved absolute paths are execution metadata only.
"""
from __future__ import annotations

import copy
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from ..adapters.qwen_native import DECODER_VERSION, PROTOCOL_VERSION, REJECTION_SCHEMA, TERMINAL_POLICY
from ..jsonio import dumps, loads, visible_path
from ..native_tools import ADAPTER_VERSION
from ..prompting import PROMPT_HASH, PROMPT_VERSION

SUITE_CONFIG_SCHEMA = "lifemate-llm-suite-config-v1"
SELECTION_POLICY_SCHEMA = "lifemate-native-selection-policy-v1"
ROW_SCHEMA = "lifemate-native-next-action-row-v2"
EXPORTER_VERSION = "lifemate-native-sft-exporter-v1"
QUALITY_POLICY = "lifemate-native-quality-audit-v1"
BASE_MODEL = {"id": "Qwen/Qwen3-4B-Instruct-2507", "revision": "cdbee75f17c01a7cc42f958dc650907174af0554"}
DATASET_SHA256 = "24c42c79fbe8db932fe9817d041c0d0ca422ac8177b413cc1be0cda1fd8941a8"
CATALOG_SHA256 = "a994984bb580d7e0d60166641858901d428549682ba3614dbf9269037a33cce0"
SPLIT_IDENTITY = "da6b2725c4a7136e66e6ee93d2cda9a30561edd0905b4a78b258de35996dfcfa"
SPLIT_COUNTS = {"fit": 1236, "validation": 309}
SMOKE_FIT_IDS = ("train_1748", "train_1749", "train_1750", "train_1751")
FIXED_VALIDATION_CASES = ("train_0072", "train_0003", "train_0074", "train_0173", "train_0052",
                          "train_0038", "train_0447", "train_1428", "train_1144", "train_0105")
IDENTITIES = {"protocol": PROTOCOL_VERSION, "prompt": PROMPT_VERSION, "decoder": DECODER_VERSION,
              "terminal_policy": TERMINAL_POLICY, "rejection_schema": REJECTION_SCHEMA,
              "row_schema": ROW_SCHEMA, "catalog_adapter": ADAPTER_VERSION}
SEEDS = {"split": 42, "training": 42, "sampler": 42, "inference": 20261027, "bootstrap": 42}
LIMITS = {"context_tokens": 16_384, "output_tokens": 512, "max_steps": 16,
          "response_bytes": 65_536, "timeout_seconds": 30.0}
TARGET_TYPES = ("normal_call", "ask_missing_info", "initial_finish", "finish_after_calls")
EXPERIMENTS = {
    "L0": {"trainable": False, "weights": None},
    "L1": {"trainable": True, "weights": dict.fromkeys(TARGET_TYPES, 1)},
    "L2": {"trainable": True, "weights": {"normal_call": 1, "ask_missing_info": 2,
                                          "finish_after_calls": 1, "initial_finish": 2}},
    "L3": {"trainable": True, "weights": "selected_policy"},
}
MODES = ("G", "A")
REQUIRED_PATHS = ("data_root", "model_dir", "split_manifest", "output_root", "runtime_dir")
OPTIONAL_PATHS = ("asr_model_dir", "fit_asr_cache", "validation_asr_cache", "native_decoder_proof",
                  "selection_policy", "manual_reviews")
PATH_KEYS = REQUIRED_PATHS + OPTIONAL_PATHS
CONFIG_KEYS = frozenset({"schema", "project_root", "environment_profile", "base_model", "identities",
                         "seeds", "limits", *PATH_KEYS})


class ConfigError(ValueError):
    """Invalid, floating, mixed-format or unportable configuration."""


def content_hash(value: Any) -> str:
    return hashlib.sha256(dumps(value).encode("utf-8")).hexdigest()


def native_identities() -> dict:
    """Model-facing identities a native suite binds (P1 hash included)."""
    return IDENTITIES | {"prompt_sha256": PROMPT_HASH, "base_model": BASE_MODEL}


def _relative(value: str, key: str, *, allow_parent: bool = False) -> bool:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ConfigError(f"{key} must be a nonempty path string")
    absolute = PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()
    parts = PurePosixPath(value.replace("\\", "/")).parts
    if not absolute and ".." in parts and not allow_parent:
        raise ConfigError(f"{key} must not traverse outside the project root; use an explicit absolute path")
    return not absolute


@dataclass(frozen=True)
class SuiteConfig:
    """Validated configuration with resolved roots and portable references."""

    source: dict
    project_root: Path
    paths: dict[str, Path | None]
    portable: dict[str, Any]

    def require(self, key: str) -> Path:
        path = self.paths.get(key)
        if path is None:
            raise ConfigError(f"{key} is required for this phase")
        return path

    def identity(self) -> str:
        """Content identity: portable references and pins, never absolute local paths."""
        return content_hash({k: v for k, v in self.source.items() if k not in PATH_KEYS + ("project_root",)}
                            | {"paths": self.portable})


def portable_reference(path: Path | None, project_root: Path) -> Any:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return {"external": True, "name": path.name}


def validate_config(raw: Any) -> dict:
    if not isinstance(raw, dict) or set(raw) - CONFIG_KEYS:
        raise ConfigError("Unknown suite configuration keys")
    for key in ("schema", "project_root", *REQUIRED_PATHS, "base_model", "identities", "seeds", "limits"):
        if key not in raw:
            raise ConfigError(f"Missing configuration key {key}")
    if raw["schema"] != SUITE_CONFIG_SCHEMA:
        raise ConfigError("Unsupported suite configuration schema")
    if raw["base_model"] != BASE_MODEL:
        raise ConfigError("Base model must be the pinned Qwen3-4B-Instruct-2507 revision (no floating main)")
    if raw["identities"] != IDENTITIES:
        raise ConfigError("Configuration identities differ from the native protocol; old/mixed formats are rejected")
    if raw["seeds"] != SEEDS or raw["limits"] != LIMITS:
        raise ConfigError("Seeds and runtime limits are fixed shared controls")
    if "environment_profile" in raw and not (isinstance(raw["environment_profile"], str) and raw["environment_profile"]):
        raise ConfigError("environment_profile must be a nonempty string")
    for key in OPTIONAL_PATHS:
        if raw.get(key) is not None:
            _relative(raw[key], key)
    for key in REQUIRED_PATHS:
        _relative(raw[key], key)
    _relative(raw["project_root"], "project_root", allow_parent=True)
    return copy.deepcopy(raw)


def load_config(path: Path, *, project_root: Path | None = None,
                overrides: dict[str, Path | None] | None = None) -> SuiteConfig:
    """Read a config file; CLI overrides win; relative paths resolve from project_root.

    A relative ``project_root`` in the file is resolved against the file's directory,
    so behavior does not depend on the current working directory.
    """
    visible_path(path)
    try:
        raw = loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise ConfigError("Cannot read suite configuration") from exc
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    return resolve_config(raw, path.resolve().parent, project_root=project_root, overrides=overrides)


def config_from_suite(suite: dict, *, project_root: Path | None = None,
                      overrides: dict[str, Path | None] | None = None) -> SuiteConfig:
    """Rebuild a suite's configuration from its recorded local execution metadata.

    After relocation, pass root overrides; portable content identity is unchanged.
    """
    resolved = suite["execution_metadata"]["resolved_paths"]
    raw = dict(suite["config"]) | {key: resolved.get(key) for key in PATH_KEYS}
    raw["project_root"] = str(project_root) if project_root is not None else resolved.get("project_root") or "."
    root = project_root or Path(resolved.get("project_root") or ".")
    return resolve_config(raw, root, project_root=project_root or root, overrides=overrides)


def resolve_config(raw: Any, base_dir: Path, *, project_root: Path | None = None,
                   overrides: dict[str, Path | None] | None = None) -> SuiteConfig:
    try:
        raw = validate_config(raw)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    if project_root is not None:
        root = project_root.resolve()
    elif _relative(raw["project_root"], "project_root", allow_parent=True):
        root = (base_dir / raw["project_root"]).resolve()
    else:
        root = Path(raw["project_root"]).resolve()
    if not root.is_dir():
        raise ConfigError("Declared project root does not exist")
    paths: dict[str, Path | None] = {}
    for key in PATH_KEYS:
        value = (overrides or {}).get(key)
        if value is None:
            declared = raw.get(key)
            value = None if declared is None else (root / declared if _relative(declared, key) else Path(declared))
        elif not value.is_absolute():
            value = root / value
        if value is not None:
            value = value.resolve()
            visible_path(value)
        paths[key] = value
    writable = paths["output_root"]
    for key in ("data_root", "model_dir", "runtime_dir"):
        if writable.is_relative_to(paths[key]):
            raise ConfigError("Output root must be outside data/model/runtime inputs")
    portable = {key: portable_reference(value, root) for key, value in paths.items()}
    return SuiteConfig(raw, root, paths, portable)


def contained_output(output_root: Path, candidate: Path) -> Path:
    """A writable path inside the configured output root (rejects traversal/links)."""
    resolved = candidate.resolve()
    if not resolved.is_relative_to(output_root.resolve()):
        raise ConfigError("Writable artifact paths must stay inside the configured output root")
    visible_path(resolved)
    return resolved


# ---------------------------------------------------------- selection policy

DEFAULT_SELECTION_POLICY = {
    "schema": SELECTION_POLICY_SCHEMA,
    "primary": {"mode": "A", "trusted_metric": "state_gated_tool_call_f1",
                "fallback_metric": "tool_call_f1", "fallback_status": "provisional"},
    "controls": {"weighting_selection": {"candidate": "L2", "control": "L1"},
                 "final_promotion": {"control": "L0", "candidates": ["L1", "L2", "L3"]}},
    "improvement_epsilon": 1e-6,
    "tie_epsilon": 1e-6,
    "tie_order": ["L1", "L2", "L3"],
    "tolerances": {"ask_strict_tp_drop": 1, "no_action_tp_drop": 1, "minority_precision_drop": 0.05,
                   "minority_fp_increase_when_precision_undefined": 1, "failed_sources_increase": 1,
                   "timed_out_sources_increase": 1, "g_macro_f1_drop": 0.01,
                   "critical_argument_error_increase": 0, "latency_p95_relative_increase": 0.10},
    "mandatory_supports": ["primary_A", "g_tool_call_f1", "ask_confusion", "no_action_confusion",
                           "failure_counts", "timeout_counts"],
    "optional_guards": ["critical_argument_errors", "latency_p95"],
    "missing_metric_handling": {"mandatory": "pending", "optional": "unverified"},
}
SUPPORTS = frozenset({"primary_A", "g_tool_call_f1", "ask_confusion", "no_action_confusion",
                      "failure_counts", "timeout_counts", "critical_argument_errors", "latency_p95"})


def validate_selection_policy(policy: Any) -> dict:
    """Complete preregistered policy; values may differ from defaults but not be partial."""
    reference = DEFAULT_SELECTION_POLICY
    if not isinstance(policy, dict) or set(policy) != set(reference) or policy["schema"] != SELECTION_POLICY_SCHEMA:
        raise ConfigError("Selection policy must contain exactly the schema fields")
    primary = policy["primary"]
    if (not isinstance(primary, dict) or set(primary) != set(reference["primary"]) or primary["mode"] != "A"
            or primary["fallback_status"] != "provisional"
            or not all(isinstance(primary[k], str) and primary[k] for k in ("trusted_metric", "fallback_metric"))):
        raise ConfigError("Primary criterion must be an A-mode metric with trusted/provisional fallback fields")
    if policy["controls"] != reference["controls"] or policy["tie_order"] != reference["tie_order"]:
        raise ConfigError("Comparison controls and tie order are fixed by the specification")
    if set(policy["tolerances"]) != set(reference["tolerances"]):
        raise ConfigError("Every regression tolerance must be declared")
    for key, value in [("improvement_epsilon", policy["improvement_epsilon"]),
                       ("tie_epsilon", policy["tie_epsilon"]), *policy["tolerances"].items()]:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ConfigError(f"Tolerance {key} must be a finite nonnegative number")
    mandatory, optional = policy["mandatory_supports"], policy["optional_guards"]
    if (not isinstance(mandatory, list) or not isinstance(optional, list) or "primary_A" not in mandatory
            or set(mandatory) & set(optional) or not set(mandatory) | set(optional) <= SUPPORTS
            or len(set(mandatory)) != len(mandatory) or len(set(optional)) != len(optional)):
        raise ConfigError("Supports must be a disjoint known set including primary_A")
    if policy["missing_metric_handling"] != reference["missing_metric_handling"]:
        raise ConfigError("Missing mandatory evidence stays pending; optional stays unverified")
    return copy.deepcopy(policy)
