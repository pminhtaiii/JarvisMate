"""Make the checked-out repository's shared engine available to standalone scripts."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "python/src"))

from lifemate.asr_training.cli import main


def entry(command: str, experiment: str | None = None):
    args = sys.argv[1:]
    if experiment and any(a.startswith("--experiment") for a in args):
        raise SystemExit("This script runs its named experiment only; use the shared CLI to choose another")
    return main([command, *(["--experiment", experiment] if experiment else []), *args])
