"""Stable hashes, atomic writes, immutable sealing and unique artifact directories (LL004).

Never enumerates or hashes ``*_environment``/``*_enviroment`` content; every hashed or
written path passes the visible-path guard. Sealed directories are append-never.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..jsonio import digest, dumps, loads, visible_path

SEAL_NAME = "SEAL.json"
SEALED_MARKER = "SEALED"  # Marks subdirectories whose files a parent SEAL.json covers.
SEAL_SCHEMA = "lifemate-llm-seal-v1"


class StorageError(OSError):
    """Artifact persistence or integrity failure; callers must not finalize."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def value_hash(value: Any) -> str:
    return text_hash(dumps(value))


def file_hash(path: Path) -> str:
    return digest(path)  # Includes the visible-path guard.


def _fsync_write(path: Path, data: bytes, *, exclusive: bool) -> None:
    visible_path(path)
    if exclusive and path.exists():
        raise StorageError(f"Refusing to overwrite durable artifact {path.name}")
    if _sealed(path.parent):
        raise StorageError("Sealed directories are immutable")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            # Both fail atomically if the target appeared meanwhile (Windows rename never replaces).
            os.rename(temporary, path) if os.name == "nt" else os.link(temporary, path)
        else:
            os.replace(temporary, path)
    except FileExistsError as exc:
        raise StorageError(f"Refusing to overwrite durable artifact {path.name}") from exc
    except OSError as exc:
        raise StorageError(f"Cannot persist {path.name}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, value: Any, *, exclusive: bool = True) -> str:
    data = (dumps(value) + "\n").encode("utf-8")
    _fsync_write(path, data, exclusive=exclusive)
    return hashlib.sha256(data).hexdigest()


def write_jsonl(path: Path, rows: Iterable[Any], *, exclusive: bool = True) -> str:
    data = "".join(dumps(row) + "\n" for row in rows).encode("utf-8")
    _fsync_write(path, data, exclusive=exclusive)
    return hashlib.sha256(data).hexdigest()


def write_text(path: Path, text: str, *, exclusive: bool = True) -> str:
    data = text.encode("utf-8")
    _fsync_write(path, data, exclusive=exclusive)
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> Any:
    visible_path(path)
    try:
        return loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise StorageError(f"Unreadable artifact {path.name}") from exc


def read_jsonl(path: Path) -> list[Any]:
    visible_path(path)
    try:
        return [loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise StorageError(f"Unreadable artifact {path.name}") from exc


def _sealed(directory: Path) -> bool:
    return (directory / SEAL_NAME).exists() or (directory / SEALED_MARKER).exists()


def new_directory(parent: Path, prefix: str) -> Path:
    """A fresh unique directory; identity of its content is recorded separately."""
    visible_path(parent)
    parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for _ in range(16):
        candidate = parent / f"{prefix}-{stamp}-{uuid.uuid4().hex[:8]}"
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise StorageError("Cannot reserve a unique artifact directory")


def create_fresh(directory: Path) -> Path:
    """Create an explicitly named directory that must not already exist."""
    visible_path(directory)
    try:
        directory.parent.mkdir(parents=True, exist_ok=True)
        directory.mkdir()
    except FileExistsError as exc:
        raise StorageError("Artifact directory already exists; choose a new one") from exc
    return directory


def seal(directory: Path, files: Iterable[str]) -> dict:
    """Record SHA-256/size of each named file, then commit SEAL.json last."""
    entries = []
    for relative in sorted(files):
        path = directory / relative
        if not path.is_file() or path.name == SEAL_NAME:
            raise StorageError(f"Cannot seal missing artifact {relative}")
        entries.append({"path": relative, "sha256": file_hash(path), "bytes": path.stat().st_size})
    record = {"schema": SEAL_SCHEMA, "sealed_at": now(), "files": entries}
    record["identity"] = value_hash(entries)
    for subdirectory in sorted({Path(e["path"]).parent for e in entries} - {Path(".")}):
        write_json(directory / subdirectory / SEALED_MARKER, {"sealed_by": SEAL_NAME, "identity": record["identity"]})
    write_json(directory / SEAL_NAME, record)
    return record


def verify_seal(directory: Path) -> dict:
    record = read_json(directory / SEAL_NAME)
    if record.get("schema") != SEAL_SCHEMA or record.get("identity") != value_hash(record.get("files")):
        raise StorageError("Seal record is invalid")
    for entry in record["files"]:
        path = directory / entry["path"]
        if not path.is_file() or path.stat().st_size != entry["bytes"] or file_hash(path) != entry["sha256"]:
            raise StorageError(f"Sealed artifact changed: {entry['path']}")
    return record



def source_provenance(repository: Path) -> dict:
    """Revision plus a hash of any uncommitted tracked/untracked source changes."""
    def git(*args: str) -> bytes:
        return subprocess.run(["git", *args], cwd=repository, check=True, capture_output=True, timeout=30,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0).stdout

    try:
        revision = git("rev-parse", "HEAD").decode().strip()
        status = git("status", "--porcelain", "--untracked-files=all")
        patch = git("diff", "HEAD", "--binary")
    except (OSError, subprocess.SubprocessError):
        return {"revision": None, "dirty": None, "dirty_patch_sha256": None, "unavailable": True}
    dirty = bool(status.strip())
    return {"revision": revision, "dirty": dirty,
            "dirty_patch_sha256": hashlib.sha256(patch + b"\0" + status).hexdigest() if dirty else None}
