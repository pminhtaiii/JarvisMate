"""Durable predictions, bounded opt-in traces, and explicit run publication."""
from __future__ import annotations

import hashlib
import os
import platform
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .contracts import JSON, PipelineError, RunConfig
from .jsonio import dumps, loads, safe_id
from .prompting import PROMPT_HASH, PROMPT_VERSION

SCHEMA_VERSION = 1
SECRET_KEY = re.compile(r"password|secret|api[_-]?key|authorization|access[_-]?token|refresh[_-]?token|^token$", re.I)
BEARER = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.I)
SECRET_TEXT = re.compile(
    r'''((?:password|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|authorization)["']?\s*[:=]\s*)["']?[^\s,;}"']+''', re.I)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: "[REDACTED]" if SECRET_KEY.search(k) else sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, str):
        # Planner output is itself JSON text; redact nested credential keys as well.
        if value.lstrip().startswith(("{", "[")):
            try:
                parsed = loads(value)
                cleaned = sanitize(parsed)
                if cleaned != parsed:
                    value = dumps(cleaned)
            except (ValueError, TypeError, RecursionError):
                pass  # Malformed model text still receives the textual redaction below.
        return SECRET_TEXT.sub(r"\1[REDACTED]", BEARER.sub("Bearer [REDACTED]", value))
    return value


def validate_prediction(row: JSON) -> None:
    if not isinstance(row, dict) or set(row) != {"id", "tool_calls", "state_hash"}:
        raise PipelineError("OUTPUT_IO", "Prediction has unexpected fields", "output")
    safe_id(row["id"])
    if (not isinstance(row["state_hash"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["state_hash"])
            or not isinstance(row["tool_calls"], list)):
        raise PipelineError("OUTPUT_IO", "Invalid authoritative prediction", "output")
    for call in row["tool_calls"]:
        if (not isinstance(call, dict) or set(call) != {"name", "arguments"}
                or not isinstance(call["name"], str) or not isinstance(call["arguments"], dict)):
            raise PipelineError("OUTPUT_IO", "Invalid authoritative call", "output")
    try:
        dumps(row)
    except (ValueError, TypeError, RecursionError) as exc:
        raise PipelineError("OUTPUT_IO", "Prediction is not finite JSON", "output") from exc


def sync_write(stream, content: str) -> None:
    stream.write(content)
    stream.flush()
    os.fsync(stream.fileno())


def atomic_json(path: Path, value: JSON) -> None:
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            sync_write(stream, dumps(value) + "\n")
        os.replace(temporary, path)
    except (OSError, ValueError, TypeError) as exc:
        raise PipelineError("OUTPUT_IO", "Cannot persist run manifest", "output") from exc
    finally:
        temporary.unlink(missing_ok=True)


def code_provenance() -> JSON:
    root = Path(__file__).resolve().parents[3]
    try:
        def git(*args):
            return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                                  text=True, timeout=10, creationflags=(
                                      subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)).stdout.strip()
        return {"revision": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}
    except (OSError, subprocess.SubprocessError):
        return {"revision": None, "dirty": None, "unavailable": True}


class Trace:
    def __init__(self, path: Path, run_id: str, sample_id: str, *, payloads: bool = False,
                 event_limit: int = 65_536, total_limit: int = 8 * 1024 * 1024,
                 clock=time.monotonic):
        self.run_id, self.sample_id = run_id, safe_id(sample_id)
        self.payloads, self.event_limit, self.total_limit = payloads, event_limit, total_limit
        self.clock, self.started = clock, clock()
        self.sequence, self.written = 0, 0
        try:
            self.stream = path.open("x", encoding="utf-8", newline="\n")
        except OSError as exc:
            raise PipelineError("TRACE_IO", "Cannot create sample trace", "trace") from exc

    def emit(self, kind: str, *, step: int | None = None, payload: Any = None, **metadata: Any) -> None:
        event = {"schema_version": SCHEMA_VERSION, "run_id": self.run_id,
                 "sample_id": self.sample_id, "sequence": self.sequence + 1,
                 "kind": kind, "elapsed": self.clock() - self.started, "step": step,
                 **sanitize(metadata)}
        if payload is not None:
            serialized = dumps(payload)
            event["payload_original_bytes"] = len(serialized.encode("utf-8"))
            if not self.payloads:
                event.update(payload_omitted=True,
                             payload_fields=sorted(payload) if isinstance(payload, dict) else [])
            else:
                cleaned = sanitize(payload)
                event.update(payload_omitted=False, payload_redacted=cleaned != payload, payload=cleaned)
        try:
            encoded = dumps(event)
            if len(encoded.encode("utf-8")) + 1 > self.event_limit and "payload" in event:
                # A bounded JSON string preview remains valid JSON even when the payload was cut.
                budget = max(0, (self.event_limit - len(dumps({k: v for k, v in event.items() if k != "payload"}).encode()) - 256) // 6)
                event["payload"] = {"preview": dumps(event["payload"]).encode("utf-8")[:budget].decode("utf-8", errors="ignore")}
                event["payload_truncated"] = True
                encoded = dumps(event)
            size = len(encoded.encode("utf-8")) + 1
            reserve = 0 if kind in {"sample_finished", "sample_failed"} else 2 * self.event_limit
            if size > self.event_limit or self.written + size + reserve > self.total_limit:
                raise PipelineError("TRACE_IO", "Trace capacity exhausted", "trace")
            sync_write(self.stream, encoded + "\n")  # Includes call intent, before dispatch.
            self.sequence += 1
            self.written += size
        except (OSError, ValueError, TypeError) as exc:
            raise PipelineError("TRACE_IO", "Cannot persist trace event", "trace") from exc

    def close(self) -> None:
        try:
            self.stream.close()
        except OSError as exc:
            raise PipelineError("TRACE_IO", "Cannot close sample trace", "trace") from exc


class RunStore:
    def __init__(self, config: RunConfig):
        if config.run_dir is None:
            raise PipelineError("INPUT_INVALID", "run requires --run-dir")
        self.directory = config.run_dir.absolute()
        self.manifest_path = self.directory / "manifest.json"
        self.partial_path = self.directory / "predictions.partial.jsonl"
        self.final_path = self.directory / "predictions.jsonl"
        self.run_id = uuid.uuid4().hex
        self.payloads = config.trace_payloads
        self.config = config
        self.manifest = {
            "schema_version": SCHEMA_VERSION, "run_id": self.run_id,
            "status": "running", "started_at": utc_now(), "ended_at": None,
            "split": config.split, "input_mode": config.input_mode,
            "requested_ids": list(config.selected_ids), "select_all": config.select_all,
            "selected_ids": [], "completed_ids": [], "failed_ids": [], "not_started_ids": [],
            "submission_ready": False, "code": code_provenance(),
            "python": platform.python_version(), "package_version": __version__,
            "prompt_version": PROMPT_VERSION, "prompt_sha256": PROMPT_HASH,
            "seed": config.seed, "device": config.device,
            "selection_filter": config.selection_filter,
            "model_offload": config.model_offload,
            "limits": vars(config.limits), "benchmark_deadline_configured": config.limits.timeout <= 30,
            "trace_payloads": config.trace_payloads,
            "trace_event_bytes": 65_536, "trace_sample_bytes": 8 * 1024 * 1024,
            "command": "run", "argv": list(__import__("sys").argv[1:]),
            "data_root": str(config.data_root.resolve()), "runtime_dir": str(config.runtime_dir.resolve()),
            "model_initialization_seconds": None, "samples": [],
            "continue_on_error": config.continue_on_error, "failures": [],
        }
        try:
            self.directory.parent.mkdir(parents=True, exist_ok=True)
            self.directory.mkdir(exist_ok=False)
            (self.directory / "traces").mkdir()
            self.save()
            with self.partial_path.open("x", encoding="utf-8"):
                pass
        except PipelineError:
            raise
        except OSError as exc:
            raise PipelineError("OUTPUT_IO", "Run directory must be new and writable", "output") from exc

    def save(self) -> None:
        atomic_json(self.manifest_path, self.manifest)

    def selected(self, metadata: JSON, runtime_metadata: JSON) -> None:
        from .provenance import execution_identity

        self.manifest.update(metadata)
        self.manifest["execution_identity"] = execution_identity(self.config)
        self.manifest["not_started_ids"] = list(metadata["selected_ids"])
        self.manifest["runtime"] = runtime_metadata
        self.save()

    def trace(self, sample_id: str) -> Trace:
        return Trace(self.directory / "traces" / f"{safe_id(sample_id)}.jsonl",
                     self.run_id, sample_id, payloads=self.payloads)

    def restore(self, source: Path) -> None:
        """Import committed results into this fresh run; never reopen completed environments."""
        from .checkpoint import read_checkpoint

        if (self.manifest["completed_ids"] or self.manifest["samples"] or "resume" in self.manifest
                or self.partial_path.stat().st_size):
            raise PipelineError("INPUT_INVALID", "Resume import requires an empty new run", "resume")
        rows, previous, provenance = read_checkpoint(source, self.manifest,
                                                     allow_mixed=self.config.allow_mixed_resume)
        atomic_json(self.directory / "resume-source-manifest.json", previous)
        completed = [row["id"] for row in rows]
        records = {s["id"]: s for s in previous["samples"]}
        imported = []
        for sample_id in completed:
            record = dict(records.get(sample_id, {"id": sample_id, "status": "completed",
                                                  "timing_unavailable": True}))
            record.setdefault("source_run_id", previous["run_id"])
            record.setdefault("trace_path", str(source.resolve() / "traces" / f"{sample_id}.jsonl"))
            imported.append(record)
        # Provenance must survive a crash during the row import, too. Completion is
        # committed only by the subsequent newline-terminated, fsynced journal rows.
        self.manifest.update(resume=provenance, samples=imported)
        self.save()

        try:
            with self.partial_path.open("w", encoding="utf-8", newline="\n") as stream:
                sync_write(stream, "".join(dumps(row) + "\n" for row in rows))
        except OSError as exc:
            raise PipelineError("OUTPUT_IO", "Cannot import resume predictions", "resume") from exc
        self.manifest.update(completed_ids=completed,
                             not_started_ids=[i for i in self.manifest["selected_ids"] if i not in completed])
        self.save()

    def verify_execution_snapshot(self) -> None:
        from .provenance import execution_identity

        if execution_identity(self.config) != self.manifest["execution_identity"]:
            raise PipelineError("INPUT_INVALID", "Execution identity changed during model loading; restart with fixed inputs",
                                "configuration")

    def verify_code_snapshot(self) -> None:
        from .provenance import code_identity

        if code_identity() != self.manifest["execution_identity"]["code"]:
            raise PipelineError("INPUT_INVALID", "Pipeline code changed during this run; restart with a fixed version",
                                "configuration")

    def append(self, outcome) -> None:
        if outcome.result is None or outcome.status == "failed":
            raise PipelineError("OUTPUT_IO", "Failure cannot become a prediction", "output")
        validate_prediction(outcome.result)
        if (outcome.id not in self.manifest["not_started_ids"]
                or outcome.id in self.manifest["completed_ids"] or outcome.result["id"] != outcome.id):
            raise PipelineError("OUTPUT_IO", "Prediction order/identity mismatch", "output")
        try:
            with self.partial_path.open("a", encoding="utf-8", newline="\n") as stream:
                sync_write(stream, dumps(outcome.result) + "\n")
        except OSError as exc:
            raise PipelineError("OUTPUT_IO", "Cannot persist prediction row", "output") from exc
        self.manifest["completed_ids"].append(outcome.id)
        self.manifest["not_started_ids"].remove(outcome.id)
        self.manifest["samples"].append({"id": outcome.id, "status": outcome.status,
                                         "elapsed": outcome.elapsed, "steps": outcome.steps,
                                         "timings": outcome.timings, "stop_reason": outcome.stop_reason})
        self.save()

    def sample_failed(self, error: JSON, sample_id: str) -> None:
        if sample_id not in self.manifest["failed_ids"]:
            self.manifest["failed_ids"].append(sample_id)
            self.manifest["failures"].append({"id": sample_id, "error": sanitize(error)})
        if sample_id in self.manifest["not_started_ids"]:
            self.manifest["not_started_ids"].remove(sample_id)
        self.save()

    def fail(self, error: JSON, sample_id: str | None = None) -> None:
        self.manifest.update(status="failed", ended_at=utc_now(), error=sanitize(error))
        if sample_id is not None:
            self.sample_failed(error, sample_id)
            return
        self.save()

    def finish(self) -> None:
        try:
            rows = [loads(line) for line in self.partial_path.read_text(encoding="utf-8").splitlines()]
            for row in rows:
                validate_prediction(row)
            ids = [row["id"] for row in rows]
            if (not ids or len(set(ids)) != len(ids) or self.manifest["failed_ids"]
                    or set(ids) != set(self.manifest["selected_ids"])
                    or ids != self.manifest["completed_ids"]):
                raise PipelineError("OUTPUT_IO", "Cannot publish incomplete selection", "output")
            if ids != self.manifest["selected_ids"]:
                # Resume/continue journals can have holes; publish exactly in dataset order.
                by_id = {row["id"]: row for row in rows}
                ordered = self.partial_path.with_suffix(".ordered.tmp")
                try:
                    with ordered.open("x", encoding="utf-8", newline="\n") as stream:
                        sync_write(stream, "".join(dumps(by_id[i]) + "\n" for i in self.manifest["selected_ids"]))
                    os.replace(ordered, self.partial_path)
                finally:
                    ordered.unlink(missing_ok=True)
            os.replace(self.partial_path, self.final_path)
            self.manifest.update(status="completed", ended_at=utc_now(),
                                 prediction_path=str(self.final_path), not_started_ids=[],
                                 completed_ids=list(self.manifest["selected_ids"]))
            self.save()
        except PipelineError:
            raise
        except (OSError, ValueError, TypeError) as exc:
            raise PipelineError("OUTPUT_IO", "Final prediction publication failed", "output") from exc


# --- Integration run artifacts (ADR 011). RunStore above stays the legacy format. ---

JOURNAL_TYPES = frozenset({"run", "resume", "worker_started", "worker_stopped",
                           "reserve", "accept", "fail"})
STAGED_FILE_BYTES = 4 * 1024 * 1024


class FileLock:
    """Non-blocking OS lock released by the kernel when its owner process dies."""

    def __init__(self, path: Path):
        self.path, self.handle = path, None

    def acquire(self) -> bool:
        if self.handle is not None:
            return True
        handle = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.handle = handle
        return True

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


def fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return  # Windows cannot open directories for fsync; NTFS journals metadata.
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_durable(path: Path, content: str) -> None:
    """Create a new file, flush, fsync and close it; never overwrite."""
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        sync_write(stream, content)
    fsync_directory(path.parent)


def _check(record: JSON) -> str:
    return hashlib.sha256(dumps(record).encode("utf-8")).hexdigest()[:32]


class JournalState:
    """Validated fold of journal records; pure, so appends can be checked first."""

    def __init__(self):
        self.records: list[JSON] = []
        self.header: JSON | None = None
        self.reservations: dict[str, JSON] = {}   # attempt_id -> reserve record
        self.terminal: dict[str, JSON] = {}       # attempt_id -> accept/fail record
        self.by_sample: dict[str, str] = {}       # sample_id -> attempt_id
        self.generations: dict[int, JSON] = {}    # generation -> worker_started record
        self.stopped: set[int] = set()

    def copy(self) -> "JournalState":
        other = JournalState()
        other.records, other.header = list(self.records), self.header
        other.reservations, other.terminal = dict(self.reservations), dict(self.terminal)
        other.by_sample, other.generations = dict(self.by_sample), dict(self.generations)
        other.stopped = set(self.stopped)
        return other

    def apply(self, record: JSON) -> None:
        from .contracts import ACCEPTED_STATES, FAILED_STATES, AttemptIdentity

        def bad(message):
            return PipelineError("JOURNAL_INVALID", message, "journal")

        kind = record.get("type")
        if kind not in JOURNAL_TYPES or record.get("seq") != len(self.records) + 1:
            raise bad("Unknown journal record type or broken sequence")
        if (kind == "run") != (not self.records):
            raise bad("Journal must start with exactly one run header")
        if kind == "run":
            self.header = record
        elif kind == "worker_started":
            if type(record.get("generation")) is not int or record["generation"] in self.generations:
                raise bad("Invalid worker generation record")
            self.generations[record["generation"]] = record
        elif kind == "worker_stopped":
            if record.get("generation") not in self.generations:
                raise bad("Stop for an unknown worker generation")
            self.stopped.add(record["generation"])
        elif kind == "reserve":
            try:
                identity = AttemptIdentity(record.get("sample_id"), record.get("attempt_id"),
                                           record.get("generation"), record.get("config_sha256"))
            except PipelineError as exc:
                raise bad("Invalid reservation identity") from exc
            if (identity.sample_id in self.by_sample or identity.attempt_id in self.reservations
                    or identity.generation not in self.generations
                    or identity.generation in self.stopped or self.unresolved()):
                raise bad("Sample/attempt reserved twice, unknown/stopped worker, or overlapping attempts")
            self.reservations[identity.attempt_id] = record
            self.by_sample[identity.sample_id] = identity.attempt_id
        elif kind in {"accept", "fail"}:
            attempt = record.get("attempt_id")
            reserved = self.reservations.get(attempt)
            if reserved is None or attempt in self.terminal or reserved["sample_id"] != record.get("sample_id"):
                raise bad("Terminal record without one matching reservation")
            if kind == "accept":
                if record.get("status") not in ACCEPTED_STATES:
                    raise bad("Invalid accepted status")
                try:
                    validate_prediction(record.get("prediction"))
                except PipelineError as exc:
                    raise bad("Invalid accepted prediction") from exc
                if record["prediction"]["id"] != record["sample_id"]:
                    raise bad("Accepted prediction identity mismatch")
            elif record.get("status") not in FAILED_STATES or not isinstance(record.get("error"), dict):
                raise bad("Invalid failure record")
            self.terminal[attempt] = record
        self.records.append(record)

    def unresolved(self) -> list[JSON]:
        return [r for a, r in self.reservations.items() if a not in self.terminal]


class RunJournal:
    """Append-only, checksummed, fsynced reservation/acceptance journal.

    Ordering contract: reserve() must be durable before dispatch; accept()/fail()
    must be durable before the next reservation. A reservation without a durable
    terminal record is uncertain after any crash and is never dispatched again.
    """

    def __init__(self, root: Path):
        self.root = root
        self.path = root / "journal.jsonl"
        self.staging, self.quarantine_root = root / "staging", root / "quarantine"
        self.workers = root / "workers"
        self.lock = FileLock(root / "run.lock")
        self.state = JournalState()
        self.broken = False

    @property
    def header(self) -> JSON | None:
        return self.state.header

    # Ownership -------------------------------------------------------------
    @classmethod
    def create(cls, root: Path, header: JSON) -> "RunJournal":
        root = root.absolute()
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PipelineError("OUTPUT_IO", "Output root is not writable", "output") from exc
        journal = cls(root)
        journal._own()
        try:
            if journal.path.exists():
                raise PipelineError("INPUT_INVALID", "Output root already holds a run; pass --resume", "journal")
            for directory in (journal.staging, journal.quarantine_root, journal.workers):
                directory.mkdir(exist_ok=True)
            with journal.path.open("x", encoding="utf-8"):
                pass
            fsync_directory(root)
            journal.append("run", **header)
        except BaseException:
            journal.close()
            raise
        return journal

    @classmethod
    def resume(cls, root: Path, header: JSON) -> "RunJournal":
        journal = cls(root.absolute())
        if not journal.path.is_file():
            raise PipelineError("INPUT_INVALID", "No journal to resume in output root", "journal")
        journal._own()
        try:
            journal._load()
            if (journal.header or {}).get("run_sha256") != header.get("run_sha256"):
                raise PipelineError("INPUT_INVALID", "Resume rejected: model, template, configuration, data "
                                    "or code identity differs from the original run", "journal")
            journal.append("resume", run_sha256=header["run_sha256"])
        except BaseException:
            journal.close()
            raise
        return journal

    def _own(self, wait: float = 5.0) -> None:
        # Kernels may release a dead owner's lock with a short delay (notably Windows);
        # a bounded wait never grants ownership while another live process holds it.
        ends = time.monotonic() + wait
        while True:
            try:
                owned = self.lock.acquire()
            except OSError as exc:
                raise PipelineError("OUTPUT_IO", "Cannot open the run lock", "journal") from exc
            if owned:
                return
            if time.monotonic() >= ends:
                raise PipelineError("RUN_OWNERSHIP", "Another supervisor owns this run", "journal")
            time.sleep(0.05)

    def close(self) -> None:
        self.lock.release()

    def _load(self) -> None:
        try:
            data = self.path.read_bytes().decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise PipelineError("JOURNAL_INVALID", "Journal is unreadable", "journal") from exc
        if not data or not data.endswith("\n"):
            raise PipelineError("JOURNAL_INVALID", "Journal is empty or ends with a truncated record", "journal")
        for line in data.splitlines():
            try:
                record = loads(line)
            except (ValueError, RecursionError) as exc:
                raise PipelineError("JOURNAL_INVALID", "Journal record is not valid JSON", "journal") from exc
            if not isinstance(record, dict) or record.pop("check", None) != _check(record):
                raise PipelineError("JOURNAL_INVALID", "Journal record checksum mismatch", "journal")
            self.state.apply(record)

    # Appends ---------------------------------------------------------------
    def append(self, kind: str, **fields) -> JSON:
        if self.broken:
            raise PipelineError("OUTPUT_IO", "Journal is in an unknown state after a write failure", "journal")
        record = {"seq": len(self.state.records) + 1, "type": kind, "at": utc_now(), **fields}
        try:
            self.state.copy().apply(record)  # Validate before writing anything.
        except PipelineError as exc:
            raise PipelineError("OUTPUT_IO", "Refusing an inconsistent journal record", "journal") from exc
        line = dumps(record | {"check": _check(record)}) + "\n"
        try:
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                sync_write(stream, line)
        except (OSError, ValueError) as exc:
            self.broken = True  # A partial line may exist; never write after it.
            raise PipelineError("OUTPUT_IO", "Journal write failed; run stops", "journal") from exc
        self.state.apply(record)
        return record

    def worker_started(self, generation: int, pid: int) -> None:
        self.append("worker_started", generation=generation, pid=pid,
                    lock=f"workers/gen-{generation}.lock")

    def worker_stopped(self, generation: int, *, confirmed: bool, reason: str) -> None:
        self.append("worker_stopped", generation=generation, confirmed=confirmed, reason=reason)

    def reserve(self, identity) -> None:
        self.append("reserve", **identity.record())

    def accept(self, identity, status: str, prediction: JSON, metrics: JSON) -> None:
        self.append("accept", sample_id=identity.sample_id, attempt_id=identity.attempt_id,
                    status=status, prediction=prediction, metrics=sanitize(metrics))

    def fail(self, identity_or_reservation, status: str, error: JSON, metrics: JSON | None = None) -> None:
        value = (identity_or_reservation.record() if hasattr(identity_or_reservation, "record")
                 else identity_or_reservation)
        self.append("fail", sample_id=value["sample_id"], attempt_id=value["attempt_id"],
                    status=status, error=sanitize(error), metrics=sanitize(metrics or {}))

    # Recovery and queries --------------------------------------------------
    def unresolved(self) -> list[JSON]:
        return self.state.unresolved()

    def mark_uncertain(self) -> list[str]:
        """After an unclean stop, reserved-without-acceptance IDs become terminal failures."""
        ids = []
        for reservation in self.unresolved():
            self.fail(reservation, "failed", {
                "code": "EXECUTION_UNCERTAIN", "stage": "recovery",
                "message": "Reserved before supervisor loss without durable acceptance; never replayed"})
            ids.append(reservation["sample_id"])
        return ids

    def attempted(self) -> set[str]:
        return set(self.state.by_sample)

    def accepted(self) -> dict[str, JSON]:
        return {r["sample_id"]: r for r in self.state.terminal.values() if r["type"] == "accept"}

    def failed(self) -> dict[str, JSON]:
        return {r["sample_id"]: r for r in self.state.terminal.values() if r["type"] == "fail"}

    def unstopped_workers(self) -> list[JSON]:
        return [r for g, r in self.state.generations.items() if g not in self.state.stopped]

    def next_generation(self) -> int:
        return max(self.state.generations, default=0) + 1

    # Staging ---------------------------------------------------------------
    def staging_dir(self, attempt_id: str) -> Path:
        return self.staging / attempt_id

    def read_staged(self, attempt_id: str, name: str) -> JSON:
        """Read one bounded staged JSON file constrained to the attempt's directory."""
        base = self.staging_dir(attempt_id).resolve()
        if not re.fullmatch(r"[a-z_]{1,32}\.json", name):
            raise PipelineError("WORKER_FAILED", "Staged artifact name is invalid", "acceptance")
        path = (base / name).resolve()
        if path.parent != base or not path.is_file() or path.stat().st_size > STAGED_FILE_BYTES:
            raise PipelineError("WORKER_FAILED", "Staged artifact is missing or oversized", "acceptance")
        try:
            return loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            raise PipelineError("WORKER_FAILED", "Staged artifact is invalid", "acceptance") from exc

    def quarantine(self, attempt_id: str) -> Path | None:
        source = self.staging_dir(attempt_id)
        if not source.exists():
            return None
        target = self.quarantine_root / attempt_id
        os.replace(source, target)
        return target

    def quarantine_unaccepted(self) -> list[str]:
        accepted = {r["attempt_id"] for r in self.accepted().values()}
        moved = []
        if self.staging.is_dir():
            for entry in sorted(self.staging.iterdir()):
                if entry.is_dir() and entry.name not in accepted and self.quarantine(entry.name):
                    moved.append(entry.name)
        return moved


def publish_predictions(journal: RunJournal, selected_ids: list[str]) -> JSON:
    """Write accepted rows; publish predictions.jsonl only for exact, failure-free coverage."""
    accepted, failed = journal.accepted(), journal.failed()
    rows = [accepted[i]["prediction"] for i in selected_ids if i in accepted]
    for row in rows:
        validate_prediction(row)
    partial = journal.root / "predictions.partial.jsonl"
    final = journal.root / "predictions.jsonl"
    if final.exists():
        # Publication happens once; a complete file never coexists with further work.
        raise PipelineError("OUTPUT_IO", "Predictions were already published for this run", "packaging")
    temporary = partial.with_name(partial.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            sync_write(stream, "".join(dumps(row) + "\n" for row in rows))
        os.replace(temporary, partial)
    except OSError as exc:
        raise PipelineError("OUTPUT_IO", "Cannot write accepted predictions", "packaging") from exc
    finally:
        temporary.unlink(missing_ok=True)
    missing = [i for i in selected_ids if i not in accepted and i not in failed]
    extra = sorted(set(accepted) - set(selected_ids))
    complete = (not failed and not missing and not extra and not journal.unresolved()
                and len(rows) == len(selected_ids))
    if complete:
        try:
            os.replace(partial, final)
            fsync_directory(journal.root)
        except OSError as exc:
            raise PipelineError("OUTPUT_IO", "Cannot publish predictions", "packaging") from exc
    return {"complete": complete, "accepted": len(rows), "failed": sorted(failed),
            "missing": missing, "path": str(final if complete else partial)}
