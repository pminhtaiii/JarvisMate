"""Separate integration entry point (ADR 011): audio -> native Qwen -> one ToolEnv.

``python -m lifemate run`` stays the legacy comparison path; nothing here changes
its prompt, protocol, defaults or stop-on-first-failure policy.
"""
from __future__ import annotations

import hashlib
from collections import Counter

from .configuration import IntegrationConfig
from .contracts import JSON
from .jsonio import dumps


def asr_identity(config: IntegrationConfig, metadata: JSON | None) -> str:
    """Effective ASR settings that key the per-sample transcript map."""
    if config.asr is None or config.mode != "audio":
        return ""
    value = {"model": str(config.asr.model_path), "device": config.asr.device, "dtype": config.asr.dtype,
             "config_sha256": (metadata or {}).get("config_sha256")}
    return hashlib.sha256(dumps(value).encode("utf-8")).hexdigest()


def build_components(config: IntegrationConfig) -> JSON:
    """Load local models once per healthy worker. Imports model libraries lazily."""
    from .adapters.asr import LocalASR
    from .adapters.qwen_native import NativePlanner
    from .contracts import PipelineError

    asr = None
    if config.mode == "audio":
        asr = LocalASR(config.asr.model_path, config.asr.device, config.limits, config.seed,
                       cpu_offload=config.asr.offload, dtype=config.asr.dtype)
    planner = NativePlanner(config.planner, config.limits, config.seed)
    planner_count = planner.metadata["parameter_count"]
    total = planner_count + (asr.metadata["parameter_count"] if asr else 0)
    if planner_count >= 5_000_000_000 or total >= 6_000_000_000:
        raise PipelineError("MODEL_UNAVAILABLE", "Deployed model parameter budget exceeded", "model_load")
    return {"asr": asr, "planner": planner, "asr_identity": asr_identity(config, asr.metadata if asr else None),
            "metadata": {"asr": asr.metadata if asr else None, "planner": planner.metadata,
                         "total_parameters": total}}


# --- CLI and batch coordination ----------------------------------------------

def host_provenance() -> JSON:
    """Supervisor-side host evidence; GPU details come from the worker's ready message."""
    import os
    import platform
    import shutil
    import subprocess

    info: JSON = {"platform": platform.platform(), "python": platform.python_version(),
                  "cpu_count": os.cpu_count(), "container": os.path.exists("/.dockerenv"),
                  "offline_env": {k: os.environ.get(k) for k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")},
                  "visible_devices": os.environ.get("NVIDIA_VISIBLE_DEVICES") or os.environ.get("CUDA_VISIBLE_DEVICES")}
    try:
        info["memory_bytes"] = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, ValueError, OSError):
        info["memory_bytes"] = None
    if shutil.which("nvidia-smi"):
        try:
            result = subprocess.run(["nvidia-smi", "--query-gpu=index,uuid,name,driver_version,memory.total",
                                     "--format=csv,noheader"], capture_output=True, text=True, timeout=10)
            info["nvidia_smi"] = result.stdout.strip().splitlines()[:16]
        except (OSError, subprocess.SubprocessError):
            info["nvidia_smi"] = None
    return info


def parser():
    import argparse
    from pathlib import Path

    from .contracts import PipelineError

    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise PipelineError("INPUT_INVALID", "Invalid command arguments; consult --help", "arguments")

    root = Parser(prog="python -m lifemate.integration",
                  description="Offline audio -> native Qwen -> ToolEnv integration (ADR 011)")
    root.add_argument("--config", required=True, type=Path)
    root.add_argument("--check-config", action="store_true",
                      help="Validate configuration, snapshots and data without models, tools or downloads")
    root.add_argument("--resume", action="store_true",
                      help="Continue the run in output.root; reserved-but-unaccepted IDs stay failed")
    root.add_argument("--asr-model", type=Path)
    root.add_argument("--planner-model", type=Path)
    root.add_argument("--device", help="Override asr.device and planner.device, e.g. cuda:0")
    return root


def summarize(journal, selected: list[str]) -> JSON:
    accepted, failed = journal.accepted(), journal.failed()
    partial_reasons = Counter(r["metrics"].get("worker", {}).get("stop_reason") or "unknown"
                              for r in accepted.values() if r["status"] == "partial")
    attempts = sorted(r["metrics"]["attempt_seconds"] for r in accepted.values()
                      if isinstance(r["metrics"].get("attempt_seconds"), (int, float)))

    def percentile(q):
        return attempts[min(len(attempts) - 1, int(q * len(attempts)))] if attempts else None

    return {"selected": len(selected),
            "completed": sum(r["status"] == "completed" for r in accepted.values()),
            "needs_info": sum(r["status"] == "needs_info" for r in accepted.values()),
            "partial": sum(r["status"] == "partial" for r in accepted.values()),
            "partial_stop_reasons": dict(sorted(partial_reasons.items())),
            "accepted": len(accepted),
            "coverage_note": "Accepted coverage includes partial execution and does not establish correctness",
            "timeout": sum(r["status"] == "timeout" for r in failed.values()),
            "failed": sum(r["status"] == "failed" for r in failed.values()),
            "not_attempted": [i for i in selected if i not in journal.attempted()],
            "failures": {i: r["error"].get("code") for i, r in failed.items()},
            "accepted_attempt_seconds": {"p50": percentile(0.5), "p95": percentile(0.95),
                                         "max": attempts[-1] if attempts else None}}


def main(argv=None, *, worker_command=None, worker_env=None, fault=None, clock=None) -> int:
    import sys
    import time

    from .artifacts import RunJournal, atomic_json, publish_predictions, sanitize, utc_now
    from .configuration import load_config, preflight
    from .contracts import PipelineError
    from .supervisor import Supervisor

    clock = clock or time.monotonic
    started = clock()
    journal, manifest = None, None

    def emit(value):
        print(dumps(value), flush=True)

    try:
        args = parser().parse_args(argv)
        overrides = {"asr_model": args.asr_model, "planner_model": args.planner_model, "device": args.device}
        config = load_config(args.config, overrides)
        checked = clock()
        pre = preflight(config)  # Fails before any worker, model or ToolEnv exists.
        preflight_seconds = clock() - checked
        selected = list(pre.dataset.metadata["selected_ids"])
        if args.check_config:
            emit({"status": "validated", "effective_config": config.record(), "identity": pre.identity,
                  "run_sha256": pre.run_sha256, "note": "No model was loaded; memory fit is unverified"})
            return 0
        header = {"run_sha256": pre.run_sha256, "config_sha256": config.fingerprint(), "selected_ids": selected}
        journal = (RunJournal.resume if args.resume else RunJournal.create)(config.output_root, header)
        if not args.resume:
            atomic_json(journal.root / "effective-config.json", config.record())
        manifest_path = journal.root / "manifest.json"
        manifest = {"schema_version": 1, "entry_point": "lifemate.integration", "status": "running",
                    "started_at": utc_now(), "argv": list(sys.argv[1:] if argv is None else argv),
                    "effective_config": config.record(), "identity": pre.identity, "run_sha256": pre.run_sha256,
                    "host": host_provenance(), "resumed": args.resume,
                    "timings": {"preflight_seconds": preflight_seconds}}
        atomic_json(manifest_path, manifest)
        supervisor = Supervisor(journal, config.fingerprint(), config.timeout_seconds,
                                config.startup_timeout_seconds, config.recovery_attempts,
                                command=worker_command, env=worker_env, clock=clock, fault=fault)
        if args.resume:
            manifest["resume"] = {"prior_workers": supervisor.confirm_prior_workers(),
                                  "uncertain_ids": journal.mark_uncertain(),
                                  "quarantined": journal.quarantine_unaccepted()}
        stop = None
        try:
            for position, sample_id in enumerate(selected, 1):
                if sample_id in journal.attempted():
                    continue  # Accepted, failed and uncertain samples are never redispatched.
                supervisor.ensure_worker()
                result = supervisor.run_sample(sample_id)
                seconds = result.metrics.get("attempt_seconds") or 0.0
                print(f"[{position}/{len(selected)}] {sample_id} {result.status} attempt={seconds:.2f}s",
                      file=sys.stderr, flush=True)
        except PipelineError as exc:
            stop = exc.record()
        finally:
            try:
                supervisor.shutdown()
            except PipelineError as exc:
                stop = stop or exc.record()
        packaging = clock()
        publication = publish_predictions(journal, selected)
        report = summarize(journal, selected)
        manifest["timings"].update(
            startup=[s for s in supervisor.startups if s["reason"] == "startup"],
            recovery=[s for s in supervisor.startups if s["reason"] == "recovery"],
            packaging_seconds=clock() - packaging, total_wall_seconds=clock() - started)
        complete = publication["complete"] and stop is None
        manifest.update(status="completed" if complete else "incomplete", ended_at=utc_now(), report=report,
                        publication=publication, stop=sanitize(stop) if stop else None,
                        submission_ready=False)  # Organizer accounting gates remain open (T032).
        atomic_json(manifest_path, manifest)
        emit({"status": manifest["status"], "manifest": str(manifest_path), "predictions": publication["path"],
              "report": report, "stop": stop})
        return 0 if complete else 1
    except PipelineError as exc:
        record = exc.record()
        if manifest is not None and journal is not None:
            try:
                manifest.update(status="failed", ended_at=utc_now(), stop=sanitize(record))
                atomic_json(journal.root / "manifest.json", manifest)
            except PipelineError:
                pass  # The journal remains the durable record.
        emit({"status": "failed", "error": record})
        return 2 if journal is None else 1
    finally:
        if journal is not None:
            journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
