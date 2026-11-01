"""Run all Train transcripts, optionally resuming an explicitly selected checkpoint."""
import argparse
from pathlib import Path

from lifemate.cli import main
from lifemate.runpaths import dated_run_path


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume-from", type=Path, help="Stopped source run directory")
    parser.add_argument("--selection-filter", action="store_true", help="Enable development task-completion filters")
    parser.add_argument("--allow-mixed-resume", action="store_true",
                        help="Keep development rows from a different/unknown code or model version")
    options = parser.parse_args()
    if options.allow_mixed_resume and options.resume_from is None:
        parser.error("--allow-mixed-resume requires --resume-from")
    root = Path(__file__).resolve().parents[1]
    data = root / "DATA_JarvisMate" / "train+public_test"
    output = dated_run_path(root / ".agent-work/lifemate-runs", "train-all")
    planner = root / ".agent-work/asr-finetune/models/qwen3-4b-instruct-2507"
    if not planner.is_dir():
        planner = root / ".agent-work/models/qwen3-4b-instruct-2507"
    args = ["run", "--data-root", str(data), "--runtime-dir", str(data / "train" / "zaic_tools"),
            "--split", "train", "--input-mode", "transcript", "--all",
            "--planner-model", str(planner),
            "--device", "cuda", "--trace-payloads", "--sample-timeout-seconds", "120",
            "--continue-on-error", "--run-dir", str(output)]
    if options.resume_from is not None:
        args += ["--resume-from", str(options.resume_from.resolve())]
    if options.allow_mixed_resume:
        args.append("--allow-mixed-resume")
    if options.selection_filter:
        args.append("--selection-filter")
    return main(args)


if __name__ == "__main__":
    raise SystemExit(run())
