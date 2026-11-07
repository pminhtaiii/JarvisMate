"""The fixed QLoRA recipe: sampling, final-span loss, checkpoints and coverage-safe selection.

An explicit loop rather than ``transformers.Trainer`` (ADR 012): the objective is summed
target cross-entropy over the supervised tokens of a whole 16-example window. Model
libraries load lazily, so the pure sampling and selection rules need only the standard library.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import math
import os
import platform
import random
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterable
from contextlib import nullcontext
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from ..adapters.qwen_native import validate_template
from ..artifacts import atomic_json
from ..contracts import JSON, PipelineError
from ..jsonio import digest, dumps, read_json
from . import EFFECTIVE_BATCH, FINAL_UPDATE_RULE, RECIPE, SEED, SELECTION_MODES, SftConfig
from .data import ReadyExport, TokenAudit, base_identity, encode_row, load_ready_export, load_tokenizer

SELECTED_RULE = RECIPE["selection"]
TRAINING_PACKAGES = ("torch", "transformers", "tokenizers", "peft", "bitsandbytes", "accelerate", "safetensors", "numpy")


def failure(message: str, code: str = "SFT_TRAINING") -> PipelineError:
    return PipelineError(code, message, "sft_training")


@dataclass(frozen=True)
class TrainPlan:
    """The recipe's run length; only tests and the explicit smoke mode shorten it."""
    updates: int = RECIPE["updates"]
    evaluate_every: int = RECIPE["evaluate_every"]
    warmup: int = RECIPE["warmup_updates"]
    validation_limit: int | None = None
    smoke: bool = False
    stop_after: int | None = None  # Test hook: simulate an interruption after this update.

    @property
    def candidates(self) -> list[int]:
        return list(range(self.evaluate_every, self.updates + 1, self.evaluate_every))

    def identity(self) -> JSON:
        return {"updates": self.updates, "evaluate_every": self.evaluate_every, "warmup": self.warmup,
                "validation_limit": self.validation_limit, "smoke": self.smoke}


SMOKE_PLAN = TrainPlan(updates=2, evaluate_every=2, validation_limit=8, smoke=True)


def default_plan(config: SftConfig, smoke: bool) -> TrainPlan:
    if not smoke:
        return TrainPlan()
    # Without a validation role the smoke plan records no validation subset it never reads.
    return SMOKE_PLAN if config.validated else replace(SMOKE_PLAN, validation_limit=None)


# --- Pure: sampling, coverage, schedule, selection -------------------------------

class RowStream:
    """Continuous deterministic shuffled traversal: every row once before any repeats.

    Windows span epoch boundaries, so no partial batch is dropped. State is only
    (epoch, position), restored without replaying the run.
    """

    def __init__(self, row_count: int, seed: int = SEED, epoch: int = 0, position: int = 0):
        if row_count <= 0 or epoch < 0 or not 0 <= position <= row_count:
            raise failure("Invalid row stream state", "SFT_IDENTITY")
        self.row_count, self.seed, self.epoch, self.position = row_count, seed, epoch, position
        self._order, self._order_epoch = [], -1

    def _current(self) -> list[int]:
        if self._order_epoch != self.epoch:
            self._order = list(range(self.row_count))
            random.Random(f"{self.seed}:{self.epoch}").shuffle(self._order)
            self._order_epoch = self.epoch
        return self._order

    def next_window(self, size: int = EFFECTIVE_BATCH) -> list[int]:
        window = []
        while len(window) < size:
            if self.position == self.row_count:
                self.epoch, self.position = self.epoch + 1, 0
            order = self._current()
            taken = order[self.position:self.position + size - len(window)]
            window += taken
            self.position += len(taken)
        return window

    def state(self) -> JSON:
        return {"epoch": self.epoch, "position": self.position}

    @property
    def consumed(self) -> int:
        return self.epoch * self.row_count + self.position


class Coverage:
    """Unique rows and sources that have contributed to a completed optimizer update."""

    def __init__(self, row_sources: list[str], rows=(), sources=()):
        self.row_sources = row_sources
        self.expected_sources = len(set(row_sources))
        self.rows, self.sources = set(rows), set(sources)

    def add(self, window: list[int]) -> None:
        self.rows.update(window)
        self.sources.update(self.row_sources[index] for index in window)

    @property
    def complete(self) -> bool:
        return (bool(self.row_sources) and len(self.rows) == len(self.row_sources)
                and len(self.sources) == self.expected_sources)

    def record(self) -> JSON:
        return {"unique_rows": len(self.rows), "expected_rows": len(self.row_sources),
                "unique_sources": len(self.sources), "expected_sources": self.expected_sources,
                "rows": sorted(self.rows), "complete": self.complete}


def replay(row_sources: list[str], update: int, seed: int = SEED) -> tuple[RowStream, Coverage]:
    """Recompute progress from first principles: persisted state cannot overstate coverage."""
    stream, coverage = RowStream(len(row_sources), seed), Coverage(row_sources)
    for _ in range(update):
        coverage.add(stream.next_window())
    return stream, coverage


def require_coverage_budget(row_count: int, plan: TrainPlan) -> None:
    if row_count <= 0:
        raise failure("No training rows")
    if plan.updates * EFFECTIVE_BATCH < row_count and not plan.smoke:
        raise failure(f"{plan.updates} updates of {EFFECTIVE_BATCH} cannot cover {row_count} rows; "
                      "revise the recipe explicitly")


def lr_multiplier(completed_updates: int, warmup: int = RECIPE["warmup_updates"]) -> float:
    """Linear warmup over the first updates, then constant. Argument counts finished updates."""
    return min(1.0, (completed_updates + 1) / warmup)


def fully_covered(coverage: JSON) -> bool:
    return (coverage["expected_rows"] > 0 and coverage["unique_rows"] == coverage["expected_rows"]
            and coverage["expected_sources"] > 0 and coverage["unique_sources"] == coverage["expected_sources"])


def select_checkpoint(candidates: list[JSON]) -> JSON:
    """Lowest finite NLL among fully covered candidates; an exact tie takes the earlier update."""
    evaluated = []
    for candidate in sorted(candidates, key=lambda c: c["update"]):
        nll, coverage = candidate["validation_nll"], candidate["coverage"]
        finite = isinstance(nll, (int, float)) and math.isfinite(nll)
        covered = fully_covered(coverage)
        evaluated.append({"update": candidate["update"], "validation_nll": nll, "finite": finite,
                          "unique_rows": coverage["unique_rows"], "expected_rows": coverage["expected_rows"],
                          "unique_sources": coverage["unique_sources"], "expected_sources": coverage["expected_sources"],
                          "eligible": finite and covered, "adapter_sha256": candidate.get("adapter_sha256")})
    eligible = [c for c in evaluated if c["eligible"]]
    chosen = min(eligible, key=lambda c: (c["validation_nll"], c["update"])) if eligible else None
    return {"status": "selected" if chosen else "failed", "mode": SELECTION_MODES["separate"], "rule": SELECTED_RULE,
            "candidates": evaluated, "selected_update": chosen["update"] if chosen else None,
            "adapter_sha256": chosen["adapter_sha256"] if chosen else None}


def select_final_update(candidates: list[JSON], final_update: int) -> JSON:
    """The last planned update once it is committed with full coverage; validation plays no part.

    Earlier checkpoints are listed for provenance and are never eligible. No NLL is read or
    recorded, so a missing metric cannot be mistaken for a measured one.
    """
    evaluated = []
    for candidate in sorted(candidates, key=lambda c: c["update"]):
        coverage = candidate["coverage"]
        covered, final = fully_covered(coverage), candidate["update"] == final_update
        evaluated.append({"update": candidate["update"], "final": final, "covered": covered,
                          **{key: coverage[key] for key in ("unique_rows", "expected_rows", "unique_sources",
                                                            "expected_sources")},
                          "eligible": final and covered, "adapter_sha256": candidate.get("adapter_sha256")})
    chosen = next((c for c in evaluated if c["eligible"]), None)
    return {"status": "selected" if chosen else "failed", "mode": SELECTION_MODES["none"], "rule": FINAL_UPDATE_RULE,
            "validation": "none", "final_update": final_update, "candidates": evaluated,
            "selected_update": chosen["update"] if chosen else None,
            "adapter_sha256": chosen["adapter_sha256"] if chosen else None}


def select_for(validation_mode: str, candidates: list[JSON], plan: TrainPlan) -> JSON:
    if validation_mode == "separate":
        return select_checkpoint(candidates)
    return select_final_update(candidates, plan.updates)


# --- Tensors and loss ------------------------------------------------------------

def require_finite_weights(torch, weights: Iterable[tuple[str, Any]], *, code: str = "SFT_TRAINING") -> None:
    """Reject NaN/Inf tensor values, independently of loss, gradients or file digests."""
    with torch.no_grad():
        for name, weight in weights:
            if not bool(torch.isfinite(weight).all()):
                raise failure(f"Nonfinite adapter weight: {name}"[:200], code)


def _require_finite_adapter_file(path: Path) -> None:
    import torch
    from safetensors import safe_open

    with safe_open(path, framework="pt", device="cpu") as adapter:
        require_finite_weights(torch, ((name, adapter.get_tensor(name)) for name in adapter.keys()),
                               code="SFT_IDENTITY")


def collate(torch, examples: list[JSON], pad_id: int, device) -> JSON:
    """Right-pad; loss and attention masks follow position, so a pad equal to EOS stays supervised."""
    length = max(len(example["input_ids"]) for example in examples)
    ids, attention, labels = [], [], []
    for example in examples:
        padding = length - len(example["input_ids"])
        ids.append(example["input_ids"] + [pad_id] * padding)
        attention.append([1] * len(example["input_ids"]) + [0] * padding)
        labels.append(example["labels"] + [-100] * padding)
    return {"input_ids": torch.tensor(ids, device=device), "attention_mask": torch.tensor(attention, device=device),
            "labels": torch.tensor(labels, device=device)}


def target_loss_sum(torch, model, batch: JSON) -> tuple[Any, int]:
    """Summed target cross-entropy and token count; logits exist only at supervised positions."""
    shifted = batch["labels"][:, 1:]
    positions = (shifted != -100).any(dim=0).nonzero().squeeze(1)
    if positions.numel() == 0:
        raise failure("A batch has no supervised tokens")
    logits = model(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"], use_cache=False,
                   logits_to_keep=positions).logits
    targets = shifted[:, positions]
    total = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.size(-1)).float(), targets.reshape(-1),
                                              ignore_index=-100, reduction="sum")
    return total, int((targets != -100).sum())


def accumulate_window(runtime: TrainingRuntime, examples: list[JSON], microbatch: int) -> float:
    """Backpropagate one window; returns its token-weighted mean loss.

    Dividing every microbatch sum by the whole window's token count makes any factorization
    of the window optimize the same objective, unlike averaging microbatch means.
    """
    total_tokens = sum(len([t for t in example["labels"] if t != -100]) for example in examples)
    if total_tokens == 0:
        raise failure("A window has no supervised tokens")
    loss_sum, counted = 0.0, 0
    for start in range(0, len(examples), microbatch):
        batch = collate(runtime.torch, examples[start:start + microbatch], runtime.pad_id, runtime.device)
        with runtime.autocast():
            total, tokens = target_loss_sum(runtime.torch, runtime.model, batch)
        if not math.isfinite(float(total.detach())):
            raise failure("Nonfinite training loss")
        (total / total_tokens).backward()
        loss_sum += float(total.detach())
        counted += tokens
    if counted != total_tokens:
        raise failure("Supervised token count disagrees with the window")
    return loss_sum / total_tokens


def evaluate(runtime: TrainingRuntime, examples) -> float:
    """Sequential, gradient-free, token-weighted completion NLL; restores training mode."""
    model, torch = runtime.model, runtime.torch
    loss_sum, tokens = 0.0, 0
    model.eval()
    try:
        with torch.no_grad():
            for example in examples:
                batch = collate(torch, [example], runtime.pad_id, runtime.device)
                with runtime.autocast():
                    total, count = target_loss_sum(torch, model, batch)
                loss_sum += float(total)
                tokens += count
    finally:
        model.train()
    if tokens == 0:
        raise failure("Validation has no supervised tokens")
    return loss_sum / tokens


# --- Model preparation -----------------------------------------------------------

@dataclass
class TrainingRuntime:
    torch: Any
    model: Any
    tokenizer: Any
    device: str
    pad_id: int
    environment: JSON = field(default_factory=dict)
    autocast: Callable[[], Any] = nullcontext
    trainable: JSON = field(default_factory=dict)


def attach_lora(model, *, dropout: float = RECIPE["lora_dropout"]):
    """Standard LoRA on the attention projections of every decoder layer; everything else frozen."""
    from peft import LoraConfig, get_peft_model

    config = LoraConfig(r=RECIPE["lora_rank"], lora_alpha=RECIPE["lora_alpha"], lora_dropout=dropout,
                        bias=RECIPE["lora_bias"], target_modules=list(RECIPE["lora_targets"]), task_type="CAUSAL_LM")
    layers = model.config.num_hidden_layers
    adapted = get_peft_model(model, config)
    return adapted, validate_trainable(adapted, layers)


def validate_trainable(model, layers: int) -> JSON:
    """Only lora_A/lora_B of all four projections in all layers may train."""
    expected = {(layer, target, side) for layer in range(layers) for target in RECIPE["lora_targets"]
                for side in ("lora_A", "lora_B")}
    found, trainable, frozen = set(), 0, 0
    for name, parameter in model.named_parameters():
        is_lora = ".lora_A." in name or ".lora_B." in name
        if parameter.requires_grad and not is_lora:
            raise failure(f"Non-adapter parameter is trainable: {name}"[:200])
        if is_lora and not parameter.requires_grad:
            raise failure(f"Adapter parameter is frozen: {name}"[:200])
        if not is_lora:
            frozen += parameter.numel()
            continue
        trainable += parameter.numel()
        parts = name.split(".")
        layer = int(parts[parts.index("layers") + 1])
        target = next((t for t in RECIPE["lora_targets"] if f".{t}." in name), None)
        found.add((layer, target, "lora_A" if ".lora_A." in name else "lora_B"))
    if found != expected:
        raise failure(f"LoRA matched {len(found)} of {len(expected)} expected adapter weights")
    return {"lora_weights": len(found), "trainable_parameters": trainable, "frozen_parameters": frozen}


def _packages() -> JSON:
    versions = {}
    for name in TRAINING_PACKAGES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def load_training_model(config: SftConfig) -> TrainingRuntime:
    """Frozen NF4 base with double quantization and BF16 compute on one selected GPU, no offload."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    try:
        import torch
        import transformers
        from peft import prepare_model_for_kbit_training
    except ImportError as exc:
        raise PipelineError("MODEL_UNAVAILABLE", "Install the training extra on this host", "sft_training") from exc
    index = int(config.device.partition(":")[2] or 0)
    if not torch.cuda.is_available() or index >= torch.cuda.device_count():
        raise PipelineError("MODEL_UNAVAILABLE", "The selected GPU is not visible", "sft_training")
    if not torch.cuda.is_bf16_supported():
        raise PipelineError("MODEL_UNAVAILABLE", "The selected GPU lacks BF16 support", "sft_training")
    random.seed(SEED)
    torch.manual_seed(SEED)  # Before LoRA initialization, which draws from this generator.
    torch.cuda.manual_seed_all(SEED)
    torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(True, warn_only=True)
    tokenizer = load_tokenizer(config.base_path)
    validate_template(tokenizer)
    quantization = transformers.BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16)
    try:
        base = transformers.AutoModelForCausalLM.from_pretrained(
            config.base_path, quantization_config=quantization, dtype=torch.bfloat16, device_map={"": config.device},
            attn_implementation="sdpa", local_files_only=True, trust_remote_code=False)
        base.config.use_cache = False
        base = prepare_model_for_kbit_training(
            base, use_gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False})
        model, trainable = attach_lora(base)
    except PipelineError:
        raise
    except (ImportError, OSError, ValueError, RuntimeError) as exc:
        raise PipelineError("MODEL_UNAVAILABLE", f"Cannot prepare the NF4 model: {exc}"[:400], "sft_training") from exc
    model.train()
    return TrainingRuntime(torch, model, tokenizer, config.device,
                           tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id,
                           environment=capture_environment(torch, config.device),
                           autocast=lambda: torch.autocast("cuda", dtype=torch.bfloat16), trainable=trainable)


def capture_environment(torch, device: str) -> JSON:
    def command(*arguments) -> str | None:
        try:
            return subprocess.run(arguments, capture_output=True, text=True, timeout=120, check=True).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None

    index = int(device.partition(":")[2] or 0)
    return {"python": sys.version.split()[0], "platform": platform.platform(), "packages": _packages(),
            "cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(index),
            "gpu_memory_bytes": torch.cuda.get_device_properties(index).total_memory,
            "driver": command("nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"),
            "cudnn": torch.backends.cudnn.version(), "git_revision": command("git", "rev-parse", "HEAD"),
            "pip_freeze": command(sys.executable, "-m", "pip", "freeze")}


# --- Checkpoints -----------------------------------------------------------------

def tree_digests(root: Path) -> JSON:
    return {path.relative_to(root).as_posix(): digest(path)
            for path in sorted(root.rglob("*")) if path.is_file() and path.name != "checkpoint.json"}


def tree_sha256(files: JSON) -> str:
    return hashlib.sha256(dumps(files).encode("utf-8")).hexdigest()


def checkpoint_path(root: Path, update: int) -> Path:
    return root / "checkpoints" / f"step-{update:04d}"


def save_checkpoint(root: Path, update: int, runtime: TrainingRuntime, optimizer, scheduler, stream: RowStream,
                    coverage: Coverage, identity: JSON, nll: float | None) -> JSON:
    """Stage everything, then rename: a checkpoint directory is complete or absent.

    ``nll`` is None when the run has no validation role: both NLL and finiteness stay null.
    """
    torch = runtime.torch
    require_finite_weights(torch, ((name, p) for name, p in runtime.model.named_parameters() if p.requires_grad))
    target = checkpoint_path(root, update)
    stage = target.with_name(f".stage-{target.name}-{uuid.uuid4().hex}")
    stage.mkdir(parents=True)
    try:
        runtime.model.save_pretrained(stage / "adapter", safe_serialization=True, save_embedding_layers=False)
        rng = {"torch": torch.get_rng_state(), "python": list(random.getstate()[1])}
        if runtime.device.startswith("cuda"):
            rng["cuda"] = torch.cuda.get_rng_state(int(runtime.device.partition(":")[2] or 0))
        torch.save({"optimizer": optimizer.state_dict(), "scheduler": scheduler.state_dict(), "rng": rng,
                    "python_rng_version": random.getstate()[0], "python_rng_gauss": random.getstate()[2]},
                   stage / "trainer_state.pt")
        finite = None if nll is None else math.isfinite(nll)
        files = tree_digests(stage)
        adapter = {name: value for name, value in files.items() if name.startswith("adapter/")}
        state = {"update": update, "identity": identity, "stream": stream.state(), "coverage": coverage.record(),
                 "validation_nll": nll if finite else None, "finite": finite, "files": files,
                 "adapter_sha256": tree_sha256(adapter)}
        atomic_json(stage / "checkpoint.json", state)
        os.replace(stage, target)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return state


def read_checkpoint(path: Path, row_sources: list[str], *, identity: JSON | None = None, seed: int = SEED) -> JSON:
    """Validate a committed checkpoint against its files and a replay of its claimed progress."""
    def reject(message: str) -> PipelineError:
        return failure(f"{path.name}: {message}", "SFT_IDENTITY")

    if not (path / "checkpoint.json").is_file():
        raise reject("incomplete checkpoint")
    state = read_json(path / "checkpoint.json", "SFT_IDENTITY")
    try:
        update, files = state["update"], state["files"]
        coverage, stream = state["coverage"], state["stream"]
        claimed = (coverage["rows"], coverage["unique_rows"], coverage["unique_sources"], coverage["expected_rows"],
                   coverage["expected_sources"], stream["epoch"], stream["position"], state["identity"], state["adapter_sha256"])
    except (KeyError, TypeError) as exc:
        raise reject("malformed checkpoint state") from exc
    if tree_digests(path) != files:
        raise reject("files differ from the recorded digests")
    if tree_sha256({k: v for k, v in files.items() if k.startswith("adapter/")}) != claimed[8]:
        raise reject("adapter digest differs")
    if identity is not None and state["identity"] != identity:
        raise reject("run identity differs")
    if type(update) is not int or update <= 0:
        raise reject("invalid update")
    expected_stream, expected_coverage = replay(row_sources, update, seed)
    recorded = expected_coverage.record()
    if stream != expected_stream.state() or any(coverage[key] != recorded[key] for key in recorded):
        raise reject("sampler or coverage progress is inconsistent with the deterministic stream")
    _require_finite_adapter_file(path / "adapter" / "adapter_model.safetensors")
    return state


def restore_checkpoint(path: Path, runtime: TrainingRuntime, optimizer, scheduler) -> None:
    from peft import set_peft_model_state_dict
    from safetensors.torch import load_file

    torch = runtime.torch
    result = set_peft_model_state_dict(runtime.model, load_file(path / "adapter" / "adapter_model.safetensors"))
    if getattr(result, "unexpected_keys", None):
        raise failure(f"{path.name}: adapter holds unexpected weights", "SFT_IDENTITY")
    trainer = torch.load(path / "trainer_state.pt", map_location="cpu", weights_only=True)
    optimizer.load_state_dict(trainer["optimizer"])
    scheduler.load_state_dict(trainer["scheduler"])
    torch.set_rng_state(trainer["rng"]["torch"])
    random.setstate((trainer["python_rng_version"], tuple(trainer["rng"]["python"]), trainer["python_rng_gauss"]))
    if "cuda" in trainer["rng"] and runtime.device.startswith("cuda"):
        torch.cuda.set_rng_state(trainer["rng"]["cuda"], int(runtime.device.partition(":")[2] or 0))


def read_candidates(root: Path, plan: TrainPlan, row_sources: list[str], identity: JSON,
                    validation_mode: str = "separate") -> list[JSON]:
    """Every scheduled checkpoint, verified; final-update mode first requires the final one."""
    if validation_mode == "none" and not (checkpoint_path(root, plan.updates) / "checkpoint.json").is_file():
        raise failure(f"No committed update-{plan.updates} checkpoint: training did not complete every update",
                      "SFT_SELECTION")
    return [read_checkpoint(checkpoint_path(root, update), row_sources, identity=identity)
            for update in plan.candidates]


def finalize_selection(config_root: Path, plan: TrainPlan, row_sources: list[str], identity: JSON, *,
                       validation_mode: str = "separate") -> JSON:
    """Write ``selection.json`` and copy the chosen adapter; no eligible candidate fails the stage."""
    states = read_candidates(config_root, plan, row_sources, identity, validation_mode)
    record = select_for(validation_mode, states, plan) | {"identity": identity}
    atomic_json(config_root / "selection.json", record)
    if record["status"] != "selected":
        if validation_mode == "none":
            raise failure(f"The update-{plan.updates} checkpoint lacks full row/source coverage", "SFT_SELECTION")
        raise failure("No fully covered checkpoint has a finite validation NLL", "SFT_SELECTION")
    source = checkpoint_path(config_root, record["selected_update"]) / "adapter"
    stage = config_root / f".adapter-{uuid.uuid4().hex}"
    try:
        shutil.copytree(source, stage)
        target = config_root / "adapter"
        if target.exists():
            shutil.rmtree(target)
        os.replace(stage, target)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return record


# --- Run -------------------------------------------------------------------------

def _encoder(runtime: TrainingRuntime, config: SftConfig):
    def encode(row: JSON) -> JSON:
        try:
            encoded = encode_row(runtime.tokenizer, row, config.context_tokens, config.max_new_tokens)
        except TokenAudit as exc:
            raise failure(f"Export row no longer tokenizes: {exc.reason}", "SFT_IDENTITY") from exc
        if encoded["sha256"] != row["tokens"]["sha256"]:
            raise failure("Rendered tokens differ from the prepared export", "SFT_IDENTITY")
        return encoded

    return encode


def _feasibility(runtime: TrainingRuntime, rows, encode, microbatch: int, optimizer) -> JSON:
    """Real backward on the longest rows, leaving weights and the dropout stream untouched."""
    torch = runtime.torch
    rng = torch.get_rng_state()
    cuda = runtime.device.startswith("cuda")
    index = int(runtime.device.partition(":")[2] or 0)
    cuda_rng = torch.cuda.get_rng_state(index) if cuda else None
    longest = sorted(rows, key=lambda r: r["tokens"]["prompt"] + r["tokens"]["target"], reverse=True)[:microbatch]
    loss = accumulate_window(runtime, [encode(row) for row in longest], microbatch)
    gradients = [p.grad for p in runtime.model.parameters() if p.requires_grad and p.grad is not None]
    if not gradients or not any(bool(g.abs().sum() > 0) for g in gradients):
        raise failure("The feasibility backward produced no adapter gradient")
    report = {"loss": loss, "longest_row_tokens": longest[0]["tokens"]["prompt"] + longest[0]["tokens"]["target"],
              "peak_allocated_bytes": torch.cuda.max_memory_allocated(index) if cuda else None}
    optimizer.zero_grad(set_to_none=True)
    torch.set_rng_state(rng)
    if cuda:
        torch.cuda.set_rng_state(cuda_rng, index)
    return report


def _frozen_fingerprint(runtime: TrainingRuntime) -> str:
    """A bounded sample of frozen weights, proving the optimizer never touched them."""
    frozen = [p for p in runtime.model.parameters() if not p.requires_grad]
    sample = frozen[:: max(1, len(frozen) // 8)]
    hasher = hashlib.sha256()
    for parameter in sample:
        hasher.update(parameter.detach().to("cpu").float().numpy().tobytes())
    return hasher.hexdigest()


def _rewrite_metrics(path: Path, update: int) -> None:
    from ..jsonio import loads

    if not path.is_file():
        return
    kept = [line for line in path.read_text(encoding="utf-8").splitlines() if line and loads(line)["update"] <= update]
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text("".join(line + "\n" for line in kept), encoding="utf-8")
    os.replace(temporary, path)


def run_training(config: SftConfig, *, resume: Path | None = None, smoke: bool = False,
                 loader: Callable[[SftConfig], TrainingRuntime] = load_training_model,
                 plan: TrainPlan | None = None) -> JSON:
    """Train from a ready export; fails bounded on OOM or kernels without changing the recipe."""
    plan = plan or default_plan(config, smoke)
    if not config.validated and plan.updates not in plan.candidates:
        raise failure("Final-update selection needs a checkpoint at the last update")
    ready = load_ready_export(config)
    root = config.experiment_dir / "smoke" if plan.smoke else config.experiment_dir
    row_sources = [row["provenance"]["source_id"] for row in ready.train]
    require_coverage_budget(len(row_sources), plan)
    existing = root / "checkpoints"
    committed = sorted(p for p in existing.glob("step-*") if p.is_dir()) if existing.is_dir() else []
    if resume is None and committed:
        raise failure("Experiment already has checkpoints; resume explicitly with --resume", "SFT_IDENTITY")
    if resume is not None and (resume.resolve().parent != existing.resolve() or not committed
                               or resume.resolve() != committed[-1].resolve()):
        raise failure("--resume must name the latest committed checkpoint of this experiment", "SFT_IDENTITY")
    base = base_identity(config, hash_files=True)
    if base["files_sha256"] != ready.manifest["base"]["files_sha256"]:
        raise failure("Base snapshot differs from the prepared export", "SFT_IDENTITY")
    runtime = loader(config)
    identity = {"config_identity": config.identity(), "export_manifest_sha256": ready.manifest_sha256,
                "base_files_sha256": base["files_sha256"], "plan": plan.identity(),
                "packages": runtime.environment.get("packages"), "gpu": runtime.environment.get("gpu")}
    try:
        return _train(config, runtime, ready, root, plan, row_sources, identity, resume)
    except PipelineError:
        raise
    except runtime.torch.cuda.OutOfMemoryError as exc:
        raise failure("GPU out of memory; the recipe is not changed automatically") from exc
    except RuntimeError as exc:
        raise failure(f"Training stopped: {exc}"[:400]) from exc


def _train(config: SftConfig, runtime: TrainingRuntime, ready: ReadyExport, root: Path, plan: TrainPlan,
           row_sources: list[str], identity: JSON, resume: Path | None) -> JSON:
    torch, model = runtime.torch, runtime.model
    encode = _encoder(runtime, config)
    root.mkdir(parents=True, exist_ok=True)
    trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
    optimizer = torch.optim.AdamW(trainable, lr=RECIPE["learning_rate"], betas=tuple(RECIPE["betas"]), eps=RECIPE["eps"],
                                  weight_decay=RECIPE["weight_decay"])
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda done: lr_multiplier(done, plan.warmup))
    stream, coverage, start = RowStream(len(row_sources)), Coverage(row_sources), 0
    metrics_path = root / "training_metrics.jsonl"
    # Leftovers of a crash before a commit: stage directories and metrics past the last checkpoint.
    for stale in (root / "checkpoints").glob(".stage-*"):
        shutil.rmtree(stale, ignore_errors=True)
    if resume is None:
        _rewrite_metrics(metrics_path, 0)
    else:
        state = read_checkpoint(resume, row_sources, identity=identity)
        start = state["update"]
        restore_checkpoint(resume, runtime, optimizer, scheduler)
        stream = RowStream(len(row_sources), SEED, state["stream"]["epoch"], state["stream"]["position"])
        coverage = Coverage(row_sources, state["coverage"]["rows"],
                            {row_sources[index] for index in state["coverage"]["rows"]})
        _rewrite_metrics(metrics_path, start)
    environment = root / "environment.json"
    feasibility = _feasibility(runtime, ready.train, encode, config.microbatch, optimizer)
    frozen = _frozen_fingerprint(runtime)
    if not environment.is_file():
        atomic_json(environment, runtime.environment | {"trainable": runtime.trainable, "feasibility": feasibility,
                                                        "effective_settings": config.record()})
    validation_rows = ready.validation[:plan.validation_limit] if plan.validation_limit else ready.validation
    model.train()
    with metrics_path.open("a", encoding="utf-8", newline="\n") as metrics:
        for update in range(start + 1, plan.updates + 1):
            window = stream.next_window()
            loss = accumulate_window(runtime, [encode(ready.train[index]) for index in window], config.microbatch)
            norm = float(torch.nn.utils.get_total_norm([p.grad for p in trainable if p.grad is not None]))
            if not math.isfinite(norm):
                raise failure("Nonfinite adapter gradient")
            rate = scheduler.get_last_lr()[0]
            optimizer.step()
            require_finite_weights(torch, ((name, p) for name, p in model.named_parameters() if p.requires_grad))
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)
            coverage.add(window)
            metrics.write(dumps({"update": update, "loss": loss, "learning_rate": rate, "gradient_norm": norm,
                                 "epochs": stream.consumed / len(row_sources), "unique_rows": len(coverage.rows),
                                 "unique_sources": len(coverage.sources)}) + "\n")
            metrics.flush()
            if update in plan.candidates:
                # No validation role: nothing is evaluated, and Train is never scored in its place.
                nll = evaluate(runtime, (encode(row) for row in validation_rows)) if config.validated else None
                state = save_checkpoint(root, update, runtime, optimizer, scheduler, stream, coverage, identity, nll)
                checked = ({"validation_nll": state["validation_nll"], "finite": state["finite"]} if config.validated
                           else {"validation": "none"})
                metrics.write(dumps({"update": update, **checked, "coverage_complete": coverage.complete}) + "\n")
                metrics.flush()
            if plan.stop_after == update:
                raise failure("Stopped by test hook")
    if _frozen_fingerprint(runtime) != frozen:
        raise failure("A frozen base weight changed during training")
    if plan.smoke:
        report = {"stage": "train", "mode": "smoke", "validation_mode": config.validation_mode,
                  "feasibility": feasibility, "updates": plan.updates,
                  "trainable": runtime.trainable, "frozen_unchanged": True, "checkpoint":
                  read_checkpoint(checkpoint_path(root, plan.updates), row_sources, identity=identity)["adapter_sha256"],
                  "note": "Short feasibility evidence only; not a training result"}
        atomic_json(root / "smoke_report.json", report)
        return report
    record = finalize_selection(root, plan, row_sources, identity, validation_mode=config.validation_mode)
    return {"stage": "train", "mode": "full", "selection_mode": record["mode"],
            "selected_update": record["selected_update"], "candidates": record["candidates"],
            "epochs": stream.consumed / len(row_sources)}
