"""Manual preparation/probe lifecycle; no experiment chaining entrypoint exists."""
from __future__ import annotations

from pathlib import Path
import sys

from asr.pretrained.data import audio_asset
from lifemate.model_budget import check_budget
from .augmentation import load_noises
from .config import load_config, prerequisites, binding
from .data import load_suite
from .storage import (read, write, rows, now, environment, code_identity, run_directory,
                      suite_lock, records, seal, verify, identity, outcome)
from .workers import once, Session
from . import checkpoints


class WorkerFailure(RuntimeError):
    def __init__(self, result: dict):
        super().__init__(result.get("error", "Worker failed"))
        self.result = result


def checked(result: dict, *, ready: bool = False) -> dict:
    if result.get("status") != ("ready" if ready else "ok"):
        raise WorkerFailure(result)
    return result


def resolve(suite_path: Path, config_path: Path, experiment: str,
            noise_manifest: Path | None = None) -> tuple[dict, list, list, dict]:
    suite, fit, val = load_suite(suite_path)
    config = prerequisites(suite_path, load_config(config_path, experiment))
    if experiment == "E4":
        config["noises"] = load_noises(noise_manifest, Path(suite["data_root"]))
    return suite, fit, val, config


def job(suite: dict, config: dict, *, mode: str, hardware: dict | None = None, **extra) -> dict:
    return {"mode": mode, "config": config, "snapshot": suite["model"]["path"],
            "base_parameters": suite["model"]["provenance"]["parameter_count"],
            "expected_hardware": hardware, **extra}


def hardware_binding(suite, config):
    result = checked(once(job(suite, config, mode="hardware"), config["load_timeout_seconds"]))
    value = binding(config, suite, result["hardware"], code_identity(), environment())
    return result, value


def require_same_baseline(suite_path: Path, config: dict, hardware_record: dict) -> None:
    if config["experiment"] == "E0":
        return
    baseline = outcome(suite_path, "E0")
    if not baseline or baseline[1]["status"] != "completed":
        raise ValueError("A completed E0 is required")
    manifest = baseline[1]
    if (manifest.get("hardware") != hardware_record["hardware"]
            or manifest.get("environment") != environment()
            or manifest.get("code", {}).get("hash") != code_identity()["hash"]):
        raise ValueError("GPU/code/environment differs from E0; rebaseline E0 on the current stack first")
    original = read(baseline[0] / "resolved-config.json")
    if original["inference_dtype"] != config["inference_dtype"] or original["seed"] != config["seed"]:
        raise ValueError("Inference seed/dtype differs from E0")


def initialize_run(path, suite, config, kind):
    manifest = {"schema": "asr-ft-run-v1", "kind": kind, "experiment": config["experiment"],
                "status": "running", "created": now(), "suite_identity": suite["identity"],
                "argv": list(sys.argv),
                "config_hash": identity(config), "code": code_identity(), "environment": environment(),
                "model_revision": suite["model"]["provenance"]["revision"],
                "model_identity": identity(suite["model"]), "source": suite["source"],
                "split_identity": suite["split_identity"], "fit_identity": suite["fit_identity"],
                "selection_identity": suite["selection_identity"], "evaluation_policy": suite["policy"],
                "determinism": {"seed": config["seed"], "algorithms": True,
                                "cublas_workspace_config": ":4096:8", "tf32": False,
                                "cudnn_benchmark": False},
                "updates": 0, "best_step": 0}
    write(path / "resolved-config.json", config)
    from importlib.metadata import distributions
    locked = sorted({f"{d.metadata['Name']}=={d.version}" for d in distributions() if d.metadata.get("Name")})
    (path / "requirements-resolved.txt").write_text("\n".join(locked) + "\n", encoding="utf-8")
    write(path / "manifest.json", manifest)
    return manifest


def fail(path, manifest, exc):
    if isinstance(exc, WorkerFailure):
        result = exc.result
        manifest.update(status=result.get("status", "failed"), error=str(exc), failure=result)
    elif isinstance(exc, KeyboardInterrupt):
        manifest.update(status="interrupted", error="User interrupted; explicit resume from a durable checkpoint only")
    else:
        manifest.update(status="failed", error=f"{type(exc).__name__}: {str(exc)[:2000]}")
    manifest["finished"] = now()
    write(path / "manifest.json", manifest)


def token_audit(suite, fit, validation):
    from asr.pretrained.models import offline
    offline()
    from transformers import WhisperTokenizer
    tokenizer = WhisperTokenizer.from_pretrained(suite["model"]["path"], local_files_only=True,
                                                 language="vi", task="transcribe")
    config = read(Path(suite["model"]["path"]) / "config.json")
    limit = config.get("max_target_positions", 448) - 1
    maximum, longest = 0, None
    for row in fit + validation:
        tokens = tokenizer(row["reference"].strip()).input_ids
        if tokens and tokens[0] == config["decoder_start_token_id"]:
            tokens = tokens[1:]
        if not tokens or len(tokens) > limit:
            raise ValueError(f"Overlong/empty transcript tokens: {row['utterance_id']}; never truncate")
        if len(tokens) > maximum:
            maximum, longest = len(tokens), row["utterance_id"]
    return {"maximum_label_tokens": maximum, "longest": longest, "limit": limit,
            "generation_max_new_tokens": 440, "rows_checked": len(fit) + len(validation)}


def preflight(suite_path: Path, config_path: Path, experiment: str, noise_manifest=None) -> dict:
    with suite_lock(suite_path):
        suite, fit, val, config = resolve(suite_path, config_path, experiment, noise_manifest)
        path = run_directory(suite_path, experiment, "probe")
        manifest = initialize_run(path, suite, config, "probe")
        try:
            manifest["phase"] = "hardware"
            write(path / "manifest.json", manifest)
            hardware, bound = hardware_binding(suite, config)
            require_same_baseline(suite_path, config, hardware)
            manifest.update(binding=bound, hardware=hardware["hardware"], precision=hardware["precision"],
                            gpu_probe=hardware)
            write(path / "token-audit.json", token_audit(suite, fit, val))
            checkpoint, memory = None, None
            if experiment != "E0":
                manifest["phase"] = "gradient_optimizer_probe"
                write(path / "manifest.json", manifest)
                response = checked(once(job(suite, config, mode="train", hardware=hardware["hardware"],
                     fit_path=str(suite_path / "data/fit.jsonl"), output=str(path), data_root=suite["data_root"],
                     binding=bound, probe=True, noises=config.get("noises", [])), config["worker_timeout_seconds"]))
                checkpoint, memory = response["checkpoint"], response["memory"]
                manifest["training_probe"] = response
            # Fresh process verifies native E3 quantization, adapter reload and generation.
            manifest["phase"] = "fresh_reload_generation_probe"
            write(path / "manifest.json", manifest)
            session = Session(job(suite, config, mode="inference", hardware=hardware["hardware"],
                                  checkpoint=checkpoint, native=experiment == "E3"))
            try:
                initialization = checked(session.receive(config["load_timeout_seconds"]), ready=True)
                if experiment == "E3" and initialization["quantized_modules"] == 0:
                    raise WorkerFailure({"status": "unsupported", "error": "No real NF4 modules after reload"})
                selected = [max(fit, key=lambda r: r["duration_seconds"]), fit[len(fit)//2], fit[0]]
                for row in selected:
                    checked(session.request(audio_asset(Path(suite["data_root"]) / "train", row["audio"]),
                                            config["timeout_seconds"]))
            finally:
                closing = session.close()
            manifest.update(status="passed", initialization=initialization, train_memory=memory,
                            inference_memory=closing.get("memory") if closing else None, finished=now())
        except BaseException as exc:
            fail(path, manifest, exc)
            # Binding/data/resource failures do not establish NF4 incompatibility.
            if (experiment == "E3" and isinstance(exc, WorkerFailure)
                    and manifest.get("phase") in {"gradient_optimizer_probe", "fresh_reload_generation_probe"}
                    and manifest["status"] == "failed"
                    and not exc.result.get("error", "").startswith("ResourceLimit:")):
                manifest["status"] = "unsupported"
        write(path / "manifest.json", manifest)
        seal(path)
        return {"path": str(path), **manifest}


def require_probe(suite_path: Path, experiment: str, bound: dict):
    candidates = records(suite_path, experiment, "probe")
    if not candidates:
        raise ValueError("Run the requested experiment's preflight first")
    path, manifest = candidates[-1]
    verify(path)
    if manifest["status"] != "passed" or manifest["binding"] != bound:
        raise ValueError("Preflight missing/stale/failed: config, model, data, environment, code and GPU must match")
    return manifest
