"""Atomic experiment artifacts and source/environment fingerprints."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import os
from pathlib import Path
import platform
import subprocess
import uuid

from lifemate.jsonio import digest, dumps, loads, visible_path, contained

REPO = Path(__file__).resolve().parents[4]
EXPERIMENTS = ("E0", "E1", "E2", "E3", "E4")
TERMINAL = {"completed", "failed", "failed_oom", "unsupported", "interrupted",
            "skipped_not_needed", "skipped_dependency", "skipped_resource", "export_unavailable"}


def identity(value) -> str:
    return hashlib.sha256(dumps(value).encode("utf-8")).hexdigest()


def read(path: Path):
    visible_path(path)
    return loads(path.read_text(encoding="utf-8"))


def write(path: Path, value) -> None:
    visible_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(dumps(value) + "\n", encoding="utf-8")
    temp.replace(path)


def append(path: Path, value) -> None:
    visible_path(path)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(dumps(value) + "\n")
        stream.flush()


def rows(path: Path) -> list[dict]:
    visible_path(path)
    return [loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write_rows(path: Path, values: list[dict]) -> None:
    visible_path(path)
    path.write_text("".join(dumps(row) + "\n" for row in values), encoding="utf-8")


def ignored(path: Path) -> Path:
    path = path.resolve()
    visible_path(path)
    if not path.is_relative_to((REPO / ".agent-work").resolve()):
        raise ValueError("Artifacts must be under the repository's ignored .agent-work/")
    return path


def tree_hashes(path: Path) -> dict:
    return {p.relative_to(path).as_posix(): digest(p) for p in sorted(path.rglob("*"))
            if p.is_file() and ".cache" not in p.relative_to(path).parts
            and p.name not in {"files.json", "files.json.tmp"}}


def seal(path: Path) -> None:
    write(path / "files.json", tree_hashes(path))


def verify(path: Path) -> None:
    hashes = read(path / "files.json")
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("Missing artifact file hashes")
    for relative, sha in hashes.items():
        if digest(contained(path, relative)) != sha:
            raise ValueError(f"Artifact checksum mismatch: {relative}")


def environment() -> dict:
    versions = {}
    for name in ("torch", "transformers", "peft", "accelerate", "bitsandbytes", "numpy", "safetensors"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return {"python": platform.python_version(), "platform": platform.platform(), "packages": versions}


def code_identity() -> dict:
    files = [*Path(__file__).parent.glob("*.py"), * (REPO / "asr/pretrained").glob("*.py"),
             REPO / "python/src/lifemate/jsonio.py", REPO / "python/src/lifemate/model_budget.py",
             REPO / "python/src/lifemate/dataset.py"]
    hashes = {str(p.relative_to(REPO)): digest(p) for p in sorted(files)}
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, text=True,
                                  capture_output=True, check=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        revision = None
    return {"hash": identity(hashes), "files": hashes, "revision": revision}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_directory(suite: Path, experiment: str, kind: str) -> Path:
    if experiment not in EXPERIMENTS or kind not in {"probe", "run", "skip"}:
        raise ValueError("Invalid experiment/run kind")
    key = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f") + "-" + uuid.uuid4().hex[:10]
    directory = suite / experiment / f"{kind}-{key}"
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def records(suite: Path, experiment: str, kind: str | None = None) -> list[tuple[Path, dict]]:
    result = []
    for path in sorted((suite / experiment).glob("*/manifest.json")):
        value = read(path)
        if kind is None or value["kind"] == kind:
            result.append((path.parent, value))
    result.sort(key=lambda r: (r[1].get("created", ""), r[0].name.split("-", 1)[-1]))
    return result


def latest(suite: Path, experiment: str, kind: str = "run") -> tuple[Path, dict] | None:
    candidates = records(suite, experiment, kind)
    return candidates[-1] if candidates else None


def outcome(suite: Path, experiment: str) -> tuple[Path, dict] | None:
    candidates = [r for r in records(suite, experiment)
                  if r[1]["kind"] != "probe" or r[1]["status"] != "passed"]
    return candidates[-1] if candidates else None


@contextmanager
def suite_lock(suite: Path):
    """One experiment/probe at a time; crashed locks require explicit recovery."""
    path = suite / "active.lock"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(descriptor, dumps({"pid": os.getpid(), "host": platform.node(), "started": now()}).encode())
        os.close(descriptor)
        descriptor = None
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        path.unlink(missing_ok=True)
