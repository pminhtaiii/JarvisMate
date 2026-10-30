"""Run exactly one requested experiment; each GPU phase has its own process."""
from __future__ import annotations

from pathlib import Path

from . import checkpoints
from .storage import (suite_lock, run_directory, read, write, append, now, rows, identity, verify)
from .orchestration import (resolve, initialize_run, hardware_binding, require_probe, require_same_baseline, checked, job, fail, WorkerFailure)
from .workers import once
from .evaluation import evaluate, slot_evaluator
from .selection import checkpoint_key
from .exporting import export


def owned(suite: Path, path: Path) -> Path:
    path = path.resolve()
    if not path.is_relative_to(suite.resolve()):
        raise ValueError("Checkpoint/evaluation path must belong to this suite")
    return path


def resume_manifest(suite_path: Path, checkpoint: Path, bound: dict, config: dict) -> tuple[dict, dict]:
    checkpoint = owned(suite_path, checkpoint)
    # checkpoint parent is checkpoints/, then the owning run directory.
    run = checkpoint.parent.parent
    manifest = read(run / "manifest.json")
    if manifest["kind"] != "run" or manifest["experiment"] != config["experiment"]:
        raise ValueError("Cannot resume another experiment or a preflight probe checkpoint")
    state = checkpoints.load(checkpoint, bound)["training"]
    if state["epoch"] >= config["max_epochs"] or state["step"] >= config.get("update_budget", float("inf")):
        raise ValueError("Checkpoint already exhausted its frozen training budget")
    return manifest, state


def run(suite_path: Path, config_path: Path, experiment: str, *, noise_manifest=None,
        resume_from: Path | None = None) -> dict:
    with suite_lock(suite_path):
        suite, fit, validation, config = resolve(suite_path, config_path, experiment, noise_manifest)
        path = run_directory(suite_path, experiment, "run")
        manifest = initialize_run(path, suite, config, "run")
        try:
            manifest["phase"] = "hardware_and_binding"
            write(path / "manifest.json", manifest)
            hardware, bound = hardware_binding(suite, config)
            require_same_baseline(suite_path, config, hardware)
            require_probe(suite_path, experiment, bound)
            manifest.update(binding=bound, precision=hardware["precision"], hardware=hardware["hardware"],
                            gpu_probe=hardware)
            write(path / "manifest.json", manifest)
            slots = slot_evaluator(suite_path, validation)
            base_job = job(suite, config, mode="inference", hardware=hardware["hardware"])
            if experiment == "E0":
                if resume_from:
                    raise ValueError("E0 has no training checkpoint to resume")
                manifest["phase"] = "primary_evaluation"
                write(path / "manifest.json", manifest)
                metrics = evaluate(base_job, validation, Path(suite["data_root"]), path / "primary", slots)
                manifest.update(metrics=metrics, best_evaluation=str(path / "primary"), best_checkpoint=None)
                if metrics["coverage"] != 1:
                    raise WorkerFailure({"status": metrics.get("failure_status") or "failed",
                                         "error": metrics.get("error") or "E0 did not complete all primary utterances"})
            else:
                checkpoint = str(resume_from.resolve()) if resume_from else None
                state, stale, best = {"step": 0, "epoch": 0, "cursor": 0}, 0, None
                if resume_from:
                    previous, state = resume_manifest(suite_path, resume_from, bound, config)
                    # Recover only evaluated history at/before the explicitly chosen checkpoint.
                    histories = rows(resume_from.parent.parent / "evaluation-history.jsonl") if (resume_from.parent.parent / "evaluation-history.jsonl").exists() else []
                    histories = [h for h in histories if h["step"] <= state["step"]]
                    for history in histories:
                        append(path / "evaluation-history.jsonl", history)
                        key = checkpoint_key(history["metrics"], history["step"])
                        if best is None or key < best:
                            best = key
                            manifest.update(best_step=history["step"], best_checkpoint=history["checkpoint"],
                                            best_evaluation=history["evaluation"], metrics=history["metrics"])
                            stale = 0
                        else:
                            stale += 1
                    manifest["resume_from"] = checkpoint
                while state["epoch"] < config["max_epochs"] and state["step"] < config.get("update_budget", float("inf")):
                    manifest["phase"] = f"training_epoch_{state['epoch']+1}"
                    write(path / "manifest.json", manifest)
                    response = checked(once(job(suite, config, mode="train", hardware=hardware["hardware"],
                         checkpoint=checkpoint, fit_path=str(suite_path / "data/fit.jsonl"),
                         data_root=suite["data_root"], output=str(path), binding=bound,
                         noises=config.get("noises", [])), config["worker_timeout_seconds"]))
                    checkpoint, state = response["checkpoint"], response["state"]
                    manifest.update(updates=state["step"], latest_checkpoint=checkpoint,
                                    trainable_parameters=response["adapter"]["adapter_parameters"])
                    old_memory = manifest.get("train_memory")
                    memory = response["memory"]
                    if old_memory:
                        memory["peak_allocated_gib"] = max(old_memory["peak_allocated_gib"], memory["peak_allocated_gib"])
                        memory["peak_reserved_gib"] = max(old_memory["peak_reserved_gib"], memory["peak_reserved_gib"])
                    manifest["train_memory"] = memory
                    if experiment == "E3":
                        manifest["phase"] = "native_nf4_evaluation"
                        write(path / "manifest.json", manifest)
                        native = evaluate(base_job | {"checkpoint": checkpoint, "native": True}, validation,
                            Path(suite["data_root"]), path / "native-4bit" / f"step-{state['step']:08d}", slots)
                        if native["coverage"] != 1:
                            raise RuntimeError("NF4 generation failed after training")
                    evaluation_path = path / "primary" / f"step-{state['step']:08d}"
                    manifest["phase"] = "primary_evaluation"
                    write(path / "manifest.json", manifest)
                    metrics = evaluate(base_job | {"checkpoint": checkpoint}, validation,
                                       Path(suite["data_root"]), evaluation_path, slots)
                    if metrics["coverage"] != 1:
                        if experiment == "E3":
                            manifest["status"] = "export_unavailable"
                        raise RuntimeError("Merged half-precision evaluation is incomplete")
                    record = {"step": state["step"], "epoch": state["epoch"], "checkpoint": checkpoint,
                              "evaluation": str(evaluation_path), "metrics": metrics}
                    append(path / "evaluation-history.jsonl", record)
                    key = checkpoint_key(metrics, state["step"])
                    if best is None or key < best:
                        best, stale = key, 0
                        manifest.update(best_step=state["step"], best_checkpoint=checkpoint,
                                        best_evaluation=str(evaluation_path), metrics=metrics)
                        write(path / "best-checkpoint.json", {"checkpoint": checkpoint, "step": state["step"],
                              "selection": "CSA/normalized-WER/CER/latency/step" if slots.status == "available" else "provisional-WER/CER/step",
                              "slot_status": slots.status})
                    else:
                        stale += 1
                    write(path / "manifest.json", manifest)
                    # E4 is stopped at the control's actual update budget, not earlier by a different patience outcome.
                    if stale >= config["patience"] and experiment != "E4":
                        break
                if not manifest.get("best_checkpoint"):
                    raise RuntimeError("No fully evaluated checkpoint was selected")
                evaluated = rows(owned(suite_path, Path(manifest["best_evaluation"])) / "transcripts.jsonl")
                manifest["phase"] = "export_roundtrip"
                write(path / "manifest.json", manifest)
                exported = export(suite, config, hardware["hardware"],
                                  owned(suite_path, Path(manifest["best_checkpoint"])), path / "exports/best", evaluated)
                manifest["export"] = exported
                manifest["phase"] = "export_full_evaluation"
                write(path / "manifest.json", manifest)
                metrics = evaluate(base_job | {"snapshot": exported["path"]}, validation,
                                   Path(suite["data_root"]), path / "export-evaluation", slots)
                if metrics["coverage"] != 1:
                    raise RuntimeError("Final offline export did not complete full Validation")
                manifest.update(metrics=metrics, best_evaluation=str(path / "export-evaluation"))
            manifest.update(status="completed", finished=now())
        except BaseException as exc:
            prior = manifest["status"]
            fail(path, manifest, exc)
            if prior == "export_unavailable":
                manifest["status"] = prior
        write(path / "manifest.json", manifest)
        return {"path": str(path), **manifest}
