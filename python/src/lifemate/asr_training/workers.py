"""Single-model subprocesses: persistent audio inference or one training epoch."""
from __future__ import annotations

import multiprocessing
from pathlib import Path
import time
import socket

from .storage import read, write, environment
from .resources import Memory, hardware, Unsupported, ResourceLimit
from .models import dependencies, load, generate, prepare_labels


def error_status(exc: BaseException) -> str:
    message = str(exc).lower().replace(" ", "")
    if "outofmemory" in message or isinstance(exc, ResourceLimit):
        return "failed_oom" if "outofmemory" in message else "failed"
    return "unsupported" if isinstance(exc, (Unsupported, ImportError)) else "failed"


def worker(connection, job: dict):
    memory = None
    try:
        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex
        def no_network(sock, address):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                raise OSError("Network disabled in ASR GPU workers")
            return original_connect(sock, address)
        def no_network_ex(sock, address):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                raise OSError("Network disabled in ASR GPU workers")
            return original_connect_ex(sock, address)
        socket.socket.connect = no_network
        socket.socket.connect_ex = no_network_ex
        torch, hf, np = dependencies(job["config"]["seed"])
        hw, precision, budget = hardware(torch, job["config"])
        if job.get("expected_hardware") and hw != job["expected_hardware"]:
            raise ValueError("GPU/runtime changed after preflight")
        memory = Memory(torch, budget)
        if job["mode"] == "hardware":
            connection.send({"status": "ok", "hardware": hw, "precision": precision,
                             "free_bytes": torch.cuda.mem_get_info()[0], "operational_budget_bytes": budget,
                             "environment": environment()})
            return
        adapter = str(Path(job["checkpoint"]) / "adapter") if job.get("checkpoint") else None
        training = job["mode"] == "train"
        native = job["config"]["experiment"] == "E3" and (training or job.get("native", False))
        started = time.perf_counter()
        with memory.phase("load"):
            model, processor, targets = load(job["snapshot"], job["config"],
                    precision if training or native else job["config"]["inference_dtype"],
                    training=training, adapter_path=adapter, native=native)
        initialized = {"load_seconds": time.perf_counter() - started, "targets": targets,
                       "hardware": hw, "precision": precision, "environment": environment()}
        from lifemate.model_budget import check_budget
        adapter_count = sum(p.numel() for name, p in model.named_parameters() if "lora_" in name)
        logical = job["base_parameters"] + adapter_count if native or training else sum(p.numel() for p in model.parameters())
        check_budget(logical)
        initialized.update(logical_parameters=logical, adapter_parameters=adapter_count,
                           quantized_modules=sum(type(m).__name__ == "Linear4bit" for m in model.modules()))
        if training:
            from .trainer import train_epoch
            result = train_epoch(model, processor, job | {"precision": precision}, torch, np, memory)
            connection.send({"status": "ok", **result, **initialized, "memory": memory.report()})
            return
        if job["mode"] == "export":
            output = Path(job["export_path"])
            if output.exists():
                raise ValueError("Export path already exists")
            with memory.phase("export"):
                model.save_pretrained(output, safe_serialization=True)
                processor.save_pretrained(output)
            # A separate worker below performs the fresh-process local-only round trip.
            connection.send({"status": "ok", "memory": memory.report(), **initialized})
            return
        connection.send({"status": "ready", "memory": memory.report(), **initialized})
        while True:
            request = connection.recv()
            if request is None:
                connection.send({"status": "closed", "memory": memory.report()})
                break
            started = time.perf_counter()
            torch.cuda.synchronize()
            with memory.phase("generation"):
                prediction = generate(model, processor, Path(request), np, torch)
            torch.cuda.synchronize()
            connection.send({"status": "ok", "prediction": prediction,
                             "latency_seconds": time.perf_counter() - started})
    except (EOFError, BrokenPipeError):
        pass
    except BaseException as exc:
        try:
            connection.send({"status": error_status(exc), "error": f"{type(exc).__name__}: {str(exc)[:2000]}",
                             "memory": memory.report() if memory else None})
        except (EOFError, BrokenPipeError, OSError):
            pass
    finally:
        connection.close()


class Session:
    def __init__(self, job: dict, *, target=worker):
        context = multiprocessing.get_context("spawn")
        self.connection, child = context.Pipe()
        self.process = context.Process(target=target, args=(child, job))
        self.process.start()
        child.close()

    def receive(self, timeout: float) -> dict:
        if not self.connection.poll(timeout):
            raise TimeoutError(f"GPU worker exceeded {timeout:g} seconds; killed without retry")
        try:
            return self.connection.recv()
        except EOFError as exc:
            raise RuntimeError("GPU worker exited without a response") from exc

    def request(self, path: Path, timeout: float) -> dict:
        self.connection.send(str(path))
        return self.receive(timeout)

    def close(self) -> dict | None:
        closing = None
        try:
            if self.process.is_alive():
                self.connection.send(None)
                if self.connection.poll(2):
                    closing = self.connection.recv()
                self.process.join(2)
        except (EOFError, OSError):
            pass
        finally:
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(5)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(5)
            self.connection.close()
        return closing


def once(job: dict, timeout: float) -> dict:
    session = Session(job)
    try:
        return session.receive(timeout)
    finally:
        session.close()
