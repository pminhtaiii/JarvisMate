"""One shared epoch/update loop for E1/E2/E3/E4, isolated in a GPU worker."""
from __future__ import annotations

import math
from pathlib import Path
import random
import time

from . import checkpoints
from .models import batch, gradient_report, prepare_labels, validate_trainable
from .resources import Unsupported
from .storage import append, rows, read, write


def schedule_factor(step: int, total: int, ratio: float) -> float:
    warmup = max(1, math.ceil(total * ratio)) if ratio else 0
    if step < warmup:
        return (step + 1) / warmup
    return max(0., (total - step) / max(1, total - warmup))


def train_epoch(model, processor, job: dict, torch, np, memory) -> dict:
    config = job["config"]
    fit = rows(Path(job["fit_path"]))
    if not fit or any(r["partition"] != "train" for r in fit):
        raise ValueError("Training worker only accepts frozen Train rows")
    # Audit every label before creating optimizer state; never truncate any label.
    lengths = [len(prepare_labels(processor, model, r["reference"])) for r in fit]
    scope = validate_trainable(model, config["scope"])
    parameters = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(parameters, lr=config["learning_rate"], weight_decay=config["weight_decay"],
                                 betas=(.9, .999), eps=1e-8)
    total = math.ceil(len(fit) / config["accumulation"]) * config["max_epochs"]
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda step: schedule_factor(step, total, config["warmup_ratio"]))
    cuda_training = next(model.parameters()).device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=cuda_training and job["precision"] == "float16")
    state = {"step": 0, "epoch": 0, "cursor": 0}
    if job.get("checkpoint"):
        state = checkpoints.restore(Path(job["checkpoint"]), job["binding"], optimizer, scheduler, scaler, torch, np)
    epoch = state["epoch"]
    order = list(range(len(fit)))
    random.Random(config["seed"] + epoch).shuffle(order)
    if job.get("probe"):
        hard = [max(range(len(fit)), key=lambda i: fit[i]["duration_seconds"]),
                max(range(len(fit)), key=lambda i: lengths[i]), order[len(order)//2]]
        needed = config["probe_updates"] * config["accumulation"]
        order = (hard * math.ceil(needed / len(hard)))[:needed]
        state = {"step": 0, "epoch": 0, "cursor": 0}
    noises = job.get("noises", [])
    directory = Path(job["output"])
    data_root = Path(job["data_root"])
    stop_step = config.get("update_budget", total)
    changed = {"encoder": False, "decoder": False}
    checkpoint = None
    with memory.phase("training"):
        for cursor in range(state["cursor"], len(order), config["accumulation"]):
            if state["step"] >= stop_step:
                break
            indices = order[cursor:cursor + config["accumulation"]]
            optimizer.zero_grad(set_to_none=True)
            before = {name: p.detach().cpu().clone() for name, p in model.named_parameters()
                      if p.requires_grad} if job.get("probe") else None
            loss_value = 0.
            started = time.perf_counter()
            for i in indices:
                inputs, augmentation = batch(fit[i], data_root, processor, model, config, epoch, noises, np, torch)
                with torch.autocast("cuda" if cuda_training else "cpu", dtype=getattr(torch, job["precision"]),
                                    enabled=cuda_training):
                    loss = model(**inputs).loss
                if not torch.isfinite(loss):
                    raise Unsupported("Training loss is NaN/Inf")
                loss_value += float(loss.detach()) / len(indices)
                scaler.scale(loss / len(indices)).backward()
                if augmentation:
                    append(directory / "augmentation.jsonl", augmentation)
            scaler.unscale_(optimizer)
            gradients = gradient_report(model, config["scope"])
            torch.nn.utils.clip_grad_norm_(parameters, config["max_grad_norm"], error_if_nonfinite=True)
            scale = scaler.get_scale()
            scaler.step(optimizer)
            scaler.update()
            if scaler.get_scale() < scale:
                raise Unsupported("FP16 optimizer update skipped; create a stable precision profile")
            scheduler.step()
            if before is not None:
                for name, parameter in model.named_parameters():
                    if name in before and not torch.equal(before[name], parameter.detach().cpu()):
                        changed["encoder" if ".encoder." in name else "decoder"] = True
            state.update(step=state["step"] + 1, cursor=cursor + len(indices))
            append(directory / "train-log.jsonl", {**state, "loss": loss_value,
                   "lr": optimizer.param_groups[0]["lr"], "gradient_norms": gradients,
                   "effective_batch": len(indices), "seconds": time.perf_counter() - started})
            if state["step"] % config["checkpoint_updates"] == 0:
                checkpoint = checkpoints.save(directory / "checkpoints", model, optimizer, scheduler, scaler,
                                              state, job["binding"], torch, np)
            if job.get("probe") and state["step"] >= config["probe_updates"]:
                break
        state.update(epoch=epoch + 1, cursor=0)
        checkpoint = checkpoints.save(directory / "checkpoints", model, optimizer, scheduler, scaler,
                                      state, job["binding"], torch, np)
    if job.get("probe"):
        required = ("encoder", "decoder") if config["scope"] == "encoder_decoder" else ("decoder",)
        if any(not changed[group] for group in required):
            raise Unsupported("Smoke optimizer did not change adapter weights in every required scope")
    return {"checkpoint": str(checkpoint), "state": state, "adapter": scope,
            "probe_updates_verified": changed if job.get("probe") else None}
