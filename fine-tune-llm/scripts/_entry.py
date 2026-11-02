"""Portable source entry; forwards one phase to the shared validated CLI."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python/src"))


def run(experiment):
    from lifemate.llm_training.cli import main
    from lifemate.llm_training.config import load_experiment
    args = sys.argv[1:]
    if not args or args[0] not in {"train", "evaluate", "probe", "latency-pilot", "export", "verify-export"}:
        print("Select one phase: train/evaluate/probe/latency-pilot/export/verify-export", file=sys.stderr)
        return 2
    if "--experiment" in args:
        print("The wrapper already selects its experiment", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parents[2]
    treatment = load_experiment(root / "fine-tune-llm/configs" / (experiment.lower()+".json"), experiment)
    if args[0] in {"train", "probe"} and treatment["training_settings"] and "--settings" not in args:
        args += ["--settings", str(root / treatment["training_settings"])]
    return main([args[0], "--experiment", experiment, *args[1:]])
