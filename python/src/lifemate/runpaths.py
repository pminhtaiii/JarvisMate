"""Human-readable prediction run directories, using Vietnam execution time."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

VIETNAM = timezone(timedelta(hours=7))


def dated_run_path(parent: Path, prefix: str, *, now: datetime | None = None) -> Path:
    """Choose an unused path without creating it; RunStore reserves it atomically.

    A same-second collision adds microseconds, never a random suffix or overwrite.
    Explicit CLI --run-dir values remain authoritative.
    """
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", prefix):
        raise ValueError("Invalid run directory prefix")
    started = now if now is not None else datetime.now(VIETNAM)
    if started.utcoffset() is None:
        raise ValueError("Run timestamp requires timezone")
    started = started.astimezone(VIETNAM)
    candidate = Path(parent) / f"{prefix}-{started:%Y%m%d-%H%M%S}"
    if not candidate.exists():
        return candidate
    while True:
        candidate = Path(parent) / f"{prefix}-{started:%Y%m%d-%H%M%S-%f}"
        if not candidate.exists():
            return candidate
        started += timedelta(microseconds=1)
