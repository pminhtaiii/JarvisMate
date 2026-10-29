"""Durable predictions, bounded opt-in traces, and explicit run publication."""
from __future__ import annotations

import math
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
from .metrics import METRICS_SCHEMA_VERSION
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


def _valid_attempt_seconds(value) -> None:
    if (value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0)):
        raise PipelineError("OUTPUT_IO", "full_attempt_seconds must be a nonnegative finite number", "output")


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
            "schema_version": SCHEMA_VERSION, "metrics_schema_version": METRICS_SCHEMA_VERSION,
            "run_id": self.run_id,
            "status": "running", "started_at": utc_now(), "ended_at": None,
            "split": config.split, "input_mode": config.input_mode,
            "requested_ids": list(config.selected_ids), "select_all": config.select_all,
            "selected_ids": [], "completed_ids": [], "failed_ids": [], "not_started_ids": [],
            "submission_ready": False, "code": code_provenance(),
            "python": platform.python_version(), "package_version": __version__,
            "prompt_version": PROMPT_VERSION, "prompt_sha256": PROMPT_HASH, "effective_prompt": None,
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
            # A pre-measurement source manifest has neither key: make that absence
            # an explicit null rather than an ambiguous missing key, so a reader
            # never has to distinguish "not implemented yet" from "unavailable".
            record.setdefault("measurements", None)
            record.setdefault("full_attempt_seconds", None)
            # Always this run's perspective, even if the source manifest had it as executed there.
            record["source"] = "imported"
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

    def append(self, outcome, *, measurements: JSON | None = None,
              full_attempt_seconds: float | None = None) -> None:
        if outcome.result is None or outcome.status == "failed":
            raise PipelineError("OUTPUT_IO", "Failure cannot become a prediction", "output")
        if measurements is not None and not isinstance(measurements, dict):
            raise PipelineError("OUTPUT_IO", "Measurements payload must be an object", "output")
        _valid_attempt_seconds(full_attempt_seconds)
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
                                         "timings": outcome.timings, "stop_reason": outcome.stop_reason,
                                         "source": "executed", "measurements": measurements,
                                         "full_attempt_seconds": full_attempt_seconds})
        self.save()

    def sample_failed(self, error: JSON, sample_id: str, *, measurements: JSON | None = None,
                      full_attempt_seconds: float | None = None, agent_loop: JSON | None = None) -> None:
        if measurements is not None and not isinstance(measurements, dict):
            raise PipelineError("OUTPUT_IO", "Measurements payload must be an object", "output")
        if agent_loop is not None and not isinstance(agent_loop, dict):
            raise PipelineError("OUTPUT_IO", "agent_loop summary must be an object", "output")
        _valid_attempt_seconds(full_attempt_seconds)
        if sample_id not in self.manifest["failed_ids"]:
            self.manifest["failed_ids"].append(sample_id)
            # agent_loop is only ever set when run_sample itself reported
            # completed/needs_info and a *later* step (durable output) failed;
            # it distinguishes that case from the loop having failed outright.
            self.manifest["failures"].append({"id": sample_id, "error": sanitize(error),
                                              "measurements": sanitize(measurements) if measurements else measurements,
                                              "full_attempt_seconds": full_attempt_seconds,
                                              "agent_loop": agent_loop})
        if sample_id in self.manifest["not_started_ids"]:
            self.manifest["not_started_ids"].remove(sample_id)
        self.save()

    def fail(self, error: JSON, sample_id: str | None = None, *, measurements: JSON | None = None,
            full_attempt_seconds: float | None = None, agent_loop: JSON | None = None) -> None:
        self.manifest.update(status="failed", ended_at=utc_now(), error=sanitize(error))
        if sample_id is not None:
            self.sample_failed(error, sample_id, measurements=measurements,
                              full_attempt_seconds=full_attempt_seconds, agent_loop=agent_loop)
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
