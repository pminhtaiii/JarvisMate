"""One experiment per invocation, fixed budget, clean-G checkpoint selection."""
from __future__ import annotations

import math
import random
from pathlib import Path

from .config import EXPERIMENTS, content_hash
from .storage import (file_hash, new_directory, read_json, read_jsonl, source_provenance,
                      seal, verify_seal, write_json, write_jsonl)

DEFAULTS = {"schema": "lifemate-llm-training-v1", "method": "lora", "precision": "bf16", "rank": 8,
            "alpha": 16, "dropout": .05, "seed": 42, "sampler_seed": 42, "view_seed": 43,
            "max_updates": 500, "accumulation": 16, "lr": 1e-4, "betas": [.9, .999], "eps": 1e-8,
            "weight_decay": .01, "warmup_updates": 25, "save_every": 100, "p_noisy": .5}


def learning_rate_multiplier(completed_updates, total, warmup):
    """The first of 25 warmup updates uses lr/25; lr reaches zero after update 500."""
    if completed_updates < warmup:
        return (completed_updates + 1) / warmup
    return max(0., (total - completed_updates) / (total - warmup))


def training_settings(path: Path):
    settings = read_json(path)
    if set(settings) != set(DEFAULTS) or settings["method"] not in {"lora", "nf4"} or settings["precision"] not in {"bf16", "fp16"}:
        raise ValueError("Incomplete/unknown training profile")
    for k, v in DEFAULTS.items():
        if k not in {"method", "precision"} and settings[k] != v:
            raise ValueError(f"Shared default changed: {k}; a reviewed new policy/suite is required")
    return settings


class BaseSampler:
    def __init__(self, size, seed=42):
        if size <= 0:
            raise ValueError("Empty clean corpus")
        self.size, self.seed, self.epoch, self.cursor = size, seed, 0, 0

    def order(self):
        order = list(range(self.size))
        random.Random(self.seed + self.epoch).shuffle(order)
        return order

    def window(self, accumulation):
        if self.cursor == self.size:
            self.epoch += 1
            self.cursor = 0
        selected = self.order()[self.cursor:self.cursor + accumulation]
        self.cursor += len(selected)
        return selected

    def state_dict(self):
        return vars(self).copy()

    def load_state_dict(self, state):
        if set(state) != set(vars(self)) or (state["size"], state["seed"]) != (self.size, self.seed) \
                or not 0 <= state["cursor"] <= self.size or state["epoch"] < 0:
            raise ValueError("Sampler identity/cursor mismatch")
        self.epoch, self.cursor = state["epoch"], state["cursor"]


def clean_nll(model, cache, torch):
    from .losses import completion_loss
    from .progress import Progress
    if not cache:
        raise ValueError("No accepted clean-G Validation tokens")
    was_training = model.training
    model.eval()
    try:
        progress = Progress("validation NLL",len(cache))
        with torch.inference_mode():
            values = []
            for item in cache:
                values.append(float(completion_loss(model, item, torch)))
                progress.advance(len(values))
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Nonfinite clean-G NLL")
        return sum(values) / len(values)
    finally:
        model.train(was_training)


def loop(model, optimizer, scheduler, scaler, rows, cache, validation, weights, settings,
         directory, binding, torch, np, *, resume=None, view_sampler=None, tokenize=None, stop_after=None, artifact_root=None):
    """Shared real update loop, also exercised by the download-free tiny model test."""
    from . import checkpoints
    from .losses import mean_weight, optimizer_update
    from .progress import Progress
    sampler = BaseSampler(len(rows), settings["sampler_seed"])
    artifact_root = artifact_root or directory.parent
    state = {"step": 0, "remaining_updates": settings["max_updates"], "best": None, "history": [], "visits": [],
             "sampler": sampler.state_dict(), "view": None}
    if resume:
        state = checkpoints.restore(resume, binding, model, optimizer, scheduler, scaler, torch, np)
        sampler.load_state_dict(state["sampler"])
        if view_sampler:
            if state["view"] is None:
                raise ValueError("Missing view RNG")
            view_sampler.load_state_dict(state["view"])
        if state["best"]:
            from ..jsonio import contained
            best_path = contained(artifact_root, state["best"]["checkpoint"], must_exist=False)
            write_json(directory / "best.json", {**state["best"], "root": "suite",
                       "identity": verify_seal(best_path)["identity"]})
    mu_w = mean_weight(rows, weights)
    model.train()
    progress = Progress(f"train {binding.get('experiment','LLM')}",settings['max_updates'],initial=state['step'])
    while state["step"] < settings["max_updates"]:
        indices, window = sampler.window(settings["accumulation"]), []
        for i in indices:
            row, tokens = rows[i], cache[i]
            visit = {"base_row_id": row["provenance"]["base_row_id"], "view": "clean"}
            if view_sampler:
                selected, visit = view_sampler.choose(row)
                tokens = tokenize(selected) if selected is not row else tokens
            state["visits"].append(visit | {"target_type": row["target_type"], "source_id": row["provenance"]["source_id"],
                "tool": row.get("target", {}).get("tool_calls", [{}])[0].get("function", {}).get("name")})
            window.append((tokens, row["target_type"]))
        next_step = state['step']+1
        used_lr = optimizer.param_groups[0]['lr']
        progress.note(f"update {next_step}/{settings['max_updates']}")
        update = optimizer_update(model, optimizer, scheduler, scaler, window, weights, mu_w, torch,
            on_row=lambda done,total:progress.note(f"update {next_step}/{settings['max_updates']}, row {done}/{total}"))
        state["step"] += 1
        state["remaining_updates"] = settings["max_updates"] - state["step"]
        state["history"].append({"step": state["step"], "mu_w": mu_w, **update})
        state["sampler"] = sampler.state_dict()
        state["view"] = view_sampler.state_dict() if view_sampler else None
        loss = sum(row['unweighted'] for row in update['losses'])/update['rows']
        progress.advance(state['step'],f"loss={loss:.4f} | lr={used_lr:.3g}",force=True)
        if state["step"] % settings["save_every"] == 0 or state["remaining_updates"] == 0 or stop_after == state["step"]:
            progress.note('validation / checkpoint',force=True)
            nll = clean_nll(model, validation, torch)
            state["history"][-1]["clean_G_nll"] = nll
            better = state["best"] is None or checkpoints.checkpoint_key(nll, state["step"]) < checkpoints.checkpoint_key(
                state["best"]["nll"], state["best"]["step"])
            if better:
                candidate_path = directory / "checkpoints" / f"step-{state['step']:06d}"
                state["best"] = {"nll": nll, "step": state["step"],
                                 "checkpoint": candidate_path.relative_to(artifact_root).as_posix()}
            checkpoint = checkpoints.save(directory / "checkpoints", model, optimizer, scheduler, scaler,
                                          state, binding, torch, np)
            if better:
                write_json(directory / "best.json", {**state["best"], "root": "suite",
                    "identity": verify_seal(checkpoint)["identity"]}, exclusive=False)
            write_jsonl(directory / "training-history.jsonl", state["history"], exclusive=False)
            progress.note(f"checkpoint saved | clean_G_nll={nll:.4f} | best_step={state['best']['step']}",force=True)
            if stop_after == state["step"]:
                break
    return state


def train(config, suite_dir: Path, experiment: str, settings: dict, *, resume=None, policy_report=None,
          resource_record: Path, latency_decision: Path):
    from .acceptance import accepted_corpus, evaluation_readiness
    from .corpus import load_suite
    from .qualification import verify_qualification
    from ..provenance import code_identity
    if experiment == "L0":
        raise ValueError("L0 has no training phase")
    from .resources import validate_lock
    environment_lock = validate_lock(config)
    loaded = load_suite(suite_dir)
    readiness = evaluation_readiness(config, suite_dir, teacher_forced=True)
    corpus = accepted_corpus(config, suite_dir)
    qualified = verify_qualification(resource_record, corpus, settings, config)
    decision = read_json(latency_decision)
    if (decision.get("schema") != "lifemate-audio-latency-decision-v1" or not decision.get("operator")
            or decision.get("suite_seal") != loaded["seal"]["identity"]
            or decision.get("decision") not in {"pilot_reviewed", "proceed_with_unresolved_audio_latency"}
            or not decision.get("reason")):
        raise ValueError("Explicit operator latency review/unresolved decision required")
    weights = EXPERIMENTS[experiment]["weights"]
    views, view_sampler = None, None
    if experiment == "L3":
        weights, views = l3_dependencies(suite_dir, policy_report, corpus, config=config)
        from .asr_views import ViewSampler
        view_sampler = ViewSampler(views, settings["view_seed"], settings["p_noisy"])
        noisy_tokens = accepted_corpus(config, suite_dir, scope="asr")
        qualified_lengths = read_json(resource_record)["lengths"]
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if max(c[key] for c in noisy_tokens["cache"]) > max(c[key] for c in qualified_lengths):
                raise ValueError("Approved noisy lengths exceed the qualification; explicitly reprobe with --include-asr")
    rows = [r for r in corpus["rows"] if r["provenance"]["partition"] == "fit"]
    cache_by_id = {c["row_id"]: c for c in corpus["cache"]}
    fit = [cache_by_id[r["row_id"]] for r in rows]
    validation = [cache_by_id[r["row_id"]] for r in corpus["rows"] if r["provenance"]["partition"] == "validation"]
    from .models import load_training_model
    from .resources import host_inventory
    environment = host_inventory(suite_dir)
    binding = {"experiment": experiment, "settings": settings, "corpus": corpus["identity"], "readiness": readiness,
               "weights": weights,
               "code": code_identity(), "packages": environment["packages"], "gpu": environment["gpus"],
               "resource_qualification": qualified, "latency_decision": file_hash(latency_decision),
               "environment_lock": environment_lock,
               "l3_policy": file_hash(policy_report) if policy_report else None}
    # Free VRAM is observation metadata, not a resume identity.
    binding["gpu"] = [{k: v for k, v in g.items() if k not in {"free", "allocation"}} for g in binding["gpu"]]
    if resume:
        if not resume.resolve().is_relative_to(suite_dir.resolve()):
            raise ValueError("Resume checkpoint must remain in this suite")
        from .checkpoints import load
        load(resume, binding)
    directory = new_directory(suite_dir / experiment, "train")
    write_json(directory / "resolved-config.json", settings)
    write_json(directory / "provenance.json", binding)
    write_json(directory / "resources.json", environment)
    write_json(directory / "manifest.started.json", {"status": "running", "binding": binding, "source": source_provenance(config.project_root)})
    try:
        model, tokenizer, metadata = load_training_model(config.require("model_dir"), settings)
        import torch
        import numpy as np
        optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=settings["lr"],
            betas=tuple(settings["betas"]), eps=settings["eps"], weight_decay=settings["weight_decay"])
        scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda completed: learning_rate_multiplier(
            completed, settings["max_updates"], settings["warmup_updates"]))
        scaler = torch.amp.GradScaler("cuda", enabled=settings["precision"] == "fp16")
        from .tokenization import supervised
        tokenize = lambda r: supervised(tokenizer, r["input"]["messages"], r["input"]["tools"], r["target"])
        state = loop(model, optimizer, scheduler, scaler, rows, fit, validation, weights, settings, directory,
                     binding, torch, np, resume=resume, view_sampler=view_sampler, tokenize=tokenize, artifact_root=suite_dir)
        result = {"status": "completed_full_budget", "experiment": experiment, "completed_updates": state["step"],
                  "remaining_updates": state["remaining_updates"], "best": state["best"], "model": metadata,
                  "binding": binding, "readiness": readiness, "submission_ready": False}
        write_json(directory / "manifest.json", result)
        if experiment == "L3":
            write_jsonl(directory / "view-visits.jsonl", state["visits"])
            from .asr_views import coverage_report
            from ..jsonio import contained
            source_views = contained(suite_dir, noisy_tokens["report"]["view_binding"]["directory"], must_exist=False)
            noisy_audits = read_jsonl(source_views / "asr-view-audit.jsonl")
            write_json(directory / "asr-training-coverage.json", coverage_report(rows, noisy_audits, state["visits"]))
        seal(directory, [p.name for p in directory.iterdir() if p.is_file()])
        return result | {"directory": str(directory)}
    except BaseException as exc:
        write_json(directory / "failure.json", {"status": "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed_training",
                   "error": type(exc).__name__, "latest_durable": read_json(directory / "latest.json") if (directory / "latest.json").exists() else None})
        raise


def l3_dependencies(suite_dir, policy_report, corpus, *, config=None):
    if policy_report is None:
        raise ValueError("L3 requires the explicit saved RV018 report")
    from .corpus import sealed_policy
    from .reporting import verify_weighting_report
    record = read_json(policy_report)
    if record.get("selection_policy_sha256") != sealed_policy(suite_dir)["policy_sha256"]:
        raise ValueError("L3 comparison policy mismatch")
    from .corpus import load_suite
    selected_policy = verify_weighting_report(suite_dir, record, config=config)
    from .acceptance import accepted_corpus
    from .config import config_from_suite
    loaded = load_suite(suite_dir)
    noisy = accepted_corpus(config or config_from_suite(loaded["suite"]), suite_dir, scope="asr")
    views = {}
    for row in noisy["rows"]:
        views.setdefault(row["provenance"]["base_row_id"], []).append(row)
    if not views:
        raise ValueError("No token-valid approved Fit noisy views")
    return EXPERIMENTS[selected_policy]["weights"], views
