"""Explicit host inventory and CUDA kernel checks; imports never allocate CUDA."""
from __future__ import annotations

import ctypes
import os
import platform
import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .storage import new_directory, write_json

GIB = 1024 ** 3
PINS = {"torch": "2.9.0+cu128", "transformers": "4.57.1", "numpy": "2.3.4", "peft": "0.17.1",
        "accelerate": "1.10.1", "lm-format-enforcer": "0.11.3"}


def packages():
    result = {}
    for name in (*PINS, "bitsandbytes", "safetensors", "tokenizers", "pip", "setuptools"):
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = None
    return result


def checked_packages(*, nf4=False):
    observed = packages()
    required = PINS | ({"bitsandbytes": "0.48.1"} if nf4 else {})
    differing = {k: {"required": v, "observed": observed[k]} for k, v in required.items() if observed[k] != v}
    if differing:
        raise ValueError(f"Package/build mismatch: {differing}")
    return observed


def validate_lock(config):
    """Model-free full closure/build lock verification before model/device loading."""
    from .storage import read_json, file_hash
    lock = config.require("environment_lock")
    manifest = read_json(lock.with_suffix(".manifest.json"))
    environment = manifest.get("environment", {})
    if (manifest.get("schema") != "lifemate-platform-lock-v1" or manifest.get("lock_sha256") != file_hash(lock)
            or manifest.get("profile") != config.source["environment_profile"]
            or environment.get("sys_platform") != sys.platform
            or environment.get("python_full_version") != platform.python_version()
            or environment.get("platform_machine") != platform.machine() or not manifest.get("packages")):
        raise ValueError("Full lock/profile/Python/architecture identity mismatch")
    for package, pin in manifest["packages"].items():
        try:
            actual = version(package)
        except PackageNotFoundError:
            actual = None
        if actual != pin:
            raise ValueError(f"Locked package/build mismatch: {package}")
    return file_hash(lock)


def command(args):
    try:
        run = subprocess.run(args, capture_output=True, text=True, timeout=15,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        return run.stdout.strip() if run.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def capacity(value):
    return {"bytes": value, "GB": value / 1e9, "GiB": value / GIB} if value is not None else None


def host_inventory(root: Path):
    ram = None
    if os.name == "nt":
        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        *[(n, ctypes.c_ulonglong) for n in ("total", "available", "page_total", "page_free",
                                                          "virtual_total", "virtual_free", "extended")]]
        state = Memory()
        state.length = ctypes.sizeof(state)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
            ram = {"physical": capacity(state.total), "available": capacity(state.available)}
    disk = shutil.disk_usage(root)
    smi = command(["nvidia-smi", "--query-gpu=name,uuid,driver_version,memory.total,memory.free",
                   "--format=csv,noheader,nounits"])
    gpu = []
    for line in smi.splitlines() if smi else []:
        name, uuid, driver, physical, free = [p.strip() for p in line.split(",")]
        gpu.append({"name": name, "uuid": uuid, "driver": driver, "physical": capacity(int(physical) * 1024**2),
                    "free": capacity(int(free) * 1024**2), "source": "nvidia-smi MiB precision", "allocation": False})
    return {"platform": platform.platform(), "python": sys.version, "executable": sys.executable,
            "machine": platform.machine(), "ram": ram, "disk": {"total": capacity(disk.total), "free": capacity(disk.free)},
            "gpus": gpu, "packages": packages(), "toolkit_nvcc": command(["nvcc", "--version"]),
            "cuda_runtime": None, "kernel_status": "not_run"}


def gpu_preflight(output_root: Path, *, profile: str, precision="bf16", nf4=False):
    report = host_inventory(output_root)
    directory = new_directory(output_root / "gpu-preflight", profile)
    status, reason = "failed", None
    try:
        checked_packages(nf4=nf4)
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
        import torch
        if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
            raise ValueError("One explicitly selected CUDA device is required; no CPU fallback")
        properties = torch.cuda.get_device_properties(0)
        report.update(cuda_runtime=torch.version.cuda, cudnn=torch.backends.cudnn.version(),
                      compute_capability=list(torch.cuda.get_device_capability(0)), arch_list=torch.cuda.get_arch_list(),
                      physical_vram=capacity(properties.total_memory), operating_cap=capacity(min(12 * GIB, properties.total_memory)))
        dtype = torch.bfloat16 if precision == "bf16" else torch.float16
        torch.manual_seed(42)
        torch.cuda.manual_seed_all(42)
        torch.use_deterministic_algorithms(True)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        report["seed"] = 42
        if precision == "bf16" and not torch.cuda.is_bf16_supported():
            raise ValueError("BF16 is unsupported; select a new explicit FP16 profile")
        torch.cuda.reset_peak_memory_stats()
        a = torch.randn((64, 64), device="cuda", dtype=dtype, requires_grad=True)
        loss = (a @ a.T).float().square().mean()
        loss.backward()
        torch.cuda.synchronize()
        if not torch.isfinite(loss) or not torch.isfinite(a.grad).all():
            raise ValueError("Nonfinite CUDA matmul/backward")
        if nf4:
            import bitsandbytes as bnb
            layer = bnb.nn.Linear4bit(64, 64, bias=False, quant_type="nf4", compress_statistics=True,
                                     compute_dtype=dtype).to("cuda")
            x = a.detach().requires_grad_()
            layer(x).float().square().mean().backward()
            if layer.weight.quant_state is None or layer.weight.quant_type != "nf4" or not torch.isfinite(x.grad).all():
                raise ValueError("NF4 CUDA kernel/dequantization/backward failed")
            report["nf4_kernel"] = "passed"
        report.update(kernel_status="passed", precision=precision, memory=cuda_memory(torch))
        status = "passed"
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"[:500]
    report.update(status=status, reason=reason, profile=profile)
    write_json(directory / "compatibility.json", report)
    write_json(directory / "outcome.json", {"status": status, "reason": reason, "scope": "kernels_only"})
    return report | {"directory": str(directory)}


def cuda_memory(torch):
    free, total = torch.cuda.mem_get_info()
    return {"allocated_peak": torch.cuda.max_memory_allocated(), "reserved_peak": torch.cuda.max_memory_reserved(),
            "free_device_bytes": free, "physical_bytes": total,
            "process_peak_bytes": None, "device_peak_bytes": None,
            "whole_process_peak_reason": "requires sampled NVML; allocator peaks alone are insufficient",
            "operating_cap_bytes": min(12 * GIB, total), "headroom_bytes": GIB}
