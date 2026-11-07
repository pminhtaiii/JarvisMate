"""``python -m lifemate.sft`` stages. Exit zero means that stage completed.

Failures print one bounded JSON record to stderr and exit nonzero. Model libraries load
lazily inside the stages that need them.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..contracts import PipelineError
from . import load_config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m lifemate.sft", description="Native planner QLoRA baseline")
    stages = parser.add_subparsers(dest="stage", required=True)

    def stage(name: str, help_text: str) -> argparse.ArgumentParser:
        command = stages.add_parser(name, help=help_text)
        command.add_argument("--config", type=Path, required=True)
        for option in ("train-jsonl", "train-catalog", "validation-jsonl", "validation-catalog", "base-path", "device"):
            command.add_argument(f"--{option}")
        command.add_argument("--output", dest="experiment_dir")
        command.add_argument("--microbatch", type=int)
        command.add_argument("--accumulation", type=int)
        return command

    stage("preflight", "Validate configuration, data roles, overlap and snapshot metadata; load nothing")
    stage("prepare", "Export audited native next-action rows")
    train = stage("train", "Run the fixed recipe on one GPU")
    train.add_argument("--resume", type=Path, help="Explicit committed checkpoint directory to resume")
    train.add_argument("--smoke", action="store_true", help="Isolated short feasibility run under <experiment>/smoke")
    export = stage("export", "Merge the selected adapter into a standalone FP16 snapshot")
    export.add_argument("--selection", type=Path, required=True)
    diagnose = stage("diagnose", "Compare the selected adapter with its merged export on fixed validation prompts "
                               "(validation_mode separate only)")
    diagnose.add_argument("--selection", type=Path, required=True)
    return parser


def _run(arguments: argparse.Namespace) -> dict:
    overrides = {key: getattr(arguments, key) for key in (
        "train_jsonl", "train_catalog", "validation_jsonl", "validation_catalog", "base_path", "device",
        "microbatch", "accumulation", "experiment_dir")}
    config = load_config(arguments.config, overrides)
    if arguments.stage == "preflight":
        from .data import preflight
        return preflight(config)
    if arguments.stage == "prepare":
        from .data import prepare
        return prepare(config)
    if arguments.stage == "train":
        from .training import run_training
        return run_training(config, resume=arguments.resume, smoke=arguments.smoke)
    if arguments.stage == "export":
        from .export import run_export
        return run_export(config, arguments.selection)
    from .export import run_diagnostics
    return run_diagnostics(config, arguments.selection)


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        print(json.dumps(_run(arguments), ensure_ascii=False, sort_keys=True))
        return 0
    except PipelineError as exc:
        print(json.dumps(exc.record(), ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(json.dumps({"code": "INTERRUPTED", "stage": arguments.stage, "message": "Interrupted"}), file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
