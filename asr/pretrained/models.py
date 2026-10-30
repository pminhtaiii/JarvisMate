"""Local-only Whisper adapters. Inference receives audio paths and settings only."""
from __future__ import annotations

import importlib.metadata
import os
from pathlib import Path
import random
import re
import wave

from lifemate.dataset import wav_info
from lifemate.jsonio import contained, digest, loads, visible_path
from lifemate.model_budget import check_budget

REGISTRY = {
    "whisper-small": ("openai/whisper-small", "transformers"),
    "phowhisper-small": ("vinai/PhoWhisper-small", "transformers"),
    "phowhisper-medium": ("vinai/PhoWhisper-medium", "transformers"),
    "phowhisper-large": ("vinai/PhoWhisper-large", "transformers"),
    "whisper-turbo": ("openai/whisper-large-v3-turbo", "transformers"),
    "whisper-small-ct2": ("openai/whisper-small", "faster-whisper"),
}
DECODING = {"language": "vi", "task": "transcribe", "beam_size": 1,
            "temperature": 0.0, "max_new_tokens": 440, "vad": False,
            "timestamps": False, "condition_on_previous_text": False,
            "initial_prompt": None, "hotwords": None, "batch_size": 1,
            "length_penalty": 1.0, "repetition_penalty": 1.0}


def offline() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")


def packages() -> dict:
    versions = {}
    for name in ("torch", "transformers", "numpy", "faster-whisper", "ctranslate2",
                 "huggingface-hub", "tokenizers", "av", "onnxruntime"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def local_spec(name: str, models_dir: Path) -> dict:
    path = (models_dir / name).resolve(strict=True)
    visible_path(path)
    provenance = loads((path / "provenance.json").read_text(encoding="utf-8"))
    expected_source, engine = REGISTRY[name]
    if (not isinstance(provenance, dict) or provenance.get("source") != expected_source or provenance.get("engine") != engine
            or not isinstance(provenance.get("revision"), str)
            or not re.fullmatch(r"[0-9a-f]{40}", provenance["revision"])
            or not isinstance(provenance.get("assets"), dict) or not provenance["assets"]
            or type(provenance.get("parameter_count")) is not int
            or not 0 < provenance["parameter_count"] < 6_000_000_000
            or not isinstance(provenance.get("generation_defaults"), dict)):
        raise ValueError(f"Invalid local provenance: {name}; run prepare explicitly")
    required = {"config.json", "preprocessor_config.json"}
    if engine == "faster-whisper":
        required |= {"model.bin", "tokenizer.json"}
    if not required <= provenance["assets"].keys():
        raise ValueError(f"Incomplete local assets: {name}; no tokenizer/preprocessor fallback is allowed")
    for relative, sha in provenance["assets"].items():
        if digest(contained(path, relative)) != sha:
            raise ValueError(f"Model asset changed: {name}/{relative}")
    return {"name": name, "path": str(path), "engine": engine, "provenance": provenance}


def require_paired_source(specs: list[dict]) -> None:
    paired = {s["name"]: s for s in specs if s["name"] in {"whisper-small", "whisper-small-ct2"}}
    if len(paired) == 2:
        hf = paired["whisper-small"]["provenance"]
        ct2 = paired["whisper-small-ct2"]["provenance"]
        if hf["revision"] != ct2["revision"] or hf["assets"] != ct2.get("source_assets"):
            raise ValueError("Whisper-small backends must use exactly the same source snapshot/assets")


def read_samples(path: Path, np):
    info = wav_info(path)
    with wave.open(str(path), "rb") as stream:
        raw = stream.readframes(info["frames"])
    if len(raw) != info["frames"] * 2:
        raise ValueError("Truncated WAV payload")
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


class TransformersASR:
    def __init__(self, spec: dict, settings: dict):
        offline()
        import numpy as np
        import torch
        import transformers as hf

        device = settings["device"]
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but unavailable; use --device cpu on Raccoon")
        random.seed(settings["seed"])
        np.random.seed(settings["seed"])
        torch.manual_seed(settings["seed"])
        torch.set_num_threads(settings["threads"])
        torch.use_deterministic_algorithms(True)
        if device == "cuda":
            torch.cuda.manual_seed_all(settings["seed"])
            torch.backends.cudnn.benchmark = False
            torch.backends.cudnn.deterministic = True
            torch.backends.cuda.matmul.allow_tf32 = False
            torch.backends.cudnn.allow_tf32 = False
        dtype = torch.float32 if settings["dtype"] == "float32" else torch.float16
        self.processor = hf.WhisperProcessor.from_pretrained(
            spec["path"], local_files_only=True, trust_remote_code=False)
        self.model = hf.WhisperForConditionalGeneration.from_pretrained(
            spec["path"], local_files_only=True, trust_remote_code=False,
            torch_dtype=dtype, attn_implementation="eager", weights_only=True).to(device).eval()
        count = sum(p.numel() for p in self.model.parameters())
        check_budget(count)
        if count != spec["provenance"]["parameter_count"]:
            raise ValueError("Loaded model parameter count differs from preparation provenance")
        self.np, self.torch, self.device, self.dtype = np, torch, device, dtype
        generation = self.model.generation_config
        self.metadata = {"parameter_count": count, "parameter_count_method": "loaded model.parameters()",
                         "dtype": str(dtype), "device": device, "threads": torch.get_num_threads(),
                         "gpu": torch.cuda.get_device_name() if device == "cuda" else None,
                         "decoding": DECODING | {
                             "suppress_tokens": generation.suppress_tokens,
                             "begin_suppress_tokens": generation.begin_suppress_tokens,
                             "silence_skip": False, "temperature_fallback": False},
                         "packages": packages()}

    def synchronize(self) -> None:
        if self.device == "cuda":
            self.torch.cuda.synchronize()

    def transcribe(self, path: Path) -> str:
        samples = read_samples(path, self.np)
        batch = self.processor(samples, sampling_rate=16000, return_tensors="pt", return_attention_mask=True)
        features = batch["input_features"].to(self.device, dtype=self.dtype)
        kwargs = {"attention_mask": batch["attention_mask"].to(self.device)} if "attention_mask" in batch else {}
        with self.torch.inference_mode():
            output = self.model.generate(
                features, **kwargs, language="vi", task="transcribe",
                do_sample=False, num_beams=1, max_new_tokens=440, return_timestamps=False,
                length_penalty=1.0, repetition_penalty=1.0)
        return self.processor.batch_decode(output, skip_special_tokens=True)[0].strip()


class FasterWhisperASR:
    def __init__(self, spec: dict, settings: dict):
        offline()
        import ctranslate2
        import numpy as np
        from faster_whisper import WhisperModel

        random.seed(settings["seed"])
        np.random.seed(settings["seed"])
        ctranslate2.set_random_seed(settings["seed"])
        self.np = np
        self.model = WhisperModel(spec["path"], device=settings["device"],
                                  compute_type=settings["compute_type"],
                                  cpu_threads=settings["threads"], num_workers=1,
                                  local_files_only=True)
        self.suppress = spec["provenance"]["generation_defaults"].get("suppress_tokens") or [-1]
        self.metadata = {"parameter_count": spec["provenance"]["parameter_count"],
                         "parameter_count_method": "source Whisper architecture instantiated on meta device",
                         "compute_type_requested": settings["compute_type"],
                         "compute_type": str(self.model.model.compute_type),
                         "device": settings["device"], "threads": settings["threads"],
                         "decoding": DECODING | {"suppress_tokens": self.suppress, "suppress_blank": True,
                                                  "silence_skip": False, "temperature_fallback": False},
                         "packages": packages(), "gpu": None,
                         "engine_caveat": "CT2 feature extraction/token suppression and quantization can differ from HF"}

    def synchronize(self) -> None:
        # CT2 generate is synchronous; the lazy segments are fully consumed below.
        pass

    def transcribe(self, path: Path) -> str:
        samples = read_samples(path, self.np)
        segments, _ = self.model.transcribe(
            samples, language="vi", task="transcribe", beam_size=1, best_of=1,
            temperature=0.0, vad_filter=False, word_timestamps=False, without_timestamps=True,
            condition_on_previous_text=False, initial_prompt=None, prefix=None, hotwords=None,
            compression_ratio_threshold=None, log_prob_threshold=None, no_speech_threshold=None,
            suppress_tokens=self.suppress, suppress_blank=True, max_new_tokens=440,
            length_penalty=1.0, repetition_penalty=1.0)
        return "".join(segment.text for segment in segments).strip()


def adapter(spec: dict, settings: dict):
    if spec["engine"] == "transformers":
        return TransformersASR(spec, settings)
    return FasterWhisperASR(spec, settings)
