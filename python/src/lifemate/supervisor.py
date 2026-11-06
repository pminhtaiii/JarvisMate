"""External full-attempt supervision for the integration entry point (ADR 011).

The supervisor owns the run journal, worker generations and attempt identities. It
durably reserves an attempt before dispatch, starts one monotonic clock immediately
before dispatch and accepts only a matching ``result_ready`` received strictly
before expiry. Every IPC wait is bounded by that deadline. On expiry or crash the
worker's process group is terminated, termination is confirmed through the worker's
kernel lock, and unaccepted staging is quarantined. Failed samples are never retried.
"""
from __future__ import annotations

import os
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .artifacts import FileLock, RunJournal, validate_prediction
from .contracts import ACCEPTED_STATES, AttemptIdentity, JSON, PipelineError
from .worker import FrameError, encode_frame, read_frame

LOG_LIMIT = 8 * 1024 * 1024
TERMINATION_WAIT = 10.0


class WorkerLost(Exception):
    """The worker closed its channel, crashed or violated the protocol."""


def lock_free(path: Path) -> bool:
    lock = FileLock(path)
    try:
        if lock.acquire():
            lock.release()
            return True
    except OSError:
        pass
    return False


def kill_tree(pid: int) -> None:
    """Terminate a worker and its process group/tree; errors mean already gone."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=10,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            os.killpg(pid, signal.SIGKILL)  # start_new_session makes the worker its group leader.
    except (OSError, subprocess.SubprocessError):
        pass


def wait_for_lock(path: Path, timeout: float, clock=time.monotonic) -> bool:
    ends = clock() + timeout
    while True:
        if lock_free(path):
            return True
        if clock() >= ends:
            return False
        time.sleep(0.02)


class WorkerHandle:
    """One spawned worker process with bounded, deadline-interruptible IPC."""

    def __init__(self, command: list[str], generation: int, root: Path, env: JSON | None = None):
        self.generation, self.root = generation, root
        self.lock_path = root / "workers" / f"gen-{generation}.lock"
        self.log_path = root / "workers" / f"gen-{generation}.log"
        options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
                   if os.name == "nt" else {"start_new_session": True})
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, env=env, **options)
        self.pid = self.process.pid
        self.messages: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._drain_log, daemon=True).start()
        self.stale_messages = 0

    def _read(self) -> None:
        try:
            while True:
                self.messages.put(read_frame(self.process.stdout))
        except (EOFError, FrameError, OSError, ValueError) as exc:
            self.messages.put(WorkerLost(type(exc).__name__))

    def _drain_log(self) -> None:
        written = 0
        try:
            with self.log_path.open("ab") as log:
                while True:
                    chunk = self.process.stderr.read1(65536)
                    if not chunk:
                        return
                    if written < LOG_LIMIT:
                        log.write(chunk[:LOG_LIMIT - written])
                        log.flush()
                    written += len(chunk)  # Keep draining so the worker never blocks on stderr.
        except (OSError, ValueError):
            return

    def send(self, message: JSON, deadline: float, clock=time.monotonic) -> bool:
        """Write one frame in a helper thread; False when the deadline passes first."""
        frame = encode_frame(message)
        done, failed = threading.Event(), []

        def write():
            try:
                self.process.stdin.write(frame)
                self.process.stdin.flush()
            except (OSError, ValueError) as exc:
                failed.append(exc)
            finally:
                done.set()

        threading.Thread(target=write, daemon=True).start()
        if not done.wait(max(0.0, deadline - clock())):
            return False
        if failed:
            raise WorkerLost("dispatch write failed")
        return True

    def receive(self, deadline: float, clock=time.monotonic) -> JSON | None:
        """Next validated message, None at deadline; raises WorkerLost on EOF/protocol error."""
        remaining = deadline - clock()
        if remaining <= 0:
            return None
        try:
            item = self.messages.get(timeout=remaining)
        except queue.Empty:
            return None
        if isinstance(item, WorkerLost):
            self.messages.put(item)  # Sticky: the channel is gone for good.
            raise item
        return item

    def terminate(self, clock=time.monotonic) -> JSON:
        """Kill the process group, reap it and confirm via the kernel-released lock."""
        started = clock()
        kill_tree(self.pid)
        try:
            self.process.kill()
        except OSError:
            pass
        try:
            self.process.wait(TERMINATION_WAIT)
        except subprocess.TimeoutExpired:
            pass
        confirmed = self.process.poll() is not None and wait_for_lock(self.lock_path, TERMINATION_WAIT, clock)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            try:
                stream.close()
            except OSError:
                pass
        return {"confirmed": confirmed, "termination_seconds": clock() - started}

    def shutdown(self, timeout: float = 5.0, clock=time.monotonic) -> JSON:
        try:
            self.send({"type": "shutdown"}, clock() + timeout, clock)
            self.process.wait(timeout)
        except (WorkerLost, subprocess.TimeoutExpired, OSError):
            pass
        if self.process.poll() is None:
            return self.terminate(clock)
        return {"confirmed": wait_for_lock(self.lock_path, TERMINATION_WAIT, clock), "termination_seconds": 0.0}


@dataclass
class AttemptResult:
    sample_id: str
    attempt_id: str
    status: str
    error: JSON | None = None
    metrics: JSON = field(default_factory=dict)


@dataclass
class Supervisor:
    journal: RunJournal
    config_sha256: str
    timeout: float
    startup_timeout: float
    recovery_attempts: int
    command: list[str] | None = None
    env: JSON | None = None
    clock: object = time.monotonic
    fault: object = None  # Test-only crash injection: fault(point) at named ordering points.
    worker: WorkerHandle | None = None
    startups: list = field(default_factory=list)
    losses: int = 0

    # Worker lifecycle --------------------------------------------------------
    def worker_command(self, generation: int) -> list[str]:
        base = self.command or [sys.executable, "-m", "lifemate.worker"]
        return [*base, "--run-root", str(self.journal.root), "--generation", str(generation)]

    def _fault(self, point: str) -> None:
        if self.fault is not None:
            self.fault(point)

    def start_worker(self, reason: str) -> JSON:
        """Spawn a generation and wait, bounded, for its ready acknowledgement."""
        generation = max(self.journal.next_generation(), self._lock_generations() + 1)
        started = self.clock()
        handle = WorkerHandle(self.worker_command(generation), generation, self.journal.root, self.env)
        try:
            self.journal.worker_started(generation, handle.pid)  # Durable before any dispatch.
        except PipelineError:
            handle.terminate(self.clock)
            raise
        deadline = started + self.startup_timeout
        try:
            message = handle.receive(deadline, self.clock)
        except WorkerLost:
            message = None
        record = {"generation": generation, "reason": reason, "seconds": self.clock() - started}
        if message is None or message.get("type") != "ready" or message.get("generation") != generation:
            stop = handle.terminate(self.clock)
            self.journal.worker_stopped(generation, confirmed=stop["confirmed"], reason="startup_failed")
            record.update(status="failed", error=(message or {}).get("error"))
            self.startups.append(record)
            raise PipelineError("RECOVERY_FAILED" if reason == "recovery" else "MODEL_UNAVAILABLE",
                                "Worker did not become ready within the startup timeout", "startup")
        record.update(status="ready", worker_startup_seconds=message.get("startup_seconds"),
                      hardware=message.get("hardware"), models=message.get("metadata"))
        self.startups.append(record)
        self.worker = handle
        return record

    def _lock_generations(self) -> int:
        numbers = []
        for path in self.journal.workers.glob("gen-*.lock"):
            try:
                numbers.append(int(path.stem.split("-", 1)[1]))
            except ValueError:
                continue
        return max(numbers, default=0)

    def ensure_worker(self) -> None:
        """Healthy worker for the next distinct sample, with bounded recovery.

        Each worker loss permits at most ``recovery_attempts`` (0 or 1) restarts; a
        failed restart stops the run nonzero with prior accepted rows intact.
        """
        if self.worker is not None:
            return
        if not self.startups:
            self.start_worker("startup")
        elif self.recovery_attempts < 1:
            raise PipelineError("RECOVERY_FAILED", "Worker lost and recovery_attempts = 0", "recovery")
        else:
            self.start_worker("recovery")

    def confirm_prior_workers(self) -> list[JSON]:
        """Resume: establish that every earlier generation is gone before any dispatch."""
        confirmed = []
        known = {r["generation"]: r for r in self.journal.state.generations.values()}
        for path in sorted(self.journal.workers.glob("gen-*.lock")):
            suffix = path.stem.partition("-")[2]
            generation = int(suffix) if suffix.isdigit() else None
            if lock_free(path):
                confirmed.append({"generation": generation, "status": "not_running"})
                continue
            record = known.get(generation)
            if record is not None:
                kill_tree(record["pid"])  # The lock is held, so the recorded pid is still that worker.
            if not wait_for_lock(path, TERMINATION_WAIT, self.clock):
                raise PipelineError("RUN_OWNERSHIP", "A prior worker is still running and could not be stopped",
                                    "recovery")
            confirmed.append({"generation": generation, "status": "terminated"})
        for record in self.journal.unstopped_workers():
            self.journal.worker_stopped(record["generation"], confirmed=True, reason="prior_run")
        return confirmed

    def shutdown(self) -> None:
        if self.worker is not None:
            handle, self.worker = self.worker, None
            stop = handle.shutdown(clock=self.clock)
            self.journal.worker_stopped(handle.generation, confirmed=stop["confirmed"], reason="shutdown")

    # One attempt -------------------------------------------------------------
    def run_sample(self, sample_id: str) -> AttemptResult:
        handle = self.worker
        identity = AttemptIdentity(sample_id, uuid.uuid4().hex, handle.generation, self.config_sha256)
        began = self.clock()
        self.journal.reserve(identity)  # Raises (run stops) unless durable: dispatch nothing.
        reservation_seconds = self.clock() - began
        self._fault("reserved")
        dispatched = self.clock()
        deadline = dispatched + self.timeout
        metrics: JSON = {"reservation_seconds": reservation_seconds, "generation": handle.generation}
        message = {"type": "dispatch", "generation": handle.generation, "attempt_id": identity.attempt_id,
                   "sample_id": sample_id, "budget_seconds": self.timeout}
        lost = None
        received = None
        try:
            if handle.send(message, deadline, self.clock):
                self._fault("dispatched")
                received = self._await_result(handle, identity, deadline)
        except WorkerLost as exc:
            lost = str(exc)
        receipt = self.clock()
        metrics.update(attempt_seconds=receipt - dispatched, stale_messages=handle.stale_messages)
        if received is not None and receipt < deadline:
            self._fault("received")
            return self._accept(identity, received, metrics, dispatched)
        # Expiry, crash or protocol loss: terminal now, never retried.
        self.worker = None
        stop = handle.terminate(self.clock)
        self.losses += 1
        metrics.update(termination_seconds=stop["termination_seconds"], termination_confirmed=stop["confirmed"],
                       overshoot_seconds=max(0.0, self.clock() - deadline) if lost is None else None)
        status, error = (("timeout", {"code": "TIME_LIMIT", "stage": "supervisor",
                                      "message": "Full attempt deadline expired; late output quarantined"})
                         if lost is None else
                         ("failed", {"code": "EXECUTION_UNCERTAIN", "stage": "worker",
                                     "message": "Worker lost during the attempt; effects are uncertain"}))
        self.journal.fail(identity, status, error, metrics)
        self.journal.worker_stopped(handle.generation, confirmed=stop["confirmed"],
                                    reason="timeout" if lost is None else "worker_lost")
        self._quarantine(identity.attempt_id)
        if not stop["confirmed"]:
            raise PipelineError("RECOVERY_FAILED", "Prior worker termination could not be confirmed", "recovery")
        return AttemptResult(sample_id, identity.attempt_id, status, error, metrics)

    def _quarantine(self, attempt_id: str) -> None:
        try:
            self.journal.quarantine(attempt_id)
        except OSError:
            pass  # Publication reads only the journal; resume quarantines leftovers again.

    def _await_result(self, handle: WorkerHandle, identity: AttemptIdentity, deadline: float) -> JSON | None:
        while True:
            message = handle.receive(deadline, self.clock)
            if message is None:
                return None
            if (message.get("type") == "result_ready" and message.get("attempt_id") == identity.attempt_id
                    and message.get("generation") == identity.generation
                    and message.get("sample_id") == identity.sample_id):
                return message
            handle.stale_messages += 1  # Stale/foreign messages are rejected, never accepted.
            if message.get("type") not in {"result_ready"}:
                raise WorkerLost("unexpected message type")

    def _accept(self, identity: AttemptIdentity, message: JSON, metrics: JSON, dispatched: float) -> AttemptResult:
        try:
            outcome = self.journal.read_staged(identity.attempt_id, "outcome.json")
            if (not isinstance(outcome, dict) or outcome.get("attempt_id") != identity.attempt_id
                    or outcome.get("status") != message.get("status")):
                raise PipelineError("WORKER_FAILED", "Staged outcome does not match the acknowledgement", "acceptance")
            metrics.update(worker=_bounded_metrics(outcome))
            status = outcome["status"]
            if status in ACCEPTED_STATES:
                prediction = self.journal.read_staged(identity.attempt_id, "prediction.json")
                validate_prediction(prediction)
                if prediction["id"] != identity.sample_id:
                    raise PipelineError("WORKER_FAILED", "Staged prediction identity mismatch", "acceptance")
                began = self.clock()
                self.journal.accept(identity, status, prediction, metrics)  # Durable before next dispatch.
                metrics["acceptance_seconds"] = self.clock() - began
                return AttemptResult(identity.sample_id, identity.attempt_id, status, None, metrics)
            error = outcome.get("error") if isinstance(outcome.get("error"), dict) else {"code": "WORKER_FAILED"}
            status = "timeout" if status == "timeout" else "failed"
        except PipelineError as exc:
            if exc.stage == "journal":
                raise  # Acceptance durability failed: the reservation stays uncertain; stop.
            status, error = "failed", exc.record()
        self.journal.fail(identity, status, error, metrics)
        self._quarantine(identity.attempt_id)
        return AttemptResult(identity.sample_id, identity.attempt_id, status, error, metrics)


def _bounded_metrics(outcome: JSON) -> JSON:
    keys = ("elapsed", "steps", "stop_reason", "timings", "metrics", "peak_memory_bytes")
    return {k: outcome.get(k) for k in keys}
