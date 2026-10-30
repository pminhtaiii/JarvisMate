"""Manual CLI: every run/preflight invocation addresses exactly ONE experiment."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform

from lifemate.jsonio import dumps
from lifemate.model_budget import check_budget
from .storage import REPO, EXPERIMENTS, ignored, read, write, rows, now, suite_lock, run_directory, outcome

CONFIGS = REPO / "asr/fine-tuned/configs"


def parser():
    root = argparse.ArgumentParser(description="Manual sequential PhoWhisper-large E0-E4. No automatic all-experiments mode.")
    commands = root.add_subparsers(dest="command", required=True)
    prepare_model = commands.add_parser("prepare-model", help="Explicit online download of the immutable local base")
    prepare_model.add_argument("--models-dir", type=Path, default=REPO / ".agent-work/asr-finetune/models")
    prepare_model.add_argument("--revision", default="main")
    prepare = commands.add_parser("prepare", help="Verify existing split/audio and create immutable suite; no training")
    prepare.add_argument("--suite-dir", type=Path, required=True)
    prepare.add_argument("--data-root", type=Path, default=REPO / "../train+public_test/train+public_test")
    prepare.add_argument("--split-manifest", type=Path, default=REPO / ".agent-work/asr-benchmark/split42.json")
    prepare.add_argument("--model", type=Path, default=REPO / ".agent-work/asr-finetune/models/phowhisper-large")
    prepare.add_argument("--slot-annotations", type=Path)
    prepare.add_argument("--slot-rules", type=Path)
    for name in ("preflight", "run"):
        command = commands.add_parser(name)
        command.add_argument("--suite-dir", type=Path, required=True)
        command.add_argument("--experiment", choices=EXPERIMENTS, required=True)
        command.add_argument("--config", type=Path)
        command.add_argument("--noise-manifest", type=Path)
        if name == "run":
            command.add_argument("--resume-from", type=Path)
    for name in ("status", "compare"):
        command = commands.add_parser(name, help="Read stored artifacts only; no model loading/training")
        command.add_argument("--suite-dir", type=Path, required=True)
    skip = commands.add_parser("skip")
    skip.add_argument("--suite-dir", type=Path, required=True)
    skip.add_argument("--experiment", choices=EXPERIMENTS, required=True)
    skip.add_argument("--status", choices=["skipped_not_needed", "skipped_dependency", "skipped_resource"], default="skipped_not_needed")
    skip.add_argument("--reason", required=True)
    failed = commands.add_parser("fail", help="Explicitly record an abandoned run as failed; no process killing")
    failed.add_argument("--suite-dir", type=Path, required=True)
    failed.add_argument("--run-dir", type=Path, required=True)
    failed.add_argument("--reason", required=True)
    unlock = commands.add_parser("unlock", help="Recover a lock only after its local process is no longer alive")
    unlock.add_argument("--suite-dir", type=Path, required=True)
    unlock.add_argument("--expected-pid", type=int, required=True)
    export = commands.add_parser("export")
    export.add_argument("--suite-dir", type=Path, required=True)
    export.add_argument("--run-dir", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--planner-parameters", type=int)
    export.add_argument("--extra-parameters", type=int, default=0)
    export.add_argument("--context-tokens", type=int, default=16384)
    return root


def process_alive(pid: int) -> bool:
    if pid <= 0:
        raise ValueError("Invalid PID")
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "prepare-model":
            from asr.pretrained.prepare import prepare_models
            prepare_models(["phowhisper-large"], ignored(args.models_dir), args.revision)
            result = {"status": "prepared", "model": str(args.models_dir / "phowhisper-large")}
        else:
            suite = ignored(args.suite_dir)
            if args.command == "prepare":
                from .data import prepare_suite
                result = prepare_suite(suite, args.data_root, args.split_manifest, args.model,
                                       args.slot_annotations, args.slot_rules)
            elif args.command in {"preflight", "run"}:
                config = args.config or CONFIGS / (args.experiment.lower() + ".json")
                if args.command == "preflight":
                    from .orchestration import preflight
                    result = preflight(suite, config, args.experiment, args.noise_manifest)
                else:
                    from .execution import run
                    result = run(suite, config, args.experiment, noise_manifest=args.noise_manifest,
                                 resume_from=args.resume_from)
                print(dumps({"status": result["status"], "path": result["path"], "error": result.get("error")}))
                return 0 if result["status"] in {"completed", "passed"} else (130 if result["status"] == "interrupted" else 3 if result["status"] == "unsupported" else 1)
            elif args.command in {"status", "compare"}:
                read(suite / "suite.json")
                from .reporting import status, compare
                result = {"experiments": status(suite)} if args.command == "status" else compare(suite)
            elif args.command == "skip":
                read(suite / "suite.json")
                if not args.reason.strip():
                    raise ValueError("Skip reason must be nonempty")
                if args.experiment == "E0":
                    raise ValueError("E0 cannot be skipped as a valid baseline")
                with suite_lock(suite):
                    path = run_directory(suite, args.experiment, "skip")
                    result = {"schema": "asr-ft-run-v1", "kind": "skip", "experiment": args.experiment,
                              "status": args.status, "error": args.reason, "created": now(), "finished": now()}
                    write(path / "manifest.json", result)
            elif args.command == "fail":
                from .execution import owned
                with suite_lock(suite):
                    path = owned(suite, args.run_dir)
                    result = read(path / "manifest.json")
                    if result["status"] not in {"running", "interrupted"} or not args.reason.strip():
                        raise ValueError("Only abandoned running/interrupted runs can be explicitly failed")
                    result.update(status="failed", error=args.reason, finished=now())
                    write(path / "manifest.json", result)
            elif args.command == "unlock":
                lock = read(suite / "active.lock")
                if (lock["pid"] != args.expected_pid or lock.get("host") != platform.node()
                        or process_alive(args.expected_pid)):
                    raise ValueError("Lock owner differs or is still alive; refusing to unlock")
                (suite / "active.lock").unlink()
                result = {"status": "unlocked", "previous_pid": args.expected_pid}
            else:
                from .data import load_suite
                from .execution import owned
                from .exporting import export
                with suite_lock(suite):
                    data, _, _ = load_suite(suite)
                    path = owned(suite, args.run_dir)
                    manifest = read(path / "manifest.json")
                    if not manifest.get("best_checkpoint"):
                        raise ValueError("Run has no selected training checkpoint")
                    config = read(path / "resolved-config.json")
                    check_budget(data["model"]["provenance"]["parameter_count"], args.planner_parameters,
                                 extra=args.extra_parameters, context_tokens=args.context_tokens)
                    evaluated = rows(owned(suite, Path(manifest["best_evaluation"])) / "transcripts.jsonl")
                    result = export(data, config, manifest["hardware"],
                                    owned(suite, Path(manifest["best_checkpoint"])), ignored(args.output), evaluated)
                    result["budget"] = check_budget(result["parameters"], args.planner_parameters,
                                                     extra=args.extra_parameters, context_tokens=args.context_tokens)
                    from .storage import seal
                    write(Path(result["path"]) / "deployment-budget.json", result["budget"])
                    seal(Path(result["path"]))
        print(dumps(result))
        return 0
    except KeyboardInterrupt:
        print("Interrupted; inspect status and resume only from an explicitly chosen durable checkpoint")
        return 130
    except Exception as exc:
        import sys
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
