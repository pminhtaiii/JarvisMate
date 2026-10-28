"""Shared offline inference setup. Optional dependencies are lazy imports."""
from __future__ import annotations

import importlib.metadata
import os
import random
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path

from ..contracts import PipelineError
from ..jsonio import digest


class ModelResidency:
    """Optional whole-model CPU storage between per-sample inference phases."""

    @contextmanager
    def inference_session(self):
        if not self.cpu_offload:
            yield
            return
        try:
            self.model.to(self.device)
        except Exception as exc:
            raise PipelineError("MODEL_UNAVAILABLE", "Cannot transfer the offloaded model to its device",
                                "model_load") from exc
        try:
            yield
        finally:
            self.model.to("cpu")
            self.torch.cuda.empty_cache()


def inference_session(adapter):
    # Controlled/custom adapters need only the ordinary capability protocol.
    return adapter.inference_session() if hasattr(adapter, "inference_session") else nullcontext()


def model_directory(path: Path | None) -> Path:
    if path is None or not path.is_dir() or not (path / "config.json").is_file():
        raise PipelineError("MODEL_UNAVAILABLE", "A complete local model snapshot is required", "model_load")
    return path.resolve()


def dependencies(device: str, seed: int):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    try:
        import numpy as np
        import torch
        import transformers
        if device not in {"cpu", "cuda"} or (device == "cuda" and not torch.cuda.is_available()):
            raise PipelineError("MODEL_UNAVAILABLE", "Requested inference device is unavailable", "model_load")
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if device == "cuda":
            torch.cuda.manual_seed_all(seed)
            torch.backends.cudnn.benchmark = False
            torch.backends.cudnn.deterministic = True
        torch.use_deterministic_algorithms(True)
        return torch, transformers, np
    except PipelineError:
        raise
    except (ImportError, OSError, RuntimeError) as exc:
        raise PipelineError("MODEL_UNAVAILABLE", "Install the pinned inference extra for this device", "model_load") from exc


def parameter_count(model, limit: int) -> int:
    count = sum(p.numel() for p in model.parameters())
    if count >= limit:
        raise PipelineError("MODEL_UNAVAILABLE", "Model exceeds the parameter budget", "model_load")
    return count


def metadata(path: Path, count: int, device: str, dtype, seed: int) -> dict:
    visible = ("config.json", "generation_config.json", "tokenizer_config.json", "preprocessor_config.json")
    return {"path": str(path), "snapshot": path.name, "parameter_count": count,
            "config_sha256": {f: digest(path / f) for f in visible if (path / f).is_file()},
            "device": device, "dtype": str(dtype), "seed": seed, "do_sample": False,
            "num_beams": 1, "local_files_only": True, "trust_remote_code": False,
            "packages": {p: importlib.metadata.version(p) for p in ("torch", "transformers", "numpy")}}


def stopping_criteria(transformers, remaining_seconds: float):
    if remaining_seconds <= 0:
        raise PipelineError("TIME_LIMIT", "No generation time remains", "inference")
    ends = time.monotonic() + remaining_seconds

    class StopAtDeadline(transformers.StoppingCriteria):
        def __call__(self, input_ids, scores, **kwargs):
            return time.monotonic() >= ends

    return transformers.StoppingCriteriaList([StopAtDeadline()])
