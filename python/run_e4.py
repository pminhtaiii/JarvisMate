"""Run audio through the frozen E4 ASR export and current planner/argument policy."""
import argparse
from pathlib import Path

from lifemate.cli import main
from lifemate.runpaths import dated_run_path


def run():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("train", "public_test"), default="public_test")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--id", action="append", default=[])
    selection.add_argument("--all", action="store_true", help="Default when no --id is supplied")
    parser.add_argument("--asr-model", type=Path, default=root / ".agent-work/asr-finetune/suite-01/E4"
                        / "run-20261030-181019-690223-4edc064ec9/exports/best")
    parser.add_argument("--planner-model", type=Path,
                        default=root / ".agent-work/asr-finetune/models/qwen3-4b-instruct-2507")
    parser.add_argument("--sample-timeout-seconds", type=float, default=120)
    options = parser.parse_args()
    data = root / "DATA_JarvisMate/train+public_test"
    prefix = options.split.replace("_", "-") + "-e4-normalized"
    output = dated_run_path(root / ".agent-work/lifemate-runs", prefix)
    args = ["run", "--data-root", str(data), "--runtime-dir", str(data / options.split / "zaic_tools"),
            "--split", options.split, "--input-mode", "audio", "--asr-model", str(options.asr_model),
            "--planner-model", str(options.planner_model), "--device", "cuda", "--model-offload",
            "--selection-filter", "--trace-payloads", "--continue-on-error",
            "--sample-timeout-seconds", str(options.sample_timeout_seconds), "--run-dir", str(output)]
    if options.id:
        for sample_id in options.id:
            args.extend(["--id", sample_id])
    else:
        args.append("--all")
    return main(args)


if __name__ == "__main__":
    raise SystemExit(run())
