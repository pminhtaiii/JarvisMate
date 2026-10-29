"""Strict, resolved experiment policies and manual prerequisites."""
from __future__ import annotations

import math
from pathlib import Path

from .storage import EXPERIMENTS, identity, outcome, read

DEFAULTS = {
    "seed": 42, "precision": "auto", "inference_dtype": "float16", "rank": 8,
    "alpha": 16, "dropout": .05, "micro_batch": 1, "accumulation": 16,
    "learning_rate": 1e-4, "weight_decay": .01, "max_epochs": 10,
    "warmup_ratio": .05, "max_grad_norm": 1., "patience": 3,
    "probe_updates": 10, "checkpoint_updates": 50, "timeout_seconds": 600.,
    "load_timeout_seconds": 600., "worker_timeout_seconds": 86400., "threads": 8,
    "vram_cap_gib": 12., "headroom_gib": 1., "purpose": "memory_comparison",
}


def load_config(path: Path, experiment: str) -> dict:
    value = read(path)
    common = read(path.parent / "common.json") if (path.parent / "common.json").is_file() else {}
    if not isinstance(common, dict) or set(common) - set(DEFAULTS):
        raise ValueError("Invalid common configuration fields")
    if not isinstance(value, dict) or set(value) - (set(DEFAULTS) | {"experiment", "scope"}):
        raise ValueError("Unknown configuration fields")
    config = DEFAULTS | common | value
    if experiment not in EXPERIMENTS or config.get("experiment") != experiment:
        raise ValueError("Config experiment does not match requested experiment")
    for key in ("seed", "rank", "alpha", "micro_batch", "accumulation", "max_epochs",
                "patience", "probe_updates", "checkpoint_updates", "threads"):
        if type(config[key]) is not int or config[key] < (0 if key == "seed" else 1):
            raise ValueError(f"Invalid integer: {key}")
    if config["seed"] > 2**32 - 1 or config["micro_batch"] != 1:
        raise ValueError("This single-GPU profile requires micro_batch=1 and uint32 seed")
    for key in ("learning_rate", "weight_decay", "max_grad_norm", "timeout_seconds",
                "load_timeout_seconds", "worker_timeout_seconds", "vram_cap_gib", "headroom_gib"):
        if type(config[key]) not in (int, float) or not math.isfinite(config[key]) or config[key] <= 0:
            raise ValueError(f"Invalid positive number: {key}")
    if config["vram_cap_gib"] > 12 or config["probe_updates"] < 10 or config["max_epochs"] > 10:
        raise ValueError("Operational cap <=12 GiB and >=10 probe updates are required")
    for key in ("dropout", "warmup_ratio"):
        if type(config[key]) not in (int, float) or not 0 <= config[key] < 1:
            raise ValueError(f"Invalid fraction: {key}")
    if config["precision"] not in {"auto", "float16", "bfloat16"} or config["inference_dtype"] != "float16":
        raise ValueError("Training precision auto/fp16/bf16; reference inference profile is FP16")
    if config.get("scope", "auto") not in {"auto", "decoder", "encoder_decoder"}:
        raise ValueError("Invalid adapter scope")
    return config


def prerequisites(suite: Path, config: dict) -> dict:
    experiment = config["experiment"]
    config = dict(config)
    if experiment == "E0":
        config["scope"] = "none"
        return config
    e0 = outcome(suite, "E0")
    if not e0 or e0[1]["status"] != "completed":
        raise ValueError("Run a complete E0 baseline first")
    config["baseline_run"] = str(e0[0].relative_to(suite))
    e1, e2 = outcome(suite, "E1"), outcome(suite, "E2")
    if experiment == "E1":
        config["scope"] = "decoder"
    elif experiment == "E2":
        if not e1 or e1[1]["status"] != "completed":
            raise ValueError("E2 requires a completed E1 control (or explicitly record a dependency skip)")
        config["scope"] = "encoder_decoder"
        original = read(e1[0] / "resolved-config.json")
        paired = ("seed", "rank", "alpha", "dropout", "precision", "micro_batch", "accumulation",
                  "learning_rate", "weight_decay", "max_epochs", "warmup_ratio", "max_grad_norm")
        if any(config[key] != original[key] for key in paired):
            raise ValueError("E2 must match E1 hyperparameters; change only adapter scope or use a new suite")
    elif experiment == "E3":
        from .storage import TERMINAL
        if not e1 or not e2 or e1[1]["status"] not in TERMINAL or e2[1]["status"] not in TERMINAL:
            raise ValueError("Record terminal E1 and E2 outcomes before E3")
        if config["purpose"] not in {"memory_comparison", "oom_fallback"}:
            raise ValueError("E3 needs an explicit memory_comparison or oom_fallback purpose")
        control = e2 if e2[1]["status"] == "completed" else e1
        config["scope"] = "encoder_decoder" if control is e2 else "decoder"
        config["control_run"] = str(control[0].relative_to(suite))
        if (control[0] / "resolved-config.json").exists():
            original = read(control[0] / "resolved-config.json")
            for key in ("seed", "rank", "alpha", "dropout", "precision", "micro_batch", "accumulation",
                        "learning_rate", "weight_decay", "max_epochs", "warmup_ratio", "max_grad_norm"):
                if config[key] != original[key]:
                    raise ValueError("E3 memory comparison must match its LoRA control hyperparameters")
    else:
        e3 = outcome(suite, "E3")
        from .storage import TERMINAL
        if not e2 or e2[1]["status"] not in TERMINAL or not e3 or e3[1]["status"] not in TERMINAL:
            raise ValueError("Record E2 and E3 outcomes/skips before E4")
        controls = [r for r in (e1, e2) if r and r[1]["status"] == "completed"]
        if not controls:
            raise ValueError("E4 requires a completed unquantized LoRA E1/E2 control")
        from .selection import checkpoint_key
        control = min(controls, key=lambda r: checkpoint_key(r[1]["metrics"], r[1]["best_step"]))
        original = read(control[0] / "resolved-config.json")
        for key in DEFAULTS:
            if key != "purpose":
                config[key] = original[key]
        config.update(scope=original["scope"], control_run=str(control[0].relative_to(suite)),
                      control_checkpoint=control[1]["best_checkpoint"],
                      update_budget=control[1]["updates"])
    return config


def binding(config: dict, suite: dict, hardware: dict, code: dict, environment: dict) -> dict:
    return {"config": identity(config), "suite": suite["identity"], "hardware": hardware,
            "code": code["hash"], "environment": identity(environment)}
