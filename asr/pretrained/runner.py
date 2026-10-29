"""Sequential persistent model workers, hard timeouts and durable evaluation artifacts."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import multiprocessing
from multiprocessing.connection import Connection
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

from lifemate.jsonio import dumps, visible_path
from lifemate.model_budget import check_budget

from .data import audio_asset, identity, load_selection
from .metrics import NORMALIZATION, normalize, score, summarize
from .models import adapter, local_spec, offline, packages, require_paired_source

TIMING = {
    "version": "worker-wav-to-text-v1", "clock": "time.perf_counter",
    "includes": ["read WAV", "PCM decode", "feature extraction", "device transfer", "generation", "text decode"],
    "excludes": ["asset/model hashing", "model loading", "warm-up", "IPC", "scoring", "artifact writes"],
    "sync": "CUDA synchronize before/after; CT2 synchronous and segments fully consumed",
    "timeout": "parent wall-clock includes IPC; terminate model worker, no retry; remaining rows not_run",
    "warmup": "repeat first selected audio, no reference/context supplied, excluded from metrics",
    "p95": "nearest rank ceil(0.95*N)",
    "failed_metrics": "score failed/timeout/not_run rows as empty hypotheses; keep full selected denominator",
    "latency_population": "attempted rows with measured time, including errors/timeouts; not_run excluded",
}


def write_json(path: Path, value: dict) -> None:
    visible_path(path)
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(dumps(value) + "\n", encoding="utf-8")
    pending.replace(path)


def worker_main(connection: Connection, spec: dict, settings: dict) -> None:
    """The child receives no corpus, reference, history, context or gold labels."""
    offline()
    try:
        started = time.perf_counter()
        model = adapter(spec, settings)
        model.synchronize()
        connection.send({"status": "ready", "load_seconds": time.perf_counter() - started,
                         "model": model.metadata})
        while True:
            request = connection.recv()
            if request is None:
                break
            model.synchronize()
            started = time.perf_counter()
            try:
                prediction = model.transcribe(Path(request))
                model.synchronize()
                connection.send({"status": "ok", "prediction": prediction,
                                 "latency_seconds": time.perf_counter() - started})
            except Exception as exc:
                model.synchronize()
                connection.send({"status": "error", "prediction": "",
                                 "latency_seconds": time.perf_counter() - started,
                                 "error": f"{type(exc).__name__}: {str(exc)[:1000]}"})
    except (EOFError, BrokenPipeError):
        pass
    except Exception as exc:
        connection.send({"status": "error", "error": f"{type(exc).__name__}: {str(exc)[:1000]}"})
    finally:
        connection.close()


def receive(connection: Connection, seconds: float) -> dict:
    if not connection.poll(seconds):
        raise TimeoutError(f"Worker exceeded {seconds:g} seconds")
    try:
        return connection.recv()
    except EOFError as exc:
        raise RuntimeError("Model worker exited without a response") from exc


def result_row(utterance: dict, response: dict) -> dict:
    status = response["status"]
    prediction = response.get("prediction", "") if status == "ok" else ""
    if not isinstance(prediction, str):
        raise ValueError("ASR must return a text prediction")
    reference = utterance["reference"]
    return {**utterance, "prediction": prediction,
            "reference_normalized": normalize(reference), "prediction_normalized": normalize(prediction),
            "status": status, "error": response.get("error"),
            "latency_seconds": response.get("latency_seconds"),
            "rtf": (response["latency_seconds"] / utterance["duration_seconds"]
                    if response.get("latency_seconds") is not None else None),
            "scores": score(reference, prediction)}


def run_configuration(spec: dict, settings: dict, utterances: list[dict], base: Path,
                      output: Path, *, worker_target=worker_main) -> tuple[dict, list[dict]]:
    """One persistent process per model; supervisor kills stalled native inference."""
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=worker_target, args=(child, spec, settings))
    rows, ready, failure = [], {}, None
    output.mkdir()
    manifest = {"status": "loading", "spec": spec, "settings": settings,
                "timing": TIMING, "normalization": NORMALIZATION}
    write_json(output / "manifest.json", manifest)
    process_started = False
    try:
        process.start()
        process_started = True
        child.close()
        ready = receive(parent, settings["load_timeout_seconds"])
        if ready["status"] != "ready":
            raise RuntimeError(ready.get("error", "Model loading failed"))
        manifest.update(status="warming_up", initialization=ready)
        write_json(output / "manifest.json", manifest)
        warmup_started = time.perf_counter()
        for _ in range(settings["warmup"]):
            parent.send(str(audio_asset(base, utterances[0]["audio"])))
            response = receive(parent, settings["timeout_seconds"])
            if response["status"] != "ok":
                raise RuntimeError(response.get("error", "Warm-up failed"))
        manifest.update(status="running", warmup_seconds=time.perf_counter() - warmup_started)
        write_json(output / "manifest.json", manifest)
        with (output / "transcripts.jsonl").open("x", encoding="utf-8") as stream:
            for index, utterance in enumerate(utterances):
                print(f"{spec['name']}: {index + 1}/{len(utterances)} {utterance['utterance_id']}", file=sys.stderr, flush=True)
                started = time.perf_counter()
                try:
                    parent.send(str(audio_asset(base, utterance["audio"])))
                    response = receive(parent, settings["timeout_seconds"])
                    if response["status"] not in {"ok", "error"}:
                        raise ValueError("Invalid worker response")
                except TimeoutError as exc:
                    response = {"status": "timeout", "error": str(exc),
                                "latency_seconds": time.perf_counter() - started}
                except (OSError, RuntimeError, ValueError) as exc:
                    response = {"status": "error", "error": str(exc)[:1000],
                                "latency_seconds": time.perf_counter() - started}
                row = result_row(utterance, response)
                rows.append(row)
                stream.write(dumps(row) + "\n")
                stream.flush()
                if response["status"] != "ok":
                    failure = response.get("error", "Inference failed")
                    break
    except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
        failure = f"{type(exc).__name__}: {str(exc)[:1000]}"
    finally:
        if process_started:
            if process.is_alive() and failure is None:
                try:
                    parent.send(None)
                except (OSError, EOFError):
                    pass
                process.join(timeout=5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join(timeout=5)
        parent.close()
        child.close()
        # Preserve full selection even for load failures and hard timeouts.
        with (output / "transcripts.jsonl").open("a", encoding="utf-8") as stream:
            for utterance in utterances[len(rows):]:
                row = result_row(utterance, {"status": "not_run", "error": failure or "Interrupted"})
                rows.append(row)
                stream.write(dumps(row) + "\n")
        summary = summarize(rows)
        completed = summary["succeeded"] == summary["selected"]
        manifest.update(status="completed" if completed else "incomplete", error=failure,
                        summary=summary, initialization=ready)
        write_json(output / "manifest.json", manifest)
    return manifest, rows


def machine_metadata() -> dict:
    metadata = {"hostname": platform.node(), "platform": platform.platform(),
                "processor": platform.processor(), "logical_cpus": os.cpu_count(),
                "python": sys.version, "packages": packages()}
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
                                 "--format=csv,noheader"], capture_output=True, text=True,
                                timeout=5, check=True)
        metadata["nvidia_gpus_name_driver_memory"] = result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        metadata["nvidia_gpus_name_driver_memory"] = None
    if sys.platform == "win32":
        # Capture actual adapter/driver names, without asserting shared RAM is VRAM.
        try:
            query = "Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion | ConvertTo-Json -Compress"
            result = subprocess.run(["powershell", "-NoProfile", "-Command", query],
                                    capture_output=True, text=True, timeout=10, check=True)
            metadata["video_controllers"] = result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            metadata["video_controllers"] = "unavailable"
    return metadata


def git_metadata(repo: Path) -> dict:
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                                  capture_output=True, text=True, check=True, timeout=10).stdout.strip()
        status = subprocess.run(["git", "status", "--porcelain"], cwd=repo,
                                capture_output=True, text=True, check=True, timeout=10).stdout.strip()
        return {"revision": revision, "dirty": bool(status), "status": status}
    except (OSError, subprocess.SubprocessError):
        return {"revision": None, "dirty": None}


def write_comparison(path: Path, summaries: list[dict]) -> None:
    fields = ["configuration", "engine", "device", "dtype", "compute_type", "revision", "status",
              "scope", "split_identity", "selection_identity", "parameter_count", "load_seconds",
              "selected", "succeeded", "failed", "timeouts", "not_run", "coverage",
              "raw_wer", "raw_cer", "normalized_wer", "normalized_cer",
              "mean_latency_seconds", "p95_latency_seconds", "rtf", "measured_utterances"]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summaries)


def benchmark(args, repo: Path) -> int:
    split, selected = load_selection(args.split_manifest, args.data_root, args.scope, args.limit)
    names = list(REGISTRY_NAMES if args.models == ["all"] else args.models)
    specs = [local_spec(name, args.models_dir) for name in names]
    for spec in specs:
        check_budget(spec["provenance"]["parameter_count"], args.planner_parameters)
    require_paired_source(specs)
    settings = {"device": args.device, "dtype": args.dtype or ("float32" if args.device == "cpu" else "float16"),
                "compute_type": args.compute_type or ("int8" if args.device == "cpu" else "float16"),
                "threads": args.threads, "seed": args.seed, "warmup": args.warmup,
                "timeout_seconds": args.timeout_seconds, "load_timeout_seconds": args.load_timeout_seconds}
    args.run_dir.mkdir(parents=True, exist_ok=False)
    selection_identity = identity({"split": split["identity"], "scope": args.scope,
                                   "utterance_ids": [u["utterance_id"] for u in selected]})
    manifest = {"status": "running", "created_utc": datetime.now(timezone.utc).isoformat(),
                "command": sys.argv, "git": git_metadata(repo), "machine": machine_metadata(),
                "split_identity": split["identity"], "selection_identity": selection_identity,
                "split_manifest": str(args.split_manifest.resolve()), "split_seed": split["seed"],
                "source": split["source"], "scope": args.scope, "limit": args.limit,
                "partial_selection": args.limit is not None, "selected": len(selected),
                "settings": settings, "timing": TIMING, "normalization": NORMALIZATION,
                "planner_parameter_count": args.planner_parameters, "configurations": [],
                "caveat": "CPU/quantized engine comparison is not an A30 or full-pipeline latency result"}
    write_json(args.run_dir / "manifest.json", manifest)
    summaries = []
    try:
        for spec in specs:
            outcome, _ = run_configuration(spec, settings, selected, args.data_root / "train",
                                           args.run_dir / spec["name"])
            initialization = outcome.get("initialization", {})
            metadata = initialization.get("model", {})
            count = metadata.get("parameter_count", spec["provenance"]["parameter_count"])
            budget = {"asr_parameters": count, "planner_parameters": args.planner_parameters,
                      "llm_limit": "<5B", "total_limit": "<6B", "planner_context_limit": 16384,
                      "status": "unverified_without_planner" if args.planner_parameters is None else
                                ("count_check_passed" if args.planner_parameters < 5_000_000_000
                                 and count + args.planner_parameters < 6_000_000_000 else "count_check_failed"),
                      "note": "Counts do not verify planner context or final pipeline; quantization preserves parameter count"}
            summary = {"configuration": spec["name"], "engine": spec["engine"],
                       "device": args.device, "dtype": metadata.get("dtype"),
                       "compute_type": metadata.get("compute_type"), "revision": spec["provenance"]["revision"],
                       "parameter_count": count, "parameter_budget": budget,
                       "load_seconds": initialization.get("load_seconds"), "status": outcome["status"],
                       "scope": args.scope, "split_identity": split["identity"],
                       "selection_identity": selection_identity, **outcome["summary"]}
            summaries.append(summary)
            manifest["configurations"] = summaries
            write_comparison(args.run_dir / "comparison.csv", summaries)
            write_json(args.run_dir / "manifest.json", manifest)
    except BaseException as exc:
        manifest.update(status="interrupted", error=f"{type(exc).__name__}: {str(exc)[:1000]}")
        write_json(args.run_dir / "manifest.json", manifest)
        raise
    manifest["status"] = "completed" if all(s["status"] == "completed" for s in summaries) else "incomplete"
    write_json(args.run_dir / "manifest.json", manifest)
    print(dumps({"status": manifest["status"], "comparison": str(args.run_dir / "comparison.csv")}))
    return 0 if manifest["status"] == "completed" else 1


# Kept here to preserve the configured order: small models first, larger ones later.
REGISTRY_NAMES = ("whisper-small-ct2", "whisper-small", "phowhisper-small", "phowhisper-medium", "whisper-turbo", "phowhisper-large")
