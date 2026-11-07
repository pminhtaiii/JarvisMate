"""Persistent spawned integration worker: loads models once, runs isolated attempts.

Protocol (length-prefixed JSON frames on stdin/stdout; logs go to stderr):

  worker -> {"type": "ready", "generation", "pid", "startup_seconds", "metadata"}
  super  -> {"type": "dispatch", "generation", "attempt_id", "sample_id", "budget_seconds"}
  worker -> {"type": "result_ready", "generation", "attempt_id", "sample_id", "status", "files"}
  super  -> {"type": "shutdown"}

The worker writes every staged artifact durably under ``staging/<attempt_id>/`` before
``result_ready``. The supervisor alone decides acceptance; this module imports no
model library at import time.
"""
from __future__ import annotations

import argparse
import importlib
import os
import struct
import sys
import time
from pathlib import Path

from .contracts import JSON, PipelineError

MAX_FRAME = 1024 * 1024
HEADER = struct.Struct(">I")


class FrameError(Exception):
    """Malformed, oversized or truncated IPC frame."""


def encode_frame(message: JSON) -> bytes:
    from .jsonio import dumps

    payload = dumps(message).encode("utf-8")
    if len(payload) > MAX_FRAME:
        raise FrameError("Frame exceeds the IPC size bound")
    return HEADER.pack(len(payload)) + payload


def read_exact(stream, size: int) -> bytes:
    chunks, remaining = [], size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise EOFError("Stream closed" + (" inside a frame" if remaining != size or chunks else ""))
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(stream) -> JSON:
    """Blocking read of one frame; validates size, encoding and object shape."""
    from .jsonio import loads

    (size,) = HEADER.unpack(read_exact(stream, HEADER.size))
    if not 0 < size <= MAX_FRAME:
        raise FrameError("Frame size is out of bounds")
    try:
        message = loads(read_exact(stream, size).decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise FrameError("Frame is not strict JSON") from exc
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise FrameError("Frame must be an object with a type")
    return message


def hardware() -> JSON:
    """Best-effort device evidence; never a submission field."""
    info: JSON = {"cpu_count": os.cpu_count()}
    try:
        import torch

        info.update(torch=torch.__version__, cuda=torch.version.cuda, cuda_available=torch.cuda.is_available())
        if torch.cuda.is_available():
            info["devices"] = [{"index": i, "name": torch.cuda.get_device_name(i),
                                "memory_bytes": torch.cuda.get_device_properties(i).total_memory}
                               for i in range(torch.cuda.device_count())]
    except Exception:  # noqa: BLE001 - hardware evidence is optional.
        info["torch"] = None
    return info


def peak_memory() -> JSON | None:
    try:
        import torch

        if torch.cuda.is_available():
            return {f"cuda:{i}": torch.cuda.max_memory_allocated(i) for i in range(torch.cuda.device_count())}
    except Exception:  # noqa: BLE001
        pass
    return None


def default_factory(config) -> JSON:
    from .integration import build_components

    return build_components(config)


def load_factory(spec: str):
    module, _, attribute = spec.partition(":")
    if not module or not attribute:
        raise PipelineError("INPUT_INVALID", "Worker factory must be module:attribute", "worker")
    return getattr(importlib.import_module(module), attribute)


class Worker:
    def __init__(self, run_root: Path, generation: int, factory, output, clock=time.monotonic):
        from .artifacts import FileLock
        from .configuration import read_effective, run_config
        from .dataset import preflight
        from .runtime import load_runtime

        self.root, self.generation, self.output, self.clock = run_root, generation, output, clock
        self.lock = FileLock(run_root / "workers" / f"gen-{generation}.lock")
        if not self.lock.acquire():
            raise PipelineError("RUN_OWNERSHIP", "Worker generation lock is held", "worker")
        started = clock()
        self.config = read_effective(run_root / "effective-config.json")
        legacy = run_config(self.config)
        self.dataset = preflight(legacy)
        self.samples = {sample.id: sample for sample in self.dataset.samples}
        self.components = factory(self.config)
        self.environments = self.components.get("environment_factory") or load_runtime(legacy, self.dataset)
        self.ready = {"type": "ready", "generation": generation, "pid": os.getpid(),
                      "startup_seconds": clock() - started, "hardware": hardware(),
                      "metadata": self.components.get("metadata", {})}

    def send(self, message: JSON) -> None:
        self.output.write(encode_frame(message))
        self.output.flush()

    def attempt(self, message: JSON) -> JSON:
        """Run one dispatched sample; durable staging happens inside its budget."""
        from .agent import run_integration_sample
        from .artifacts import Trace, write_durable
        from .contracts import Deadline
        from .jsonio import dumps

        deadline = Deadline(float(message["budget_seconds"]), self.clock)
        attempt_id, sample_id = message["attempt_id"], message["sample_id"]
        staging = self.root / "staging" / attempt_id
        staging.mkdir()  # Unique per attempt; an existing directory is never reused.
        trace = Trace(staging / "trace.jsonl", attempt_id, sample_id, payloads=self.config.debug_payloads,
                      clock=self.clock)
        sample = self.samples.get(sample_id)
        try:
            if sample is None:
                raise PipelineError("INPUT_INVALID", "Dispatched sample was not preflighted", "worker")
            outcome = run_integration_sample(
                sample, self.components["planner"], self.components.get("asr"), self.environments, trace,
                self.config.limits, deadline, split=self.config.split, data_root=self.config.data_root,
                asr_identity=self.components.get("asr_identity", ""), clock=self.clock)
        finally:
            trace.close()
        status = (outcome.status if outcome.status != "failed"
                  else "timeout" if outcome.error and outcome.error["code"] == "TIME_LIMIT" else "failed")
        files = ["outcome.json"]
        started = self.clock()
        if outcome.result is not None and status in {"completed", "needs_info"}:
            write_durable(staging / "prediction.json", dumps(outcome.result) + "\n")
            files.append("prediction.json")
        record = {"attempt_id": attempt_id, "sample_id": sample_id, "generation": self.generation,
                  "status": status, "elapsed": outcome.elapsed, "steps": outcome.steps,
                  "stop_reason": outcome.stop_reason, "error": outcome.error, "timings": outcome.timings,
                  "metrics": outcome.metrics, "peak_memory_bytes": peak_memory(),
                  "diagnostic_available": outcome.diagnostic is not None}
        # The outcome file's own write is covered by the supervisor's full-attempt span.
        record["timings"] = dict(record["timings"], output=self.clock() - started)
        write_durable(staging / "outcome.json", dumps(record) + "\n")
        return {"type": "result_ready", "generation": self.generation, "attempt_id": attempt_id,
                "sample_id": sample_id, "status": status, "files": files,
                "worker_elapsed": deadline.elapsed()}

    def serve(self, source) -> int:
        self.send(self.ready)
        while True:
            try:
                message = read_frame(source)
            except EOFError:
                return 0  # Supervisor gone: never continue unsupervised.
            if message["type"] == "shutdown":
                return 0
            if (message["type"] != "dispatch" or message.get("generation") != self.generation
                    or not isinstance(message.get("attempt_id"), str) or not isinstance(message.get("sample_id"), str)):
                return 3  # Protocol violation: stop rather than guess.
            self.send(self.attempt(message))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="lifemate.worker")
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--generation", required=True, type=int)
    parser.add_argument("--factory", default="lifemate.worker:default_factory")
    args = parser.parse_args(argv)
    # Reserve the real stdout for frames; anything printed by libraries goes to stderr.
    output = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
    source = os.fdopen(os.dup(sys.stdin.fileno()), "rb")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    try:
        worker = Worker(args.run_root, args.generation, load_factory(args.factory), output)
    except PipelineError as exc:
        output.write(encode_frame({"type": "startup_failed", "generation": args.generation, "error": exc.record()}))
        output.flush()
        return 2
    return worker.serve(source)


if __name__ == "__main__":
    sys.exit(main())
