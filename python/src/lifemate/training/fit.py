"""Controlled LoRA/QLoRA fitting of the native planner on one audited SFT export.

The trainer reads a strict JSON configuration and an export's fit rows only; it never
opens Train data, environments or validation rows. Each row's completion-only labels
are re-derived with the base tokenizer and must match the export before any update.
Training libraries are imported lazily, so `lifemate run` and the data commands never
need them. Adapters are saved per epoch with provenance and a verified reload.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import math
import os
import platform
import random
import re
import shutil
import sys
import time
from pathlib import Path

from ..adapters import qwen_protocol
from ..artifacts import atomic_json, code_provenance, sync_write, utc_now
from ..contracts import JSON, Limits, PipelineError
from ..jsonio import digest, dumps, loads
from ..prompt_profiles import profile_identity, protocol_profile, resolve_profile
from ..prompting import NATIVE_FINISH_TEXT
from ..provenance import code_identity, model_identity
from . import data

CONFIG_SCHEMA_VERSION = 1
TRAINER_VERSION = "lifemate-native-sft-fit-v1"
RUN_MANIFEST = "fit_manifest.json"
ADAPTER_PROVENANCE = "lifemate_adapter.json"
ADAPTER_WEIGHTS = "adapter_model.safetensors"
PARAMETER_LIMIT = 5_000_000_000
FIELDS = frozenset({
    "schema_version", "base_model", "export_manifest", "fit_rows", "output_dir", "method", "device", "seed",
    "context_limit", "max_target_tokens", "microbatch", "gradient_accumulation", "gradient_checkpointing",
    "learning_rate", "epochs", "adapter", "optimizer", "schedule", "warmup_ratio", "checkpoint_cadence",
    "package_lock"})
ADAPTER_FIELDS = frozenset({"rank", "alpha", "dropout", "targets"})
# Packages the trainer imports; QLoRA additionally needs bitsandbytes.
REQUIRED_PINS = ("torch", "transformers", "peft", "accelerate", "safetensors", "tokenizers", "numpy")
PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.+!_-]*)")
# Settings this trainer version fixes; recorded so every run states all of them.
FIXED_SETTINGS = {
    "precision": "bf16 base weights and compute; fp32 adapter weights and optimizer state",
    "loss": "mean completion NLL per row, averaged over the rows of each optimizer step; prompt tokens ignored",
    "packing": False, "padding": "left", "weight_decay": 0.0, "max_grad_norm": 1.0, "lora_bias": "none",
    "data_order": "seeded permutation per epoch (seed + epoch)",
    "determinism": "torch deterministic algorithms with warn_only; bitwise GPU reproducibility is not claimed",
}
QLORA_SETTINGS = {"quant_type": "nf4", "double_quant": True, "compute_dtype": "bfloat16",
                  "kbit_preparation": True}


def _invalid(message: str) -> PipelineError:
    return PipelineError("INPUT_INVALID", message, "fit")


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise _invalid(message)


def _integer(value, low: int, high: int | None = None) -> bool:
    return type(value) is int and value >= low and (high is None or value <= high)


def _fraction(value) -> bool:
    """A finite real number in [0, 1)."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            and 0 <= value < 1)


def validate_config(value, base_dir: Path) -> JSON:
    """The validated settings and resolved paths; relative paths resolve against `base_dir`."""
    _check(isinstance(value, dict) and set(value) == FIELDS,
           f"Fit config needs exactly these fields: {', '.join(sorted(FIELDS))}")
    _check(value["schema_version"] == CONFIG_SCHEMA_VERSION, "Unsupported fit config schema_version")
    paths = {}
    for key in ("base_model", "export_manifest", "fit_rows", "output_dir"):
        _check(isinstance(value[key], str) and bool(value[key].strip()), f"{key} must be a path")
        paths[key] = (base_dir / value[key]).resolve()
    _check(value["method"] in ("lora", "qlora"), "method must be lora or qlora")
    _check(value["device"] in ("cpu", "cuda"), "device must be cpu or cuda")
    _check(value["method"] == "lora" or value["device"] == "cuda", "QLoRA needs a CUDA device")
    _check(_integer(value["seed"], 0, 2 ** 32 - 1), "seed must be a non-negative 32-bit integer")
    _check(_integer(value["context_limit"], 2, Limits().context_tokens),
           f"context_limit must be an integer up to {Limits().context_tokens}")
    _check(_integer(value["max_target_tokens"], 1, value["context_limit"] - 1),
           "max_target_tokens must be a positive integer below context_limit")
    for key in ("microbatch", "gradient_accumulation", "epochs"):
        _check(_integer(value[key], 1), f"{key} must be a positive integer")
    _check(isinstance(value["gradient_checkpointing"], bool), "gradient_checkpointing must be true or false")
    _check(_fraction(value["learning_rate"]) and value["learning_rate"] > 0, "learning_rate must be in (0, 1)")
    _check(_fraction(value["warmup_ratio"]), "warmup_ratio must be in [0, 1)")
    adapter = value["adapter"]
    _check(isinstance(adapter, dict) and set(adapter) == ADAPTER_FIELDS,
           "adapter needs exactly rank, alpha, dropout and targets")
    _check(_integer(adapter["rank"], 1, 1024), "adapter.rank must be an integer in [1, 1024]")
    _check(isinstance(adapter["alpha"], (int, float)) and not isinstance(adapter["alpha"], bool)
           and math.isfinite(adapter["alpha"]) and adapter["alpha"] > 0, "adapter.alpha must be positive")
    _check(_fraction(adapter["dropout"]), "adapter.dropout must be in [0, 1)")
    targets = adapter["targets"]
    _check(targets == "all-linear" or (isinstance(targets, list) and bool(targets)
                                       and all(isinstance(t, str) and t.strip() for t in targets)
                                       and len(set(targets)) == len(targets)),
           "adapter.targets must be 'all-linear' or a list of distinct module names")
    _check((value["optimizer"], value["schedule"], value["checkpoint_cadence"]) == ("adamw_torch", "linear", "epoch"),
           "This trainer supports optimizer adamw_torch, schedule linear and checkpoint_cadence epoch")
    lock = value["package_lock"]
    _check(isinstance(lock, dict) and set(lock) == {"path", "sha256"} and isinstance(lock["path"], str)
           and bool(lock["path"].strip()) and isinstance(lock["sha256"], str)
           and re.fullmatch(r"[0-9a-f]{64}", lock["sha256"]) is not None,
           "package_lock needs a path and its lowercase hex sha256")
    paths["package_lock"] = (base_dir / lock["path"]).resolve()
    output = paths["output_dir"]
    for name in ("base_model", "export_manifest"):
        protected = paths[name] if name == "base_model" else paths[name].parent
        _check(not output.is_relative_to(protected), "output_dir must be outside the base model and the export")
    return {"settings": value, "paths": paths}


def load_config(path: Path) -> JSON:
    path = Path(path).resolve()
    try:
        raw = path.read_bytes()
        value = loads(raw.decode("utf-8"))
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        raise _invalid("Fit config is unreadable or invalid JSON") from exc
    return validate_config(value, path.parent) | {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def _jsonl(raw: bytes, name: str) -> list[JSON]:
    try:
        rows = [loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise _invalid(f"{name} is not valid JSONL") from exc
    _check(all(isinstance(row, dict) for row in rows), f"{name} rows must be objects")
    return rows


def _read(path: Path, name: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise _invalid(f"Cannot read the {name}") from exc


def audited_rows(paths: JSON) -> tuple[list[JSON], JSON, JSON]:
    """Fit rows proven to be unmodified fit-side rows of one audited native export.

    Returns the rows, the export manifest and the input identity. A row from the
    validation diagnostics, an edited row or a stale export is rejected, never skipped.
    """
    manifest_bytes = _read(paths["export_manifest"], "export manifest")
    try:
        manifest = loads(manifest_bytes.decode("utf-8"))
        expected_prompt = profile_identity(protocol_profile(resolve_profile("baseline"), qwen_protocol.PROTOCOL))
        audited = (manifest["export_schema_version"] == data.EXPORT_SCHEMA_VERSION
                   and manifest["exporter"]["version"] == data.EXPORTER_VERSION
                   and manifest["protocol"]["protocol"] == qwen_protocol.PROTOCOL
                   and manifest["protocol"]["prompt"] == expected_prompt
                   and manifest["protocol"]["final_text"] == NATIVE_FINISH_TEXT
                   and manifest["supervision"]["ignore_index"] == data.IGNORE_INDEX
                   and manifest["supervision"]["packing"] is False
                   and manifest["audits"]["leakage"]["failures"] == 0
                   and manifest["audits"]["partition"]["shared_groups"] == 0
                   and manifest["audits"]["partition"]["non_fit_rows_in_fit"] == 0
                   and isinstance(manifest["base_model"]["files"], dict))
        fit_sha256 = manifest["files"][data.EXPORT_FILES["fit"]]["sha256"]
    except (ValueError, UnicodeError, RecursionError, KeyError, TypeError) as exc:
        raise _invalid("Export manifest is unreadable or lacks its audit fields") from exc
    _check(audited, "The export is not an audited native export for the current protocol and prompt")
    export_fit = paths["export_manifest"].parent / data.EXPORT_FILES["fit"]
    export_bytes = _read(export_fit, "export fit rows")
    _check(hashlib.sha256(export_bytes).hexdigest() == fit_sha256, "The export's fit.jsonl differs from its manifest")
    selected_bytes = export_bytes if paths["fit_rows"] == export_fit else _read(paths["fit_rows"], "fit rows")
    exported = {row.get("row_id"): row for row in _jsonl(export_bytes, "export fit.jsonl")}
    rows, seen = _jsonl(selected_bytes, "fit rows"), set()
    _check(bool(rows), "The fit rows file has no rows")
    for row in rows:
        provenance = row.get("provenance")
        _check(row.get("use") == "fit" and isinstance(provenance, dict) and provenance.get("partition") == "fit",
               f"Row {row.get('row_id')!r} is not a fit row; validation rows never enter optimizer input")
        _check(row.get("row_id") not in seen and exported.get(row.get("row_id")) == row,
               f"Row {row.get('row_id')!r} is not an unmodified, unique row of the export's fit.jsonl")
        seen.add(row["row_id"])
    identity = {"export_manifest": {"path": str(paths["export_manifest"]),
                                    "sha256": hashlib.sha256(manifest_bytes).hexdigest()},
                "fit_rows": {"path": str(paths["fit_rows"]), "sha256": hashlib.sha256(selected_bytes).hexdigest(),
                             "rows": len(rows), "export_fit_rows": len(exported),
                             "subset": len(rows) != len(exported)},
                "protocol": manifest["protocol"], "source": manifest.get("source"),
                "partition": manifest.get("partition")}
    return rows, manifest, identity


def locked_packages(path: Path, sha256: str, method: str, version=importlib.metadata.version) -> JSON:
    """The exact pins of the training lock, each verified against the installed version."""
    raw = _read(path, "package lock")
    _check(hashlib.sha256(raw).hexdigest() == sha256, "The package lock differs from the sha256 in the config")
    pins = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        match = PIN.fullmatch(line)
        _check(match is not None, "Package lock lines must be exact name==version pins")
        pins[re.sub(r"[-_.]+", "-", match[1]).lower()] = match[2]
    required = REQUIRED_PINS + (("bitsandbytes",) if method == "qlora" else ())
    _check(all(name in pins for name in required), f"The package lock must pin {', '.join(required)}")
    installed = {}
    for name in pins:
        try:
            installed[name] = version(name)
        except importlib.metadata.PackageNotFoundError:
            installed[name] = None
    differing = sorted(name for name in pins if installed[name] != pins[name])
    if differing:
        raise PipelineError("MODEL_UNAVAILABLE", "Installed training packages differ from the lock: "
                            + ", ".join(f"{n} {installed[n]} != {pins[n]}" for n in differing[:8]), "fit")
    return {"path": str(path), "sha256": sha256, "pins": pins, "python": platform.python_version(),
            "platform": platform.platform()}


def verify_base(base: Path, manifest: JSON, tokenizer) -> JSON:
    """The base matches the export's tokenizer/template/config identity; weights are hashed too."""
    recorded = manifest["base_model"]
    if data.base_files(base) != recorded["files"]:
        raise _invalid("The base model's tokenizer, template or config files differ from the export's base")
    template = hashlib.sha256(tokenizer.chat_template.encode()).hexdigest()
    if (template, tokenizer.eos_token_id) != (recorded["chat_template_sha256"], recorded["eos_token_id"]):
        raise _invalid("The loaded chat template or EOS differs from the export's base")
    return {"identity": model_identity(base), "chat_template_sha256": template,
            "tokenizer_class": type(tokenizer).__name__, "eos_token_id": tokenizer.eos_token_id}


def mask_audit(rows: list[JSON], tokenizer, settings: JSON) -> tuple[list[JSON], JSON]:
    """Re-derive every row's completion-only labels and enforce the fit budgets.

    A row whose tokens, mask or decoded target differ from the export fails the audit,
    and a row over the budgets stops the run: rows are never dropped or truncated here.
    """
    examples = []
    for row in rows:
        row_id = row["row_id"]
        try:
            input_ids, labels = data.token_labels(tokenizer, row["prompt"], row["completion"])
            prompt_tokens = labels.count(data.IGNORE_INDEX)
            target = qwen_protocol.decode_decision(
                tokenizer.decode(input_ids[prompt_tokens:], skip_special_tokens=True))
        except (KeyError, TypeError, ValueError, UnicodeError, RecursionError) as exc:
            raise _invalid(f"Mask audit failed for {row_id}: {exc}") from exc
        completion_tokens = len(input_ids) - prompt_tokens
        if (labels[:prompt_tokens] != [data.IGNORE_INDEX] * prompt_tokens
                or (prompt_tokens, completion_tokens) != (row.get("prompt_tokens"), row.get("completion_tokens"))
                or dumps(target) != dumps(row.get("canonical_target"))):
            raise _invalid(f"Mask audit failed for {row_id}: tokens, mask or target differ from the export")
        if len(input_ids) > settings["context_limit"] or completion_tokens > settings["max_target_tokens"]:
            raise PipelineError("CONTEXT_LIMIT", f"{row_id} needs {len(input_ids)} tokens with a {completion_tokens}"
                                "-token target, over the fit budgets; rows are never dropped or truncated", "fit")
        examples.append({"row_id": row_id, "input_ids": input_ids, "labels": labels,
                         "completion_tokens": completion_tokens})
    totals = [len(e["input_ids"]) for e in examples]
    targets = [e["completion_tokens"] for e in examples]
    return examples, {"rows_checked": len(examples), "failures": 0, "target_tokens": sum(targets),
                      "masked_prompt_tokens": sum(totals) - sum(targets), "max_total_tokens": max(totals),
                      "max_completion_tokens": max(targets), "context_limit": settings["context_limit"],
                      "max_target_tokens": settings["max_target_tokens"]}


def libraries(method: str):
    """torch, transformers and peft from the isolated training environment."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    try:
        import peft
        import torch
        import transformers
        if method == "qlora":
            import bitsandbytes  # noqa: F401
    except ImportError as exc:
        raise PipelineError("MODEL_UNAVAILABLE", "Fitting needs the isolated training environment "
                            "(python/requirements-training.txt)", "fit") from exc
    return torch, transformers, peft


def seed_everything(torch, seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    try:
        import numpy

        numpy.random.seed(seed)
    except ImportError:
        pass


def device_report(torch, device: str) -> JSON:
    """The training device; a missing GPU or BF16 support stops the run instead of changing it."""
    if device == "cpu":
        return {"device": "cpu", "bf16": True, "machine": platform.machine(), "cpu_count": os.cpu_count()}
    if not torch.cuda.is_available():
        raise PipelineError("MODEL_UNAVAILABLE", "CUDA was requested but is unavailable; fitting never falls back "
                            "to CPU", "fit")
    if not torch.cuda.is_bf16_supported():
        raise PipelineError("MODEL_UNAVAILABLE", "The GPU lacks BF16 support; precision is never changed silently",
                            "fit")
    properties = torch.cuda.get_device_properties(0)
    return {"device": "cuda", "bf16": True, "name": properties.name, "total_memory_bytes": properties.total_memory,
            "compute_capability": f"{properties.major}.{properties.minor}", "cuda": torch.version.cuda}


def load_model(libs, base: Path, settings: JSON):
    """The base in BF16 (or NF4 for QLoRA) wrapped in a fresh LoRA adapter."""
    torch, hf, peft = libs
    qlora = settings["method"] == "qlora"
    config = hf.AutoConfig.from_pretrained(base, local_files_only=True, trust_remote_code=False)
    if config.model_type != "qwen3":
        raise PipelineError("MODEL_UNAVAILABLE", "Fitting requires a local Qwen3 checkpoint", "fit")
    # BF16 eager attention is several times slower than SDPA on CPU; SDPA serves both devices.
    attention = "sdpa"
    options = {"config": config, "local_files_only": True, "trust_remote_code": False, "dtype": torch.bfloat16,
               "attn_implementation": attention, "weights_only": True}
    if qlora:
        options |= {"device_map": {"": 0}, "quantization_config": hf.BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16)}
    model = hf.AutoModelForCausalLM.from_pretrained(base, **options)
    # num_parameters counts packed 4-bit weights at their full size.
    base_parameters = model.num_parameters()
    if base_parameters >= PARAMETER_LIMIT:
        raise PipelineError("MODEL_UNAVAILABLE", "The base model exceeds the parameter budget", "fit")
    model.config.use_cache = False
    checkpointing = {"use_reentrant": False}
    if qlora:
        model = peft.prepare_model_for_kbit_training(
            model, use_gradient_checkpointing=settings["gradient_checkpointing"],
            gradient_checkpointing_kwargs=checkpointing)
    else:
        model.to(settings["device"])
        if settings["gradient_checkpointing"]:
            model.gradient_checkpointing_enable(gradient_checkpointing_kwargs=checkpointing)
            model.enable_input_require_grads()
    adapter = settings["adapter"]
    model = peft.get_peft_model(model, peft.LoraConfig(
        r=adapter["rank"], lora_alpha=adapter["alpha"], lora_dropout=adapter["dropout"],
        target_modules=adapter["targets"], bias="none", task_type="CAUSAL_LM"))
    trainable = [p for p in model.parameters() if p.requires_grad]
    return model, {"model_type": config.model_type, "base_parameters": base_parameters,
                   "trainable_parameters": sum(p.numel() for p in trainable),
                   "adapter_modules": sorted(model.peft_config["default"].target_modules),
                   "attention_implementation": attention, "dtype": "bfloat16",
                   "qlora": QLORA_SETTINGS if qlora else None}


def _batch(torch, examples: list[JSON], pad_id: int, device: str):
    """Left-padded tensors; every completion then ends at the last position."""
    width = max(len(e["input_ids"]) for e in examples)
    keep = max(e["completion_tokens"] for e in examples) + 1
    ids, mask, labels = [], [], []
    for example in examples:
        pad = width - len(example["input_ids"])
        ids.append([pad_id] * pad + example["input_ids"])
        mask.append([0] * pad + [1] * len(example["input_ids"]))
        labels.append([data.IGNORE_INDEX] * pad + example["labels"])
    ids, mask, labels = (torch.tensor(value, device=device) for value in (ids, mask, labels))
    positions = (mask.cumsum(-1) - 1).clamp(min=0)
    return ids, mask, positions, labels[:, width - keep + 1:], keep


def row_losses(torch, model, examples: list[JSON], pad_id: int, device: str):
    """Mean completion NLL of each row.

    Only the positions that predict completion tokens get logits (`logits_to_keep`), so
    a full-vocabulary logit matrix is never built over a long prompt.
    """
    ids, mask, positions, targets, keep = _batch(torch, examples, pad_id, device)
    logits = model(input_ids=ids, attention_mask=mask, position_ids=positions, logits_to_keep=keep,
                   use_cache=False).logits[:, :-1, :].float()
    losses = torch.nn.functional.cross_entropy(logits.transpose(1, 2), targets, ignore_index=data.IGNORE_INDEX,
                                               reduction="none")
    return losses.sum(-1) / (targets != data.IGNORE_INDEX).sum(-1)


def memory_probe(torch, model, examples: list[JSON], settings: JSON, pad_id: int, hardware: JSON) -> JSON:
    """One forward/backward pass on the longest accepted rows; the weights are not updated."""
    longest = sorted(examples, key=lambda e: len(e["input_ids"]), reverse=True)[:settings["microbatch"]]
    cuda = settings["device"] == "cuda"
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    # AdamW keeps two fp32 moments per trainable parameter.
    result = {"probe_rows": len(longest), "probe_tokens": len(longest[0]["input_ids"]),
              "optimizer_state_bytes_estimate": 8 * trainable}
    if cuda:
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
    model.train()
    try:
        row_losses(torch, model, longest, pad_id, settings["device"]).mean().backward()
    except torch.cuda.OutOfMemoryError as exc:
        raise PipelineError("MODEL_UNAVAILABLE", "One microbatch of the longest accepted rows does not fit in GPU "
                            "memory; reduce microbatch or choose QLoRA explicitly", "fit") from exc
    finally:
        model.zero_grad(set_to_none=True)
    if not cuda:
        return result | {"peak_allocated_bytes": None, "note": "CPU memory is not measured"}
    peak = torch.cuda.max_memory_allocated()
    headroom = hardware["total_memory_bytes"] - peak - result["optimizer_state_bytes_estimate"]
    result |= {"peak_allocated_bytes": peak, "total_memory_bytes": hardware["total_memory_bytes"],
               "headroom_bytes": headroom}
    if headroom < 0:
        raise PipelineError("MODEL_UNAVAILABLE", "Measured peak memory plus optimizer state exceeds the GPU", "fit")
    return result


def adapter_matches(torch, peft, model, checkpoint: Path) -> bool:
    """The saved adapter tensors equal the trained ones exactly."""
    from safetensors.torch import load_file

    saved = load_file(str(checkpoint / ADAPTER_WEIGHTS))
    current = peft.get_peft_model_state_dict(model)
    return set(saved) == set(current) and all(
        torch.equal(saved[name], current[name].detach().to("cpu")) for name in saved)


def save_checkpoint(libs, model, output: Path, name: str, provenance: JSON) -> JSON:
    """Write one adapter checkpoint, then publish it under its final name once reload is verified."""
    torch, _, peft = libs
    staging = output / f".{name}.partial"
    model.save_pretrained(staging, safe_serialization=True)
    if not adapter_matches(torch, peft, model, staging):
        raise PipelineError("OUTPUT_IO", f"Reloaded adapter {name} differs from the trained weights", "fit")
    weights = digest(staging / ADAPTER_WEIGHTS)
    with (staging / ADAPTER_PROVENANCE).open("x", encoding="utf-8", newline="\n") as stream:
        sync_write(stream, dumps(provenance | {"adapter_sha256": weights}) + "\n")
    os.rename(staging, output / name)
    return {"name": name, "path": str(output / name), "adapter_sha256": weights, "reload_verified": True}


def train(libs, model, examples: list[JSON], settings: JSON, pad_id: int, checkpoint) -> JSON:
    """Seeded epochs of AdamW with linear warmup/decay; `checkpoint` runs after each epoch."""
    torch, hf, _ = libs
    seed_everything(torch, settings["seed"])
    microbatches = math.ceil(len(examples) / settings["microbatch"])
    steps_per_epoch = math.ceil(microbatches / settings["gradient_accumulation"])
    total_steps = steps_per_epoch * settings["epochs"]
    warmup_steps = math.ceil(settings["warmup_ratio"] * total_steps)
    parameters = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(parameters, lr=settings["learning_rate"],
                                  weight_decay=FIXED_SETTINGS["weight_decay"])
    scheduler = hf.get_linear_schedule_with_warmup(optimizer, warmup_steps, total_steps)
    model.train()
    epochs, step = [], 0
    for epoch in range(1, settings["epochs"] + 1):
        started = time.monotonic()
        order = torch.randperm(len(examples), generator=torch.Generator().manual_seed(settings["seed"] + epoch))
        batches = [[examples[i] for i in order[start:start + settings["microbatch"]].tolist()]
                   for start in range(0, len(examples), settings["microbatch"])]
        step_losses = []
        for start in range(0, len(batches), settings["gradient_accumulation"]):
            group = batches[start:start + settings["gradient_accumulation"]]
            rows = sum(len(batch) for batch in group)
            total = 0.0
            for batch in group:
                losses = row_losses(torch, model, batch, pad_id, settings["device"])
                (losses.sum() / rows).backward()
                total += float(losses.detach().sum())
            torch.nn.utils.clip_grad_norm_(parameters, FIXED_SETTINGS["max_grad_norm"])
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)
            step += 1
            loss = total / rows
            if not math.isfinite(loss):
                raise PipelineError("MODEL_UNAVAILABLE", f"Training loss became non-finite at step {step}", "fit")
            step_losses.append(round(loss, 6))
        summary = {"epoch": epoch, "optimizer_steps": step, "seconds": round(time.monotonic() - started, 3),
                   "mean_step_loss": round(sum(step_losses) / len(step_losses), 6), "step_losses": step_losses}
        summary["checkpoint"] = checkpoint(epoch, step, summary["mean_step_loss"])
        epochs.append(summary)
    return {"rows": len(examples), "optimizer_steps": step, "steps_per_epoch": steps_per_epoch,
            "warmup_steps": warmup_steps, "effective_batch_rows": settings["microbatch"]
            * settings["gradient_accumulation"], "epochs": epochs}


def claim_output(output: Path) -> None:
    """Create the run directory; an existing path, even an empty directory, is never reused."""
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        os.mkdir(output)
    except FileExistsError as exc:
        raise _invalid("The fit output_dir already exists; every fit needs a new directory") from exc
    except OSError as exc:
        raise PipelineError("OUTPUT_IO", "Cannot create the fit output_dir", "fit") from exc


def fit(config_path: Path, *, preflight_only: bool = False) -> JSON:
    """Audit inputs, preflight the device and memory, then train and save adapter checkpoints.

    Every outcome after the output directory is claimed leaves `fit_manifest.json` with
    its status and stage; a failure keeps the evidence gathered so far.
    """
    config = load_config(config_path)
    settings, paths = config["settings"], config["paths"]
    output = paths["output_dir"]
    if output.exists():
        raise _invalid("The fit output_dir already exists; every fit needs a new directory")
    claim_output(output)
    manifest = {"schema_version": 1, "trainer": TRAINER_VERSION, "status": "running", "stage": "preflight",
                "check": "inputs", "started_at": utc_now(), "preflight_only": preflight_only,
                "output_dir": str(output),
                "config": {"path": config["path"], "sha256": config["sha256"], "settings": settings},
                "fixed_settings": FIXED_SETTINGS,
                "code": {"sha256": hashlib.sha256(dumps(code_identity()).encode()).hexdigest(),
                         **code_provenance()},
                "checkpoints": []}
    path = output / RUN_MANIFEST

    def advance(check: str, **values) -> None:
        manifest.update(values, check=check)
        atomic_json(path, manifest)

    advance("inputs")
    try:
        rows, export_manifest, inputs = audited_rows(paths)
        advance("packages", inputs=inputs)
        packages = locked_packages(paths["package_lock"], settings["package_lock"]["sha256"], settings["method"])
        libs = libraries(settings["method"])
        torch = libs[0]
        advance("tokenizer_and_masks", packages=packages)
        tokenizer = data.load_tokenizer(paths["base_model"], "fit")
        base = verify_base(paths["base_model"], export_manifest, tokenizer)
        examples, audit = mask_audit(rows, tokenizer, settings)
        advance("device", base_model=base, mask_audit=audit)
        torch.use_deterministic_algorithms(True, warn_only=True)
        seed_everything(torch, settings["seed"])
        hardware = device_report(torch, settings["device"])
        advance("model_load", hardware=hardware)
        model, model_summary = load_model(libs, paths["base_model"], settings)
        pad_id = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id
        advance("memory", model=model_summary)
        memory = memory_probe(torch, model, examples, settings, pad_id, hardware)
        if preflight_only:
            advance("complete", memory=memory, status="preflight-passed", finished_at=utc_now())
            return manifest
        advance("training", memory=memory, stage="fit")
        provenance = {"schema_version": 1, "trainer": TRAINER_VERSION, "method": settings["method"],
                      "adapter": settings["adapter"], "seed": settings["seed"],
                      "base_model": {"files": base["identity"]["files"],
                                     "chat_template_sha256": base["chat_template_sha256"],
                                     "tokenizer_class": base["tokenizer_class"]},
                      "protocol": {"protocol": qwen_protocol.PROTOCOL, "prompt": inputs["protocol"]["prompt"],
                                   "final_text": NATIVE_FINISH_TEXT},
                      "export_manifest_sha256": inputs["export_manifest"]["sha256"],
                      "fit_rows_sha256": inputs["fit_rows"]["sha256"], "config_sha256": config["sha256"],
                      "packages_sha256": packages["sha256"], "qlora": model_summary["qlora"],
                      "trainable_parameters": model_summary["trainable_parameters"]}

        def checkpoint(epoch: int, steps: int, loss: float) -> JSON:
            saved = save_checkpoint(libs, model, output, f"checkpoint-epoch-{epoch}",
                                    provenance | {"epoch": epoch, "optimizer_steps": steps, "mean_step_loss": loss})
            manifest["checkpoints"].append(saved | {"epoch": epoch, "mean_step_loss": loss})
            advance("training", stage="adapter-saved")
            return saved["path"]

        training = train(libs, model, examples, settings, pad_id, checkpoint)
        advance("complete", training=training, status="completed", stage="adapter-saved", finished_at=utc_now())
        return manifest
    except PipelineError as exc:
        _failed(manifest, path, exc.record())
        raise
    except KeyboardInterrupt:
        _failed(manifest, path, PipelineError("INTERRUPTED", "Fitting was interrupted", "fit").record())
        raise
    except Exception as exc:
        error = PipelineError("MODEL_UNAVAILABLE", f"Fitting failed with {type(exc).__name__}", "fit")
        _failed(manifest, path, error.record())
        raise error from exc


def _failed(manifest: JSON, path: Path, error: JSON) -> None:
    manifest.update(status="failed", error=error, finished_at=utc_now())
    try:
        atomic_json(path, manifest)
    except PipelineError:
        # The original failure is the one to report; the partial manifest stays on disk.
        print("Cannot record the failed fit manifest", file=sys.stderr)
    for partial in path.parent.glob(".checkpoint-*.partial"):
        shutil.rmtree(partial, ignore_errors=True)
