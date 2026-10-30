"""Run from the repository root: python -m asr.pretrained --help."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys

from lifemate.contracts import PipelineError
from lifemate.jsonio import dumps, visible_path

from .data import make_split
from .models import REGISTRY, offline

REPO = Path(__file__).resolve().parents[2]
WORK = REPO / ".agent-work" / "asr-benchmark"


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Must be >=1")
    return number


def positive_seconds(value: str) -> float:
    number = float(value)
    if not 0 < number < float("inf"):
        raise argparse.ArgumentTypeError("Must be finite and >0")
    return number


def ignored_path(path: Path) -> Path:
    path = path.resolve()
    visible_path(path)
    if not path.is_relative_to((REPO / ".agent-work").resolve()):
        raise ValueError("Store derived data, artifacts and weights under the ignored .agent-work/ directory")
    return path


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Pretrained Vietnamese ASR benchmark; CPU by default, offline inference")
    commands = command.add_subparsers(dest="command", required=True)
    split = commands.add_parser("split", help="Inspect Train WAVs and freeze leakage-aware seed-42 split; no models")
    split.add_argument("--data-root", type=Path, default=REPO / "../train+public_test/train+public_test")
    split.add_argument("--output", type=Path, default=WORK / "split42.json")
    prepare = commands.add_parser("prepare", help="EXPLICIT ONLINE download and local CT2 conversion; no benchmark")
    prepare.add_argument("--models", choices=[*REGISTRY, "all"], nargs="+", default=["all"])
    prepare.add_argument("--models-dir", type=Path, default=WORK / "models")
    prepare.add_argument("--revision", default="main", help="Resolve to immutable SHA; use per-model SHA for reproduction")
    run = commands.add_parser("run", help="Benchmark the frozen validation selection; local files only")
    run.add_argument("--data-root", type=Path, default=REPO / "../train+public_test/train+public_test")
    run.add_argument("--split-manifest", type=Path, default=WORK / "split42.json")
    run.add_argument("--models-dir", type=Path, default=WORK / "models")
    run.add_argument("--models", choices=[*REGISTRY, "all"], nargs="+", default=["whisper-small-ct2"])
    run.add_argument("--run-dir", type=Path, default=WORK / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    run.add_argument("--scope", choices=["current", "with-history"], default="current")
    run.add_argument("--limit", type=positive_int, help="First N validation utterances; marked as a partial selection")
    run.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    run.add_argument("--dtype", choices=["float32", "float16"], help="Transformers dtype; default CPU fp32 / CUDA fp16")
    run.add_argument("--compute-type", choices=["int8", "float32", "float16", "int8_float16"],
                     help="CT2 compute type; default CPU int8 / CUDA fp16")
    run.add_argument("--threads", type=positive_int, default=8)
    run.add_argument("--seed", type=int, default=42, help="Inference seed; split seed remains frozen at 42")
    run.add_argument("--warmup", type=positive_int, default=1)
    run.add_argument("--timeout-seconds", type=positive_seconds, default=600)
    run.add_argument("--load-timeout-seconds", type=positive_seconds, default=600)
    run.add_argument("--planner-parameters", type=positive_int, help="Optional actual planner count for <5B / combined <6B check")
    return command


def main(argv: list[str] | None = None) -> int:
    command = parser()
    args = command.parse_args(argv)
    try:
        if hasattr(args, "models"):
            if "all" in args.models and args.models != ["all"]:
                command.error("Use --models all by itself")
            if len(args.models) != len(set(args.models)):
                command.error("Duplicate configurations are not allowed")
            args.models_dir = ignored_path(args.models_dir)
        if args.command == "split":
            output = ignored_path(args.output)
            if output.exists():
                raise ValueError("Split manifest already exists; reuse it or choose a new --output")
            manifest = make_split(args.data_root.resolve())
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as stream:
                stream.write(dumps(manifest) + "\n")
            print(dumps({"manifest": str(output), "identity": manifest["identity"],
                         "source": manifest["source"], "groups": manifest["groups"],
                         "largest_group": manifest["largest_group"],
                         "actual_validation_ratio": manifest["actual_validation_ratio"]}))
            return 0
        if args.command == "prepare":
            from .prepare import prepare_models

            names = list(REGISTRY) if args.models == ["all"] else args.models
            if args.revision != "main" and len(set(REGISTRY[n][0] for n in names)) != 1:
                command.error("Use an immutable --revision separately for each source model")
            prepare_models(names, args.models_dir, args.revision)
            print(dumps({"status": "prepared", "models": names, "models_dir": str(args.models_dir)}))
            return 0
        if args.device == "cpu" and (args.dtype == "float16" or args.compute_type in {"float16", "int8_float16"}):
            command.error("CPU: use --dtype float32 and --compute-type int8 or float32")
        if not 0 <= args.seed <= 2**32 - 1:
            command.error("--seed must be in [0, 2**32-1]")
        args.run_dir = ignored_path(args.run_dir)
        if args.run_dir.exists():
            raise ValueError("Run directory already exists; choose a fresh --run-dir (no overwrite/resume)")
        offline()
        from .runner import benchmark

        return benchmark(args, REPO)
    except (PipelineError, OSError, ValueError, RuntimeError, ImportError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted; check the run manifest and retained partial artifacts", file=sys.stderr)
        return 130
