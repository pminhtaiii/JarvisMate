"""Actual CUDA probes and phase-specific resident/peak memory accounting."""
from __future__ import annotations

from contextlib import contextmanager
import subprocess
import time


class Unsupported(RuntimeError):
    pass


class ResourceLimit(RuntimeError):
    pass


def hardware(torch, config: dict) -> tuple[dict, str, int]:
    if not torch.cuda.is_available():
        raise ResourceLimit("CUDA unavailable: use a CUDA-enabled training environment on the target GPU")
    torch.cuda.set_device(0)
    device = torch.cuda.get_device_properties(0)
    free, total = torch.cuda.mem_get_info()
    cap = min(total, int(config["vram_cap_gib"] * 1024**3))
    reserve = max(config["headroom_gib"] * 1024**3, .1 * cap)
    budget = int(min(cap, free + torch.cuda.memory_reserved()) - reserve)
    if budget <= 0:
        raise ResourceLimit("Insufficient free VRAM after operational headroom")
    precision = config["precision"]
    if precision == "auto":
        precision = "bfloat16" if torch.cuda.is_bf16_supported() else "float16"
    if precision == "bfloat16" and not torch.cuda.is_bf16_supported():
        raise Unsupported("BF16 requested but unsupported; create an explicit FP16 profile")
    for selected in {precision, config["inference_dtype"]}:
        dtype = getattr(torch, selected)
        probe = torch.ones((32, 32), device="cuda", dtype=dtype)
        result = probe @ probe
        torch.cuda.synchronize()
        if not torch.isfinite(result).all():
            raise ResourceLimit("CUDA precision kernel probe returned non-finite values")
        del probe, result
    try:
        driver = subprocess.run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                                capture_output=True, text=True, check=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        driver = "unavailable"
    return {"name": device.name, "total_bytes": total, "capability": list(torch.cuda.get_device_capability()),
            "cuda_runtime": torch.version.cuda, "driver": driver, "torch": torch.__version__}, precision, budget


class Memory:
    def __init__(self, torch, budget: int):
        self.torch, self.budget, self.phases = torch, budget, []

    @contextmanager
    def phase(self, name: str):
        cuda = self.torch.cuda
        cuda.synchronize()
        cuda.reset_peak_memory_stats()
        free_before, total = cuda.mem_get_info()
        started = time.perf_counter()
        failed = False
        try:
            yield
        except BaseException:
            failed = True
            raise
        finally:
            cuda.synchronize()
            row = {"phase": name, "seconds": time.perf_counter() - started,
                   "peak_allocated_bytes": cuda.max_memory_allocated(),
                   "peak_reserved_bytes": cuda.max_memory_reserved(),
                   "free_before_bytes": free_before, "free_after_bytes": cuda.mem_get_info()[0],
                   "device_total_bytes": total, "budget_bytes": self.budget}
            self.phases.append(row)
            if not failed and row["peak_reserved_bytes"] > self.budget:
                raise ResourceLimit(f"{name}: peak reserved VRAM exceeds the frozen headroom budget")

    def report(self) -> dict:
        return {"phases": self.phases, "device_sampling": "not sampled; framework peaks and device free snapshots only",
                "peak_allocated_gib": max((r["peak_allocated_bytes"] for r in self.phases), default=0)/1024**3,
                "peak_reserved_gib": max((r["peak_reserved_bytes"] for r in self.phases), default=0)/1024**3}
